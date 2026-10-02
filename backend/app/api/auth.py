"""认证路由：注册 / 登录 / 当前用户信息"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, InviteCode, UserRole, File
from ..schemas import UserCreate, UserLogin, Token, UserWithStats
from ..core.security import (
    hash_password,
    verify_password,
    burn_password_check,
    create_access_token,
)
from ..core.deps import get_current_user
from ..core.app_settings import get_registration_enabled, get_default_quota_bytes
from ..core.timeutil import utcnow
from ..rate_limit import limiter
from .files import upload_reserved_bytes

router = APIRouter()


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")  # 注册限流：每分钟 5 次
async def register(
    request: Request,
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    用户注册：校验注册开关与邀请码，创建用户，返回 JWT。

    安全红线：
    - 注册开关关闭时一律拒绝（即便持有有效邀请码）
    - 邀请码必须有效（未使用、未过期），加行锁防止并发重复使用
    - 密码仅存哈希
    """
    # 1. 注册开关（安全红线：后台关闭注册后必须真正生效）
    if not await get_registration_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="系统已关闭注册",
        )

    # 2. 校验用户名是否已存在
    result = await db.execute(select(User).where(User.username == user_in.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已被注册",
        )

    # 3. 校验邀请码（FOR UPDATE：同一邀请码并发注册时只有一个能成功）
    result = await db.execute(
        select(InviteCode)
        .where(
            InviteCode.code == user_in.invite_code,
            InviteCode.used_by.is_(None),
            # used_at 非空即已用过（使用者被删除后 used_by 会置空，不能据此复用）
            InviteCode.used_at.is_(None),
        )
        .with_for_update()
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请码无效或已被使用",
        )

    if invite.expires_at and invite.expires_at <= utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请码已过期",
        )

    # 4. 创建用户（bcrypt 为 CPU 密集操作，放入线程池避免阻塞事件循环）
    password_hash = await run_in_threadpool(hash_password, user_in.password)
    new_user = User(
        username=user_in.username,
        password_hash=password_hash,
        role=UserRole.USER,  # 安全红线：注册只能得到普通用户
        quota_bytes=await get_default_quota_bytes(db),
        is_active=True,
    )
    db.add(new_user)
    try:
        await db.flush()
    except IntegrityError:
        # 用户名唯一约束：并发注册同名时兜底
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已被注册",
        )

    # 5. 标记邀请码已使用
    invite.used_by = new_user.id
    invite.used_at = utcnow()

    await db.commit()

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
    - 不泄露用户是否存在（错误信息一致，耗时一致）
    """
    result = await db.execute(select(User).where(User.username == credentials.username))
    user = result.scalar_one_or_none()

    if user is None:
        # 用户不存在也跑一次 bcrypt，避免按响应时间枚举用户名
        await run_in_threadpool(burn_password_check, credentials.password)
        password_ok = False
    else:
        password_ok = await run_in_threadpool(
            verify_password, credentials.password, user.password_hash
        )

    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )

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
        reserved_bytes=await upload_reserved_bytes(db, current_user.id),
    )
