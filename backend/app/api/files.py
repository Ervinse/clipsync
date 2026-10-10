"""文件路由：分片上传 + 下载 + 删除"""
import logging
import mimetypes
import os
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File as FastAPIFile, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, delete as sql_delete, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, UserRole, File, UploadSession, AccessCode
from ..schemas import (
    UploadInitRequest,
    UploadInitResponse,
    UploadCompleteRequest,
    FileResponse,
    FileListResponse,
)
from ..core.deps import get_current_user
from ..core.storage import (
    ensure_user_storage_dir,
    ensure_upload_temp_dir,
    get_upload_temp_dir,
    get_file_path,
    generate_stored_name,
    cleanup_upload_temp,
    is_valid_upload_id,
    delete_file as storage_delete_file,
)
from ..core.http_utils import content_disposition
from ..core.timeutil import utcnow
from ..core.ws_manager import manager
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

_READ_BLOCK = 64 * 1024

# 单个上传的分片总数上限：chunk_size 过小会产生海量小文件与超大列表，拖垮事件循环
MAX_TOTAL_CHUNKS = 10_000

# 正在合并的 upload_id（后端单 worker，检查与加入之间无 await，在 asyncio 下是原子的）
_completing: set[str] = set()


def _require_valid_upload_id(upload_id: str) -> None:
    """格式不对（含大写写法）的 upload_id 一律按会话不存在处理，不进入查库与磁盘操作"""
    if not is_valid_upload_id(upload_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或无权访问")


async def _reserved_bytes(db: AsyncSession, user_id: int, exclude_upload_id: str | None = None) -> int:
    """
    已占用配额 = 已落盘文件 + 进行中的上传会话声明大小。
    安全红线：把未完成会话也计入，防止并发开多个会话各自通过 init 校验后超配。
    """
    result = await db.execute(
        select(func.coalesce(func.sum(File.size), 0)).where(File.user_id == user_id)
    )
    used = int(result.scalar())
    return used + await upload_reserved_bytes(db, user_id, exclude_upload_id)


async def upload_reserved_bytes(db: AsyncSession, user_id: int, exclude_upload_id: str | None = None) -> int:
    """进行中上传会话的声明大小之和（「上传中」占用的配额，/auth/me 与文件列表也会返回）"""
    stmt = select(func.coalesce(func.sum(UploadSession.total_size), 0)).where(
        UploadSession.user_id == user_id
    )
    if exclude_upload_id:
        stmt = stmt.where(UploadSession.upload_id != exclude_upload_id)
    result = await db.execute(stmt)
    return int(result.scalar())


def _merge_chunks(temp_dir: Path, total_chunks: int, final_path: Path) -> int:
    """同步合并分片（在线程池中执行，避免阻塞事件循环），返回合并后字节数"""
    written = 0
    with open(final_path, "wb") as outfile:
        for index in range(total_chunks):
            with open(temp_dir / str(index), "rb") as infile:
                while block := infile.read(_READ_BLOCK):
                    outfile.write(block)
                    written += len(block)
    return written


def _save_chunk(src, partial_path: Path, limit: int) -> int:
    """
    同步写分片（在线程池中执行）：边写边计数。
    超过 limit 立即停止并删除半截文件，返回 -1；否则返回写入字节数。
    """
    written = 0
    try:
        with open(partial_path, "wb") as f:
            while block := src.read(_READ_BLOCK):
                written += len(block)
                if written > limit:
                    break
                f.write(block)
    except OSError:
        # 磁盘写满等 IO 错误：不留半截 .part（客户端重试会不断堆积，加重磁盘满）
        try:
            partial_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    if written > limit:
        partial_path.unlink(missing_ok=True)
        return -1
    return written


def _count_chunks(temp_dir: Path) -> int:
    """统计已落盘的分片数（只算纯数字文件名，不含 .part 临时文件）"""
    return sum(1 for p in temp_dir.iterdir() if p.is_file() and p.name.isdigit())


def _list_chunk_indexes(temp_dir: Path) -> list[int]:
    """已落盘分片的索引，升序（目录不存在返回空列表）"""
    if not temp_dir.is_dir():
        return []
    return sorted(int(p.name) for p in temp_dir.iterdir() if p.is_file() and p.name.isdigit())


def _open_for_download(path: Path):
    """先打开再 fstat 取大小：此后文件即使被删除，已打开的句柄仍能读完，Content-Length 与实际一致"""
    f = open(path, "rb")
    try:
        size = os.fstat(f.fileno()).st_size
    except OSError:
        f.close()
        raise
    return f, size


def _iter_handle(f):
    """流式读取已打开的文件（StreamingResponse 会在线程池中迭代同步生成器）"""
    with f:
        while block := f.read(_READ_BLOCK):
            yield block


async def stream_file_response(file_record: File, missing_detail: str = "文件已丢失") -> StreamingResponse:
    """
    统一的流式下载响应（登录下载与访问码下载共用）

    missing_detail：磁盘文件不存在时的提示；公开访问码路径传「访问码无效或已失效」，不暴露码本身有效。
    """
    file_path = get_file_path(file_record.user_id, file_record.stored_name)
    try:
        f, size = await run_in_threadpool(_open_for_download, file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=missing_detail)

    return StreamingResponse(
        _iter_handle(f),
        media_type=file_record.mime_type,
        headers={
            # 安全红线：文件名来自用户，按 RFC 6266 编码，杜绝头注入
            "Content-Disposition": content_disposition(file_record.original_name),
            "Content-Length": str(size),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/upload/init", response_model=UploadInitResponse)
async def init_upload(
    data: UploadInitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    初始化分片上传会话

    安全红线：
    - 单文件大小不超过 MAX_FILE_BYTES，分片大小不超过 CHUNK_SIZE
    - 已用 + 进行中会话 + 本次大小 <= 配额
    - 单用户进行中会话数有上限（防磁盘耗尽）
    """
    if data.total_size > settings.MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小超过限制（最大 {settings.MAX_FILE_BYTES // (1024 * 1024)} MB）",
        )

    # 分片大小：不超过 CHUNK_SIZE，且不小于让分片数落在 MAX_TOTAL_CHUNKS 以内的最小值
    min_chunk_size = -(-data.total_size // MAX_TOTAL_CHUNKS)  # 向上取整
    chunk_size = min(max(data.chunk_size, min_chunk_size), settings.CHUNK_SIZE)
    if (data.total_size + chunk_size - 1) // chunk_size > MAX_TOTAL_CHUNKS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="分片数过多",
        )

    # 清理当前用户已过期的会话，避免其永久占用配额与会话名额
    expire_before = utcnow() - timedelta(hours=settings.UPLOAD_SESSION_TTL_HOURS)
    result = await db.execute(
        select(UploadSession.upload_id).where(
            UploadSession.user_id == current_user.id,
            UploadSession.created_at < expire_before,
        )
    )
    expired_ids = [row[0] for row in result.all()]
    if expired_ids:
        await db.execute(sql_delete(UploadSession).where(UploadSession.upload_id.in_(expired_ids)))
        await db.commit()
        for expired_id in expired_ids:
            await run_in_threadpool(cleanup_upload_temp, expired_id)

    # 锁住当前用户行，把「数会话 + 算配额 + 插入新会话」串行化，防止并发 init 各自通过校验后超配、超额开会话。
    # 加锁前先 commit：MySQL 默认 REPEATABLE READ，get_current_user 的鉴权读已固定本事务读视图，
    # 若不先结束该视图，加锁后的 count / sum 仍读旧快照，锁形同虚设；commit 开启新读视图（expire_on_commit=False，current_user 仍可用）。
    await db.commit()
    await db.execute(select(User.id).where(User.id == current_user.id).with_for_update())

    result = await db.execute(
        select(func.count()).select_from(UploadSession).where(UploadSession.user_id == current_user.id)
    )
    if result.scalar() >= settings.MAX_UPLOAD_SESSIONS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="进行中的上传过多，请先完成或等待过期",
        )

    reserved = await _reserved_bytes(db, current_user.id)
    if reserved + data.total_size > current_user.quota_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="存储配额不足",
        )

    total_chunks = (data.total_size + chunk_size - 1) // chunk_size

    upload_id = str(uuid.uuid4())
    db.add(UploadSession(
        upload_id=upload_id,
        user_id=current_user.id,
        original_name=data.original_name,
        total_size=data.total_size,
        total_chunks=total_chunks,
        received_chunks=0,
        chunk_size=chunk_size,
        created_at=utcnow(),
    ))
    await db.commit()

    await run_in_threadpool(ensure_upload_temp_dir, upload_id)

    return UploadInitResponse(upload_id=upload_id, total_chunks=total_chunks, chunk_size=chunk_size)


@router.delete("/upload/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_upload(
    upload_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    取消进行中的上传：删除会话（立即释放其占用的配额）并清理临时分片

    安全红线：删除条件带 user_id，他人会话与不存在统一 404
    """
    _require_valid_upload_id(upload_id)
    if upload_id in _completing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该上传正在合并中")

    result = await db.execute(
        sql_delete(UploadSession).where(
            UploadSession.upload_id == upload_id,
            UploadSession.user_id == current_user.id,  # 安全红线：归属校验
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或无权访问")
    await db.commit()

    await run_in_threadpool(cleanup_upload_temp, upload_id)
    return None


@router.post("/upload/chunk", status_code=status.HTTP_200_OK)
async def upload_chunk(
    upload_id: str = Form(..., min_length=36, max_length=36),
    chunk_index: int = Form(..., ge=0),
    chunk_data: UploadFile = FastAPIFile(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    上传单个分片

    安全红线：
    - upload_id 必须归属当前用户（查库时带 user_id）
    - chunk_index 在 [0, total_chunks) 内；磁盘名只用整数索引
    - 单分片字节数不得超过会话的 chunk_size，边写边计数，超限立即中止并删除
    """
    _require_valid_upload_id(upload_id)
    result = await db.execute(
        select(UploadSession).where(
            UploadSession.upload_id == upload_id,
            UploadSession.user_id == current_user.id,  # 安全红线：归属校验
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或无权访问")

    if chunk_index >= session.total_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"分片索引超出范围（最大 {session.total_chunks - 1}）",
        )

    # 会话过期：不再接收分片，顺带清理
    if session.created_at < utcnow() - timedelta(hours=settings.UPLOAD_SESSION_TTL_HOURS):
        await db.execute(sql_delete(UploadSession).where(UploadSession.upload_id == upload_id))
        await db.commit()
        await run_in_threadpool(cleanup_upload_temp, upload_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话已过期")

    # 临时目录由 init 创建；不存在说明会话已被清理，不能用 ensure_* 重建（否则留下孤儿目录）
    temp_dir = get_upload_temp_dir(upload_id)
    if not await run_in_threadpool(temp_dir.is_dir):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或无权访问")

    # 每个分片的期望大小：非最后一片等于 chunk_size，最后一片为剩余字节数
    if chunk_index < session.total_chunks - 1:
        expected_size = session.chunk_size
    else:
        expected_size = session.total_size - session.chunk_size * (session.total_chunks - 1)

    chunk_path = temp_dir / str(chunk_index)
    # 临时名带随机后缀：同一分片并发重传时各写各的，不会互相截断
    partial_path = temp_dir / f"{chunk_index}.{uuid.uuid4().hex}.part"

    # 写盘期间临时目录可能被并发的 complete / 过期清理 / 删除用户 rmtree 掉，
    # 此时各文件操作抛 FileNotFoundError，一律按会话已结束处理（404），不留半截文件。
    try:
        written = await run_in_threadpool(_save_chunk, chunk_data.file, partial_path, expected_size)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或已结束")
    if written < 0:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="分片大小超过限制",
        )
    if written != expected_size:
        await run_in_threadpool(partial_path.unlink, missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"分片大小与预期不符（应为 {expected_size} 字节）",
        )

    # 写完再原子替换，断点续传重传同一分片时不会留下半截文件
    try:
        await run_in_threadpool(partial_path.replace, chunk_path)
    except FileNotFoundError:
        await run_in_threadpool(partial_path.unlink, missing_ok=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或已结束")

    try:
        received_count = await run_in_threadpool(_count_chunks, temp_dir)
    except FileNotFoundError:
        # 分片落盘后临时目录被并发的 cancel / complete / 过期清理 rmtree 掉：会话已结束
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或已结束")
    # 显式 UPDATE + 校验 rowcount：重传已存在的分片时 received_chunks 可能不变，
    # 靠 ORM 脏检查则不会发出 UPDATE，无法察觉会话已被并发删除。显式 UPDATE 的
    # rowcount==0 才能可靠判定「会话行已不存在」（MySQL 方言启用 FOUND_ROWS，
    # rowcount 为匹配行数而非改动行数，重传未变分片仍匹配到 1 行）。
    result = await db.execute(
        sql_update(UploadSession)
        .where(
            UploadSession.upload_id == upload_id,
            UploadSession.user_id == current_user.id,  # 安全红线：归属校验
        )
        .values(received_chunks=received_count)
    )
    if result.rowcount == 0:
        # 写分片期间会话被 complete / 过期清理 / 删除用户删掉了
        await db.rollback()
        await run_in_threadpool(cleanup_upload_temp, upload_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或已结束")
    await db.commit()

    return {
        "message": "分片上传成功",
        "chunk_index": chunk_index,
        "received_chunks": received_count,
        "total_chunks": session.total_chunks,
    }


@router.post("/upload/complete", response_model=FileResponse)
async def complete_upload(
    data: UploadCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    完成上传：校验分片完整 + 流式合并 + 写记录 + 清理临时 + 广播

    安全红线：
    - 校验 upload_id 归属
    - 合并后实际大小必须等于声明大小（声明大小已在 init 时过配额）
    - 合并后再次按实际占用校验配额
    - 同一 upload_id 不允许并发 complete（否则会写出两条 File 记录、重复占用配额）
    """
    _require_valid_upload_id(data.upload_id)
    if data.upload_id in _completing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该上传正在合并中")
    _completing.add(data.upload_id)
    try:
        return await _complete_upload(data, current_user, db)
    finally:
        _completing.discard(data.upload_id)


async def _complete_upload(data: UploadCompleteRequest, current_user: User, db: AsyncSession) -> FileResponse:
    """complete 的实际逻辑（调用方负责互斥）"""
    result = await db.execute(
        select(UploadSession).where(
            UploadSession.upload_id == data.upload_id,
            UploadSession.user_id == current_user.id,  # 安全红线：归属校验
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或无权访问")

    # 会话过期：拒绝合并并清理
    if session.created_at < utcnow() - timedelta(hours=settings.UPLOAD_SESSION_TTL_HOURS):
        await db.execute(sql_delete(UploadSession).where(UploadSession.upload_id == data.upload_id))
        await db.commit()
        await run_in_threadpool(cleanup_upload_temp, data.upload_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话已过期")

    temp_dir = get_upload_temp_dir(data.upload_id)
    received = await run_in_threadpool(_list_chunk_indexes, temp_dir)
    # received 是排好序、不重复的非负整数（文件名唯一），长度相等且末项为 n-1 即为 0..n-1，
    # 不构造 list(range(n))，避免分片数很大时在事件循环里占用大量内存与 CPU
    if len(received) != session.total_chunks or (
        received and received[-1] != session.total_chunks - 1
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"分片不完整（已收到 {len(received)} / {session.total_chunks}）",
        )

    stored_name = generate_stored_name()
    final_path = (await run_in_threadpool(ensure_user_storage_dir, current_user.id)) / stored_name

    try:
        actual_size = await run_in_threadpool(_merge_chunks, temp_dir, session.total_chunks, final_path)
    except OSError:
        logger.exception("合并分片失败 upload_id=%s", data.upload_id)
        await run_in_threadpool(final_path.unlink, missing_ok=True)
        await run_in_threadpool(cleanup_upload_temp, data.upload_id)
        await db.execute(sql_delete(UploadSession).where(UploadSession.upload_id == data.upload_id))
        await db.commit()
        # 安全红线：不把底层异常细节（路径等）回传客户端
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="文件合并失败")

    async def _abort(detail: str):
        await run_in_threadpool(final_path.unlink, missing_ok=True)
        await run_in_threadpool(cleanup_upload_temp, data.upload_id)
        await db.execute(sql_delete(UploadSession).where(UploadSession.upload_id == data.upload_id))
        await db.commit()
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=detail)

    if actual_size != session.total_size:
        await _abort("文件实际大小与声明不符")

    reserved = await _reserved_bytes(db, current_user.id, exclude_upload_id=data.upload_id)
    if reserved + actual_size > current_user.quota_bytes:
        await _abort("存储配额不足")

    mime_type, _ = mimetypes.guess_type(session.original_name)

    file_record = File(
        user_id=current_user.id,
        original_name=session.original_name,
        stored_name=stored_name,
        size=actual_size,
        mime_type=mime_type or "application/octet-stream",
        created_at=utcnow(),
    )
    db.add(file_record)
    await db.execute(sql_delete(UploadSession).where(UploadSession.upload_id == data.upload_id))
    try:
        await db.commit()
    except Exception:
        # 提交失败：记录未落库，删掉已合并的文件，避免磁盘上留下不计配额的孤儿文件
        await run_in_threadpool(final_path.unlink, missing_ok=True)
        raise
    # 无需 refresh：flush 后 id 已回填，created_at 显式赋值，expire_on_commit=False

    await run_in_threadpool(cleanup_upload_temp, data.upload_id)

    await manager.broadcast_to_user(
        user_id=current_user.id,
        message={
            "type": "file_added",
            "data": {
                "id": file_record.id,
                "original_name": file_record.original_name,
                "size": file_record.size,
            },
        },
    )

    return FileResponse(
        id=file_record.id,
        original_name=file_record.original_name,
        size=file_record.size,
        mime_type=file_record.mime_type,
        created_at=file_record.created_at,
    )


@router.get("", response_model=FileListResponse)
async def list_files(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的文件列表 + 存储统计

    安全红线：查询强制按 user_id 过滤
    """
    result = await db.execute(
        select(File)
        .where(File.user_id == current_user.id)
        .order_by(File.created_at.desc())
    )
    files = result.scalars().all()

    return FileListResponse(
        items=[
            FileResponse(
                id=f.id,
                original_name=f.original_name,
                size=f.size,
                mime_type=f.mime_type,
                created_at=f.created_at,
            )
            for f in files
        ],
        total=len(files),
        used_bytes=sum(f.size for f in files),
        reserved_bytes=await upload_reserved_bytes(db, current_user.id),
        quota_bytes=current_user.quota_bytes,
    )


@router.get("/{file_id}/download")
async def download_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    下载文件（流式响应）

    安全红线：
    - 仅允许文件归属者与 superadmin 下载；admin 不可下载他人文件
    - 按 file_id 查库取 stored_name 拼路径，防穿越
    """
    result = await db.execute(select(File).where(File.id == file_id))
    file_record = result.scalar_one_or_none()

    is_owner = file_record is not None and file_record.user_id == current_user.id
    is_superadmin = current_user.role == UserRole.SUPERADMIN

    if file_record is None or not (is_owner or is_superadmin):
        # 不存在与无权限统一 404，不暴露他人文件 ID 是否存在
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在")

    return await stream_file_response(file_record)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_endpoint(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    删除文件：记录 + 磁盘 + 级联删除访问码 + 广播

    安全红线：
    - 仅归属者可删除（superadmin 也不越权删除他人文件）
    - 同时删除指向该文件的访问码，源文件删除后文件码立即失效
    """
    result = await db.execute(
        select(File).where(
            File.id == file_id,
            File.user_id == current_user.id,  # 安全红线：仅归属者
        )
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在或无权访问")

    await db.execute(sql_delete(AccessCode).where(AccessCode.file_id == file_id))
    await db.execute(sql_delete(File).where(File.id == file_id))
    await db.commit()

    # 记录已删除：磁盘删除失败（如 Windows 下文件正被下载占用）只记日志，不影响响应与广播
    try:
        await run_in_threadpool(storage_delete_file, file_record.user_id, file_record.stored_name)
    except OSError:
        logger.exception("删除磁盘文件失败 file_id=%s", file_id)

    await manager.broadcast_to_user(
        user_id=current_user.id,
        message={"type": "file_deleted", "data": {"id": file_id}},
    )

    return None
