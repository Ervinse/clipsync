"""文件路由：分片上传 + 下载 + 删除"""
import logging
import mimetypes
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File as FastAPIFile, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, delete as sql_delete
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
    delete_file as storage_delete_file,
)
from ..core.http_utils import content_disposition
from ..core.timeutil import utcnow
from ..core.ws_manager import manager
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

_READ_BLOCK = 64 * 1024


async def _reserved_bytes(db: AsyncSession, user_id: int, exclude_upload_id: str | None = None) -> int:
    """
    已占用配额 = 已落盘文件 + 进行中的上传会话声明大小。
    安全红线：把未完成会话也计入，防止并发开多个会话各自通过 init 校验后超配。
    """
    result = await db.execute(
        select(func.coalesce(func.sum(File.size), 0)).where(File.user_id == user_id)
    )
    used = int(result.scalar())

    stmt = select(func.coalesce(func.sum(UploadSession.total_size), 0)).where(
        UploadSession.user_id == user_id
    )
    if exclude_upload_id:
        stmt = stmt.where(UploadSession.upload_id != exclude_upload_id)
    result = await db.execute(stmt)
    return used + int(result.scalar())


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


def _iter_file(path: Path):
    """流式读取文件（StreamingResponse 会在线程池中迭代同步生成器）"""
    with open(path, "rb") as f:
        while block := f.read(_READ_BLOCK):
            yield block


def stream_file_response(file_record: File) -> StreamingResponse:
    """统一的流式下载响应（登录下载与访问码下载共用）"""
    file_path = get_file_path(file_record.user_id, file_record.stored_name)
    if not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件已丢失")

    return StreamingResponse(
        _iter_file(file_path),
        media_type=file_record.mime_type,
        headers={
            # 安全红线：文件名来自用户，按 RFC 6266 编码，杜绝头注入
            "Content-Disposition": content_disposition(file_record.original_name),
            "Content-Length": str(file_path.stat().st_size),
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

    chunk_size = min(data.chunk_size, settings.CHUNK_SIZE)

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
            cleanup_upload_temp(expired_id)

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

    ensure_upload_temp_dir(upload_id)

    return UploadInitResponse(upload_id=upload_id, total_chunks=total_chunks, chunk_size=chunk_size)


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

    temp_dir = ensure_upload_temp_dir(upload_id)
    chunk_path = temp_dir / str(chunk_index)
    partial_path = temp_dir / f"{chunk_index}.part"

    written = 0
    oversized = False
    with open(partial_path, "wb") as f:
        while block := await chunk_data.read(_READ_BLOCK):
            written += len(block)
            if written > session.chunk_size:
                oversized = True
                break
            f.write(block)

    if oversized:
        partial_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="分片大小超过限制",
        )

    # 写完再原子替换，断点续传重传同一分片时不会留下半截文件
    partial_path.replace(chunk_path)

    received_count = sum(1 for p in temp_dir.iterdir() if p.is_file() and p.name.isdigit())
    session.received_chunks = received_count
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
    """
    result = await db.execute(
        select(UploadSession).where(
            UploadSession.upload_id == data.upload_id,
            UploadSession.user_id == current_user.id,  # 安全红线：归属校验
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上传会话不存在或无权访问")

    temp_dir = get_upload_temp_dir(data.upload_id)
    received = sorted(
        int(p.name) for p in temp_dir.iterdir() if p.is_file() and p.name.isdigit()
    ) if temp_dir.exists() else []
    if received != list(range(session.total_chunks)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"分片不完整（已收到 {len(received)} / {session.total_chunks}）",
        )

    stored_name = generate_stored_name()
    final_path = ensure_user_storage_dir(current_user.id) / stored_name

    try:
        actual_size = await run_in_threadpool(_merge_chunks, temp_dir, session.total_chunks, final_path)
    except OSError:
        logger.exception("合并分片失败 upload_id=%s", data.upload_id)
        final_path.unlink(missing_ok=True)
        cleanup_upload_temp(data.upload_id)
        await db.execute(sql_delete(UploadSession).where(UploadSession.upload_id == data.upload_id))
        await db.commit()
        # 安全红线：不把底层异常细节（路径等）回传客户端
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="文件合并失败")

    async def _abort(detail: str):
        final_path.unlink(missing_ok=True)
        cleanup_upload_temp(data.upload_id)
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
    await db.commit()
    await db.refresh(file_record)

    cleanup_upload_temp(data.upload_id)

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

    return stream_file_response(file_record)


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

    storage_delete_file(file_record.user_id, file_record.stored_name)

    await manager.broadcast_to_user(
        user_id=current_user.id,
        message={"type": "file_deleted", "data": {"id": file_id}},
    )

    return None
