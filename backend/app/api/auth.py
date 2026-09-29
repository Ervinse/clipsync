"""认证路由：注册 / 登录 / 当前用户信息"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, InviteCode, UserRole, File
from ..schemas import UserCreate, UserLogin, Token, UserWithStats
from ..core.security import hash_password, verify_password, create_access_token
from ..core.deps import get_current_user
from ..rate_limit import limiter
from ..config import settings

router = APIRouter()


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")  # 注册限流：每分钟 5 次
async def register(
    request: Request,
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    用户注册：校验邀请码，创建用户，返回 JWT。

    安全红线：
    - 邀请码必须有效（未使用、未过期）
    - 用户名唯一性校验
    - 密码仅存哈希
    """
    # 1. 校验用户名是否已存在
    result = await db.execute(select(User).where(User.username == user_in.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已被注册",
        )

    # 2. 校验邀请码
    result = await db.execute(
        select(InviteCode).where(
            InviteCode.code == user_in.invite_code,
            InviteCode.used_by.is_(None),  # 未使用
        )
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请码无效或已被使用",
        )

    # 检查过期
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请码已过期",
        )

    # 3. 创建用户
    new_user = User(
        username=user_in.username,
        password_hash=hash_password(user_in.password),
        role=UserRole.USER,
        quota_bytes=settings.DEFAULT_QUOTA_BYTES,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()  # 获取 new_user.id

    # 4. 标记邀请码已使用
    invite.used_by = new_user.id
    invite.used_at = datetime.utcnow()

    await db.commit()
    await db.refresh(new_user)

    # 5. 生成 JWT
    access_token = create_access_token(data={"sub": str(new_user.id)})

    return Token(access_token=access_token)


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")  # 登录限流：每分钟 10 次
async def login(
    request: Request,
    credentials: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    """
    用户登录：校验用户名密码，返回 JWT。

    安全红线：
    - 限流防爆破
    - 密码校验失败不泄露用户是否存在
    """
    # 查询用户
    result = await db.execute(select(User).where(User.username == credentials.username))
    user = result.scalar_one_or_none()

    # 统一错误消息，不泄露用户名是否存在
    if not user or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )

    # 生成 JWT
    access_token = create_access_token(data={"sub": str(user.id)})

    return Token(access_token=access_token)


@router.get("/me", response_model=UserWithStats)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户信息 + 存储统计。

    安全红线：必须通过 get_current_user 依赖校验 JWT。
    """
    # 计算已用空间（该用户所有文件的大小总和）
    result = await db.execute(
        select(func.coalesce(func.sum(File.size), 0)).where(File.user_id == current_user.id)
    )
    used_bytes = result.scalar()

    return UserWithStats(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        quota_bytes=current_user.quota_bytes,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        used_bytes=used_bytes,
    )
