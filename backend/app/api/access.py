"""访问码路由：创建 + 撤销（需登录） / 免登录访问（公开，限流）"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, AccessCode, AccessCodeTargetType, Clipboard, File
from ..schemas import (
    AccessCodeCreate,
    AccessCodeResponse,
    AccessCodeListResponse,
    AccessTextResponse,
)
from ..core.deps import get_current_user
from ..core.timeutil import utcnow, to_naive_utc
from ..rate_limit import limiter
from .files import stream_file_response

# 需登录的管理接口，挂载在 /api/access-codes
router = APIRouter()
# 免登录访问接口，挂载在 /api/access（与管理接口分开，避免公开处理函数出现在登录前缀下）
public_router = APIRouter()

_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
ACCESS_CODE_LENGTH = 12  # 62^12 ≈ 3.2e21，配合限流足以抵抗遍历


def generate_access_code() -> str:
    """生成随机访问码（secrets 为密码学安全随机源）"""
    return "".join(secrets.choice(_ALPHABET) for _ in range(ACCESS_CODE_LENGTH))


def is_access_code_valid(access_code: AccessCode) -> bool:
    """访问码有效：未撤销且未过期（expires_at 统一按 naive UTC 存储）"""
    if access_code.is_revoked:
        return False
    if access_code.expires_at is not None and access_code.expires_at <= utcnow():
        return False
    return True


def _build_access_url(request: Request, code: AccessCode) -> str:
    """
    按请求的 scheme + host 动态拼接前端访问页链接（SPA 路由 /access/<code>），不硬编码协议或域名。
    文件码带 ?t=file，访问页据此走 /api/access/<code>/download。
    """
    base = f"{request.url.scheme}://{request.headers.get('host', '')}/access/{code.code}"
    return f"{base}?t=file" if code.target_type == AccessCodeTargetType.FILE else base


def _to_response(request: Request, code: AccessCode) -> AccessCodeResponse:
    return AccessCodeResponse(
        id=code.id,
        code=code.code,
        target_type=code.target_type,
        file_id=code.file_id,
        expires_at=code.expires_at,
        is_revoked=code.is_revoked,
        created_at=code.created_at,
        access_url=_build_access_url(request, code),
    )


async def _resolve_valid_code(
    db: AsyncSession, code: str, expected_type: AccessCodeTargetType
) -> tuple[AccessCode, User]:
    """
    解析公开访问码。

    安全红线：不存在 / 类型不符 / 已撤销 / 已过期 / 属主已禁用，一律返回同样的 404，
    不给遍历者任何「这个码存在」的信号。
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="访问码无效或已失效")

    if not code or len(code) > 32:
        raise not_found

    result = await db.execute(
        select(AccessCode, User)
        .join(User, AccessCode.owner_id == User.id)
        .where(AccessCode.code == code)
    )
    row = result.first()
    if row is None:
        raise not_found

    access_code, owner = row
    if (
        access_code.target_type != expected_type
        or not is_access_code_valid(access_code)
        or not owner.is_active  # 安全红线：属主被禁用后其访问码一并失效
    ):
        raise not_found

    return access_code, owner


# ========== 需登录：访问码管理 ==========


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
    - 文本码：不存快照，实时指向属主当前文本；不允许携带 file_id
    - 文件码：校验 file_id 归属于当前用户
    """
    expires_at = to_naive_utc(data.expires_at)
    if expires_at is not None and expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="过期时间必须晚于当前时间")

    file_id = None
    if data.target_type == AccessCodeTargetType.FILE:
        if not data.file_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件码必须指定 file_id")

        result = await db.execute(
            select(File.id).where(
                File.id == data.file_id,
                File.user_id == current_user.id,  # 安全红线：只能为自己的文件生成码
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在或无权访问")
        file_id = data.file_id

    code = None
    for _ in range(5):
        candidate = generate_access_code()
        result = await db.execute(select(AccessCode.id).where(AccessCode.code == candidate))
        if result.scalar_one_or_none() is None:
            code = candidate
            break
    if code is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="访问码生成失败，请重试")

    access_code = AccessCode(
        code=code,
        owner_id=current_user.id,
        target_type=data.target_type,
        file_id=file_id,
        expires_at=expires_at,
        is_revoked=False,
        created_at=utcnow(),
    )
    db.add(access_code)
    await db.commit()
    await db.refresh(access_code)

    return _to_response(request, access_code)


@router.get("", response_model=AccessCodeListResponse)
async def list_access_codes(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的访问码列表（安全红线：强制按 owner_id 过滤）"""
    result = await db.execute(
        select(AccessCode)
        .where(AccessCode.owner_id == current_user.id)
        .order_by(AccessCode.created_at.desc())
    )
    items = [_to_response(request, code) for code in result.scalars().all()]
    return AccessCodeListResponse(items=items, total=len(items))


@router.delete("/{access_code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_access_code(
    access_code_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """撤销访问码（安全红线：仅归属者可撤销）"""
    result = await db.execute(
        select(AccessCode).where(
            AccessCode.id == access_code_id,
            AccessCode.owner_id == current_user.id,
        )
    )
    access_code = result.scalar_one_or_none()
    if not access_code:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="访问码不存在或无权访问")

    access_code.is_revoked = True
    await db.commit()
    return None


# ========== 免登录：凭访问码访问（公开，必须限流） ==========


@public_router.get("/{code}", response_model=AccessTextResponse)
@limiter.limit("30/minute")
async def access_text(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """通过文本码读取属主当前文本（实时，不存快照）"""
    access_code, owner = await _resolve_valid_code(db, code, AccessCodeTargetType.TEXT)

    result = await db.execute(select(Clipboard).where(Clipboard.user_id == access_code.owner_id))
    clipboard = result.scalar_one_or_none()

    return AccessTextResponse(
        content=clipboard.content if clipboard else "",
        updated_at=clipboard.updated_at if clipboard else utcnow(),
        owner_username=owner.username,
    )


@public_router.get("/{code}/download")
@limiter.limit("30/minute")
async def access_file_download(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """通过文件码下载文件（流式）"""
    access_code, _owner = await _resolve_valid_code(db, code, AccessCodeTargetType.FILE)

    result = await db.execute(
        select(File).where(
            File.id == access_code.file_id,
            File.user_id == access_code.owner_id,  # 文件必须仍属于码的属主
        )
    )
    file_record = result.scalar_one_or_none()
    if file_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="访问码无效或已失效")

    return stream_file_response(file_record)
