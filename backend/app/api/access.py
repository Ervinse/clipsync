"""访问码路由：创建 + 撤销 + 免登录访问"""
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, AccessCode, AccessCodeTargetType, Clipboard, File
from ..schemas import (
    AccessCodeCreate,
    AccessCodeResponse,
    AccessCodeListResponse,
    AccessTextResponse,
    AccessFileResponse,
)
from ..core.deps import get_current_user
from ..core.storage import get_file_path
from ..rate_limit import limiter

router = APIRouter()


def generate_access_code() -> str:
    """生成 8 位随机访问码（大小写字母 + 数字）"""
    # 62^8 = 2.18e14 种组合，足够安全
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def is_access_code_valid(access_code: AccessCode) -> bool:
    """
    检查访问码是否有效

    条件：
    1. 未被撤销
    2. 未过期（expires_at 为 None 或在当前时间之后）
    """
    if access_code.is_revoked:
        return False

    if access_code.expires_at:
        # 使用 UTC 时区比较
        now = datetime.now(timezone.utc)
        # 确保 expires_at 有时区信息
        expires_at = access_code.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if now >= expires_at:
            return False

    return True


@router.post("", response_model=AccessCodeResponse)
async def create_access_code(
    data: AccessCodeCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    创建访问码

    安全红线：
    - 文本码：无需校验，指向属主当前文本（实时）
    - 文件码：校验 file_id 归属于当前用户
    - 访问 URL 按请求协议 + 域名动态拼接
    """
    # 1. 文件码校验：file_id 归属
    if data.target_type == AccessCodeTargetType.FILE:
        if not data.file_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="文件码必须指定 file_id",
            )

        # 查询文件，校验归属（安全红线）
        result = await db.execute(
            select(File).where(
                File.id == data.file_id,
                File.user_id == current_user.id,
            )
        )
        file_record = result.scalar_one_or_none()

        if not file_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件不存在或无权访问",
            )

    # 2. 生成唯一访问码（冲突重试）
    max_retries = 5
    code = None

    for _ in range(max_retries):
        candidate = generate_access_code()
        # 检查是否已存在
        result = await db.execute(
            select(AccessCode).where(AccessCode.code == candidate)
        )
        if result.scalar_one_or_none() is None:
            code = candidate
            break

    if code is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="访问码生成失败，请重试",
        )

    # 3. 创建访问码记录
    access_code = AccessCode(
        code=code,
        owner_id=current_user.id,
        target_type=data.target_type,
        file_id=data.file_id,
        expires_at=data.expires_at,
    )
    db.add(access_code)
    await db.commit()
    await db.refresh(access_code)

    # 4. 动态拼接访问 URL（协议 + 域名 + 路径）
    # 获取请求的协议和主机
    scheme = request.url.scheme  # http 或 https
    host = request.headers.get("host")  # 包含端口

    # 构建完整访问 URL
    if data.target_type == AccessCodeTargetType.TEXT:
        access_url = f"{scheme}://{host}/api/access/{code}"
    else:  # FILE
        access_url = f"{scheme}://{host}/api/access/{code}/download"

    return AccessCodeResponse(
        id=access_code.id,
        code=access_code.code,
        target_type=access_code.target_type,
        file_id=access_code.file_id,
        expires_at=access_code.expires_at,
        is_revoked=access_code.is_revoked,
        created_at=access_code.created_at,
        access_url=access_url,
    )


@router.get("", response_model=AccessCodeListResponse)
async def list_access_codes(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的访问码列表

    安全红线：查询强制按 user_id 过滤
    """
    # 查询访问码（按创建时间倒序）
    result = await db.execute(
        select(AccessCode)
        .where(AccessCode.owner_id == current_user.id)
        .order_by(AccessCode.created_at.desc())
    )
    codes = result.scalars().all()

    # 动态拼接访问 URL
    scheme = request.url.scheme
    host = request.headers.get("host")

    items = []
    for code in codes:
        if code.target_type == AccessCodeTargetType.TEXT:
            access_url = f"{scheme}://{host}/api/access/{code.code}"
        else:  # FILE
            access_url = f"{scheme}://{host}/api/access/{code.code}/download"

        items.append(AccessCodeResponse(
            id=code.id,
            code=code.code,
            target_type=code.target_type,
            file_id=code.file_id,
            expires_at=code.expires_at,
            is_revoked=code.is_revoked,
            created_at=code.created_at,
            access_url=access_url,
        ))

    return AccessCodeListResponse(
        items=items,
        total=len(items),
    )


@router.delete("/{access_code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_access_code(
    access_code_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    撤销访问码

    安全红线：仅允许归属者撤销
    """
    # 查询访问码，校验归属
    result = await db.execute(
        select(AccessCode).where(
            AccessCode.id == access_code_id,
            AccessCode.owner_id == current_user.id,  # 安全红线
        )
    )
    access_code = result.scalar_one_or_none()

    if not access_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="访问码不存在或无权访问",
        )

    # 标记为已撤销
    access_code.is_revoked = True
    await db.commit()

    return None


# ========== 免登录访问接口（公开，需要限流） ==========


@router.get("/{code}", response_model=AccessTextResponse)
@limiter.limit("30/minute")  # 限流：防暴力猜测
async def access_text(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    通过访问码获取文本（免登录）

    安全机制：
    - 限流：30 次/分钟（防暴力猜测 62^8 组合空间）
    - 校验有效性：未撤销、未过期
    - 文本码实时指向属主当前文本，不存快照
    """
    # 1. 查询访问码
    result = await db.execute(
        select(AccessCode).where(AccessCode.code == code)
    )
    access_code = result.scalar_one_or_none()

    if not access_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="访问码不存在",
        )

    # 2. 校验类型
    if access_code.target_type != AccessCodeTargetType.TEXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="访问码类型错误（应为文本码）",
        )

    # 3. 校验有效性
    if not is_access_code_valid(access_code):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="访问码已失效",
        )

    # 4. 查询属主当前文本（实时，不存快照）
    result = await db.execute(
        select(Clipboard).where(Clipboard.user_id == access_code.owner_id)
    )
    clipboard = result.scalar_one_or_none()

    if not clipboard:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="属主暂无内容",
        )

    # 5. 查询属主用户名
    result = await db.execute(
        select(User).where(User.id == access_code.owner_id)
    )
    owner = result.scalar_one()

    return AccessTextResponse(
        content=clipboard.content,
        updated_at=clipboard.updated_at,
        owner_username=owner.username,
    )


@router.get("/{code}/download")
@limiter.limit("30/minute")  # 限流：防暴力猜测
async def access_file_download(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    通过访问码下载文件（免登录）

    安全机制：
    - 限流：30 次/分钟（防暴力猜测）
    - 校验有效性：未撤销、未过期
    - 流式响应，避免内存占用
    """
    # 1. 查询访问码
    result = await db.execute(
        select(AccessCode).where(AccessCode.code == code)
    )
    access_code = result.scalar_one_or_none()

    if not access_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="访问码不存在",
        )

    # 2. 校验类型
    if access_code.target_type != AccessCodeTargetType.FILE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="访问码类型错误（应为文件码）",
        )

    # 3. 校验有效性
    if not is_access_code_valid(access_code):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="访问码已失效",
        )

    # 4. 查询文件记录
    result = await db.execute(
        select(File).where(File.id == access_code.file_id)
    )
    file_record = result.scalar_one_or_none()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    # 5. 获取文件路径（使用 UUID stored_name，防穿越）
    file_path = get_file_path(file_record.user_id, file_record.stored_name)

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件已丢失",
        )

    # 6. 流式响应
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
