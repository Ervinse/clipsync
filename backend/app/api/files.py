"""文件路由：分片上传 + 下载 + 删除"""
import uuid
import mimetypes
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File as FastAPIFile, Form
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
    get_file_path,
    generate_stored_name,
    cleanup_upload_temp,
    delete_file as storage_delete_file,
)
from ..core.ws_manager import manager
from ..config import settings

router = APIRouter()


@router.post("/upload/init", response_model=UploadInitResponse)
async def init_upload(
    data: UploadInitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    初始化分片上传会话

    安全红线：
    - 先校验配额：已用 + 本次文件大小 <= 配额
    - 单文件大小不超过 MAX_FILE_BYTES
    """
    # 1. 校验单文件大小上限
    if data.total_size > settings.MAX_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小超过限制（最大 {settings.MAX_FILE_BYTES // (1024*1024)} MB）",
        )

    # 2. 计算用户已用空间
    result = await db.execute(
        select(func.coalesce(func.sum(File.size), 0)).where(File.user_id == current_user.id)
    )
    used_bytes = result.scalar()

    # 3. 校验配额
    if used_bytes + data.total_size > current_user.quota_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"存储配额不足（已用 {used_bytes // (1024*1024)} MB / "
                   f"配额 {current_user.quota_bytes // (1024*1024)} MB）",
        )

    # 4. 计算分片数
    total_chunks = (data.total_size + data.chunk_size - 1) // data.chunk_size

    # 5. 创建上传会话
    upload_id = str(uuid.uuid4())
    session = UploadSession(
        upload_id=upload_id,
        user_id=current_user.id,
        original_name=data.original_name,
        total_size=data.total_size,
        total_chunks=total_chunks,
        received_chunks=0,
        chunk_size=data.chunk_size,
    )
    db.add(session)
    await db.commit()

    # 6. 创建临时目录
    ensure_upload_temp_dir(upload_id)

    return UploadInitResponse(
        upload_id=upload_id,
        total_chunks=total_chunks,
    )


@router.post("/upload/chunk", status_code=status.HTTP_200_OK)
async def upload_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(..., ge=0),
    chunk_data: UploadFile = FastAPIFile(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    上传单个分片

    安全红线：
    - 校验 upload_id 归属于当前用户
    - 校验 chunk_index 在有效范围内
    - 支持断点续传（重复上传同一分片会覆盖）
    """
    # 1. 查询上传会话，校验归属
    result = await db.execute(
        select(UploadSession).where(
            UploadSession.upload_id == upload_id,
            UploadSession.user_id == current_user.id,  # 安全红线：归属校验
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传会话不存在或无权访问",
        )

    # 2. 校验分片索引
    if chunk_index >= session.total_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"分片索引超出范围（最大 {session.total_chunks - 1}）",
        )

    # 3. 保存分片到临时目录
    temp_dir = ensure_upload_temp_dir(upload_id)
    chunk_path = temp_dir / f"{chunk_index}"

    # 流式写入分片（避免内存占用）
    with open(chunk_path, "wb") as f:
        while chunk := await chunk_data.read(8192):  # 8KB 块读取
            f.write(chunk)

    # 4. 更新已接收分片数（如果该分片是新上传的）
    # 简化逻辑：检查临时目录中的分片数
    received_count = len(list(temp_dir.glob("*")))
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
    - 校验所有分片已到齐
    - 流式合并，避免内存占用
    - 合并后再次校验配额（防止并发上传超配）
    """
    # 1. 查询上传会话，校验归属
    result = await db.execute(
        select(UploadSession).where(
            UploadSession.upload_id == data.upload_id,
            UploadSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="上传会话不存在或无权访问",
        )

    # 2. 校验分片完整性
    temp_dir = ensure_upload_temp_dir(data.upload_id)
    received_chunks = sorted([int(f.name) for f in temp_dir.glob("*") if f.is_file()])

    if len(received_chunks) != session.total_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"分片不完整（已收到 {len(received_chunks)} / {session.total_chunks}）",
        )

    expected_chunks = list(range(session.total_chunks))
    if received_chunks != expected_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="分片索引不连续",
        )

    # 3. 生成存储文件名（UUID）
    stored_name = generate_stored_name()
    user_dir = ensure_user_storage_dir(current_user.id)
    final_path = user_dir / stored_name

    # 4. 流式合并分片（追加模式）
    try:
        with open(final_path, "wb") as outfile:
            for chunk_index in range(session.total_chunks):
                chunk_path = temp_dir / str(chunk_index)
                with open(chunk_path, "rb") as infile:
                    while chunk := infile.read(8192):
                        outfile.write(chunk)
    except Exception as e:
        # 合并失败，清理临时文件和目标文件
        if final_path.exists():
            final_path.unlink()
        cleanup_upload_temp(data.upload_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件合并失败: {str(e)}",
        )

    # 5. 获取实际文件大小（可能与声明不完全一致）
    actual_size = final_path.stat().st_size

    # 6. 再次校验配额（防止并发上传超配）
    result = await db.execute(
        select(func.coalesce(func.sum(File.size), 0)).where(File.user_id == current_user.id)
    )
    used_bytes = result.scalar()

    if used_bytes + actual_size > current_user.quota_bytes:
        # 超配，删除刚合并的文件
        final_path.unlink()
        cleanup_upload_temp(data.upload_id)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="存储配额不足（并发上传导致超配）",
        )

    # 7. 推断 MIME 类型
    mime_type, _ = mimetypes.guess_type(session.original_name)
    if not mime_type:
        mime_type = "application/octet-stream"

    # 8. 写入文件记录
    file_record = File(
        user_id=current_user.id,
        original_name=session.original_name,
        stored_name=stored_name,
        size=actual_size,
        mime_type=mime_type,
    )
    db.add(file_record)

    # 9. 删除上传会话
    await db.execute(
        sql_delete(UploadSession).where(UploadSession.upload_id == data.upload_id)
    )

    await db.commit()
    await db.refresh(file_record)

    # 10. 清理临时目录
    cleanup_upload_temp(data.upload_id)

    # 11. 实时广播
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
    # 1. 查询文件列表
    result = await db.execute(
        select(File)
        .where(File.user_id == current_user.id)
        .order_by(File.created_at.desc())
    )
    files = result.scalars().all()

    # 2. 计算已用空间
    used_bytes = sum(f.size for f in files)

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
        used_bytes=used_bytes,
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
    - 仅允许文件归属者与 superadmin 下载
    - 使用 stored_name 拼接路径，防穿越
    """
    # 1. 查询文件记录
    result = await db.execute(select(File).where(File.id == file_id))
    file_record = result.scalar_one_or_none()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    # 2. 权限校验（安全红线）
    is_owner = file_record.user_id == current_user.id
    is_superadmin = current_user.role == UserRole.SUPERADMIN

    if not (is_owner or is_superadmin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该文件",
        )

    # 3. 获取文件路径（使用 UUID stored_name，防穿越）
    file_path = get_file_path(file_record.user_id, file_record.stored_name)

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件已丢失",
        )

    # 4. 流式响应
    def iterfile():
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(
        iterfile(),
        media_type=file_record.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{file_record.original_name}"',
            "Content-Length": str(file_record.size),
        },
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_endpoint(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    删除文件：记录 + 磁盘 + 级联撤销访问码 + 广播

    安全红线：
    - 校验归属（仅归属者可删除，superadmin 不可越权删除）
    - 级联撤销该文件的访问码
    """
    # 1. 查询文件记录，校验归属
    result = await db.execute(
        select(File).where(
            File.id == file_id,
            File.user_id == current_user.id,  # 安全红线：仅归属者
        )
    )
    file_record = result.scalar_one_or_none()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在或无权访问",
        )

    # 2. 级联撤销访问码（file_id 外键 ON DELETE CASCADE 会自动处理，这里显式撤销）
    await db.execute(
        sql_delete(AccessCode).where(AccessCode.file_id == file_id)
    )

    # 3. 删除数据库记录
    await db.execute(sql_delete(File).where(File.id == file_id))
    await db.commit()

    # 4. 删除磁盘文件
    storage_delete_file(file_record.user_id, file_record.stored_name)

    # 5. 实时广播
    await manager.broadcast_to_user(
        user_id=current_user.id,
        message={
            "type": "file_deleted",
            "data": {"id": file_id},
        },
    )

    return None
