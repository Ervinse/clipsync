"""管理后台路由：统计 + 用户管理 + 邀请码 + 系统设置"""
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, delete as sql_delete, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import (
    User,
    UserRole,
    File,
    AccessCode,
    InviteCode,
    Setting,
    Clipboard,
    ClipboardHistory,
    UploadSession,
)
from ..schemas import (
    SystemStats,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserDetail,
    UpdateUserQuota,
    UpdateUserStatus,
    InviteCodeCreate,
    InviteCodeResponse,
    InviteCodeListResponse,
    SystemSettingsResponse,
    UpdateSystemSettings,
    AdminFileListItem,
    AdminFileListResponse,
)
from ..core.deps import get_current_user, require_role
from ..core.storage import delete_user_storage, cleanup_upload_temp
from ..core.ws_manager import manager
from ..core.timeutil import utcnow, to_naive_utc

router = APIRouter()


# ========== 统计数据 ==========


@router.get("/stats", response_model=SystemStats)
async def get_system_stats(
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    获取系统统计数据

    权限：admin + superadmin
    """
    # 1. 用户统计
    result = await db.execute(select(func.count(User.id)))
    total_users = result.scalar()

    result = await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )
    active_users = result.scalar()

    # 2. 文件统计
    result = await db.execute(select(func.count(File.id)))
    total_files = result.scalar()

    result = await db.execute(select(func.coalesce(func.sum(File.size), 0)))
    total_storage_bytes = result.scalar()

    # 3. 访问码统计
    result = await db.execute(select(func.count(AccessCode.id)))
    total_access_codes = result.scalar()

    result = await db.execute(
        select(func.count(AccessCode.id)).where(AccessCode.is_revoked == False)
    )
    active_access_codes = result.scalar()

    return SystemStats(
        total_users=total_users,
        active_users=active_users,
        total_files=total_files,
        total_storage_bytes=total_storage_bytes,
        total_access_codes=total_access_codes,
        active_access_codes=active_access_codes,
    )


# PLACEHOLDER_1: 用户管理接口继续


# ========== 用户管理 ==========


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    获取用户列表（分页）

    权限：admin + superadmin
    安全红线：仅返回元数据，不返回内容
    """
    # 1. 查询用户
    result = await db.execute(
        select(User)
        .order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    users = result.scalars().all()

    # 2. 查询总数
    result = await db.execute(select(func.count(User.id)))
    total = result.scalar()

    # 3. 构建响应（查询每个用户的已用空间和文件数）
    items = []
    for user in users:
        # 已用空间
        result = await db.execute(
            select(func.coalesce(func.sum(File.size), 0)).where(File.user_id == user.id)
        )
        used_bytes = result.scalar()

        # 文件数
        result = await db.execute(
            select(func.count(File.id)).where(File.user_id == user.id)
        )
        file_count = result.scalar()

        items.append(AdminUserListItem(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            quota_bytes=user.quota_bytes,
            used_bytes=used_bytes,
            file_count=file_count,
            created_at=user.created_at,
        ))

    return AdminUserListResponse(items=items, total=total)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def get_user_detail(
    user_id: int,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    获取用户详情

    权限：admin + superadmin
    安全红线：仅返回元数据，不返回文本内容
    """
    # 1. 查询用户
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 2. 已用空间
    result = await db.execute(
        select(func.coalesce(func.sum(File.size), 0)).where(File.user_id == user.id)
    )
    used_bytes = result.scalar()

    # 3. 文件数
    result = await db.execute(
        select(func.count(File.id)).where(File.user_id == user.id)
    )
    file_count = result.scalar()

    # 4. 剪贴板更新时间（不返回内容）
    result = await db.execute(
        select(Clipboard.updated_at).where(Clipboard.user_id == user.id)
    )
    clipboard_updated_at = result.scalar_one_or_none()

    return AdminUserDetail(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        quota_bytes=user.quota_bytes,
        used_bytes=used_bytes,
        file_count=file_count,
        clipboard_updated_at=clipboard_updated_at,
        created_at=user.created_at,
    )


@router.patch("/users/{user_id}/quota", response_model=AdminUserDetail)
async def update_user_quota(
    user_id: int,
    data: UpdateUserQuota,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    修改用户配额

    权限：仅 superadmin
    """
    # 1. 查询用户
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 2. 更新配额
    user.quota_bytes = data.quota_bytes
    await db.commit()
    await db.refresh(user)

    # 3. 返回更新后的详情（复用 get_user_detail 逻辑）
    result = await db.execute(
        select(func.coalesce(func.sum(File.size), 0)).where(File.user_id == user.id)
    )
    used_bytes = result.scalar()

    result = await db.execute(
        select(func.count(File.id)).where(File.user_id == user.id)
    )
    file_count = result.scalar()

    result = await db.execute(
        select(Clipboard.updated_at).where(Clipboard.user_id == user.id)
    )
    clipboard_updated_at = result.scalar_one_or_none()

    return AdminUserDetail(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        quota_bytes=user.quota_bytes,
        used_bytes=used_bytes,
        file_count=file_count,
        clipboard_updated_at=clipboard_updated_at,
        created_at=user.created_at,
    )


@router.patch("/users/{user_id}/status", response_model=AdminUserDetail)
async def update_user_status(
    user_id: int,
    data: UpdateUserStatus,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    修改用户状态（启用/禁用）

    权限：仅 superadmin
    """
    # 1. 查询用户
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 2. 禁止操作自己
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能修改自己的状态",
        )

    # 3. 更新状态
    user.is_active = data.is_active
    await db.commit()
    await db.refresh(user)

    # 安全红线：禁用后立即断开其实时连接（HTTP 接口由 get_current_user 每次回库拦截）
    if not user.is_active:
        await manager.disconnect_user(user.id)

    # 4. 返回详情
    result = await db.execute(
        select(func.coalesce(func.sum(File.size), 0)).where(File.user_id == user.id)
    )
    used_bytes = result.scalar()

    result = await db.execute(
        select(func.count(File.id)).where(File.user_id == user.id)
    )
    file_count = result.scalar()

    result = await db.execute(
        select(Clipboard.updated_at).where(Clipboard.user_id == user.id)
    )
    clipboard_updated_at = result.scalar_one_or_none()

    return AdminUserDetail(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        quota_bytes=user.quota_bytes,
        used_bytes=used_bytes,
        file_count=file_count,
        clipboard_updated_at=clipboard_updated_at,
        created_at=user.created_at,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    删除用户（级联删除所有关联数据）

    权限：仅 superadmin
    安全红线：
    - 禁止删除自己
    - 级联删除：文件（磁盘+记录）、剪贴板、访问码等
    """
    # 1. 查询用户
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 2. 禁止删除自己
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能删除自己",
        )

    # 3. 进行中的上传会话（用于清理临时目录）
    result = await db.execute(select(UploadSession.upload_id).where(UploadSession.user_id == user_id))
    upload_ids = [row[0] for row in result.all()]

    # 4. 显式按依赖顺序删除关联数据（迁移中外键没有 ON DELETE CASCADE，不能依赖数据库级联）
    await db.execute(sql_delete(AccessCode).where(AccessCode.owner_id == user_id))
    await db.execute(sql_delete(UploadSession).where(UploadSession.user_id == user_id))
    await db.execute(sql_delete(File).where(File.user_id == user_id))
    await db.execute(sql_delete(ClipboardHistory).where(ClipboardHistory.user_id == user_id))
    await db.execute(sql_delete(Clipboard).where(Clipboard.user_id == user_id))
    # 邀请码：该用户用过的保留记录但解除关联；该用户创建的未使用码作废，已使用的转记到操作者名下
    await db.execute(
        sql_update(InviteCode).where(InviteCode.used_by == user_id).values(used_by=None)
    )
    await db.execute(
        sql_delete(InviteCode).where(InviteCode.created_by == user_id, InviteCode.used_by.is_(None), InviteCode.used_at.is_(None))
    )
    await db.execute(
        sql_update(InviteCode).where(InviteCode.created_by == user_id).values(created_by=current_user.id)
    )
    await db.execute(sql_delete(User).where(User.id == user_id))
    await db.commit()

    # 5. 删除磁盘文件与临时目录
    delete_user_storage(user_id)
    for upload_id in upload_ids:
        cleanup_upload_temp(upload_id)

    # 6. 断开该用户所有实时连接
    await manager.disconnect_user(user_id)

    return None


# PLACEHOLDER_2: 邀请码管理接口继续


# ========== 邀请码管理 ==========


def generate_invite_code() -> str:
    """生成 16 位邀请码（大小写字母 + 数字）"""
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(secrets.choice(alphabet) for _ in range(16))


@router.post("/invite-codes", response_model=InviteCodeResponse)
async def create_invite_code(
    data: InviteCodeCreate,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    生成邀请码

    权限：admin + superadmin
    """
    # 1. 生成唯一邀请码（冲突重试）
    max_retries = 5
    code = None

    for _ in range(max_retries):
        candidate = generate_invite_code()
        result = await db.execute(
            select(InviteCode).where(InviteCode.code == candidate)
        )
        if result.scalar_one_or_none() is None:
            code = candidate
            break

    if code is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="邀请码生成失败，请重试",
        )

    # 2. 创建邀请码（过期时间统一转 naive UTC，与 register 中的 utcnow() 比较口径一致）
    expires_at = to_naive_utc(data.expires_at)
    if expires_at is not None and expires_at <= utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="过期时间必须晚于当前时间",
        )
    invite_code = InviteCode(
        code=code,
        created_by=current_user.id,
        expires_at=expires_at,
        created_at=utcnow(),
    )
    db.add(invite_code)
    await db.commit()
    await db.refresh(invite_code)

    # 3. 查询使用者用户名（如果已使用）
    used_by_username = None
    if invite_code.used_by:
        result = await db.execute(
            select(User.username).where(User.id == invite_code.used_by)
        )
        used_by_username = result.scalar_one_or_none()

    return InviteCodeResponse(
        id=invite_code.id,
        code=invite_code.code,
        created_by=invite_code.created_by,
        created_by_username=current_user.username,
        used_by=invite_code.used_by,
        used_by_username=used_by_username,
        expires_at=invite_code.expires_at,
        used_at=invite_code.used_at,
        created_at=invite_code.created_at,
    )


@router.get("/invite-codes", response_model=InviteCodeListResponse)
async def list_invite_codes(
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    获取邀请码列表

    权限：admin + superadmin
    """
    # 查询所有邀请码（按创建时间倒序），关联创建者和使用者
    result = await db.execute(
        select(
            InviteCode,
            User.username.label("creator_username")
        )
        .join(User, InviteCode.created_by == User.id)
        .order_by(InviteCode.created_at.desc())
    )
    rows = result.all()

    items = []
    for invite_code, creator_username in rows:
        # 查询使用者用户名
        used_by_username = None
        if invite_code.used_by:
            result_used = await db.execute(
                select(User.username).where(User.id == invite_code.used_by)
            )
            used_by_username = result_used.scalar_one_or_none()

        items.append(InviteCodeResponse(
            id=invite_code.id,
            code=invite_code.code,
            created_by=invite_code.created_by,
            created_by_username=creator_username,
            used_by=invite_code.used_by,
            used_by_username=used_by_username,
            expires_at=invite_code.expires_at,
            used_at=invite_code.used_at,
            created_at=invite_code.created_at,
        ))

    return InviteCodeListResponse(items=items, total=len(items))


@router.delete("/invite-codes/{invite_code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invite_code(
    invite_code_id: int,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    删除邀请码

    权限：admin + superadmin
    """
    # 查询邀请码
    result = await db.execute(
        select(InviteCode).where(InviteCode.id == invite_code_id)
    )
    invite_code = result.scalar_one_or_none()

    if not invite_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="邀请码不存在",
        )

    # 删除邀请码
    await db.execute(sql_delete(InviteCode).where(InviteCode.id == invite_code_id))
    await db.commit()

    return None


# PLACEHOLDER_3: 系统设置接口继续


# ========== 系统设置 ==========


@router.get("/settings", response_model=SystemSettingsResponse)
async def get_system_settings(
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    获取系统设置

    权限：admin + superadmin
    """
    # 查询系统设置（key-value 存储）
    from ..config import settings as app_settings
    import json

    # 读取默认配额
    result = await db.execute(
        select(Setting).where(Setting.key == "default_quota_bytes")
    )
    quota_setting = result.scalar_one_or_none()
    default_quota_bytes = int(quota_setting.value) if quota_setting else app_settings.DEFAULT_QUOTA_BYTES

    # 读取注册开关
    result = await db.execute(
        select(Setting).where(Setting.key == "registration_enabled")
    )
    reg_setting = result.scalar_one_or_none()
    registration_enabled = (reg_setting.value.lower() == "true") if reg_setting else True

    return SystemSettingsResponse(
        default_quota_bytes=default_quota_bytes,
        registration_enabled=registration_enabled,
    )


@router.patch("/settings", response_model=SystemSettingsResponse)
async def update_system_settings(
    data: UpdateSystemSettings,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    更新系统设置

    权限：仅 superadmin
    """
    # 更新默认配额
    if data.default_quota_bytes is not None:
        result = await db.execute(
            select(Setting).where(Setting.key == "default_quota_bytes")
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = str(data.default_quota_bytes)
        else:
            setting = Setting(
                key="default_quota_bytes",
                value=str(data.default_quota_bytes),
            )
            db.add(setting)

    # 更新注册开关
    if data.registration_enabled is not None:
        result = await db.execute(
            select(Setting).where(Setting.key == "registration_enabled")
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.value = "true" if data.registration_enabled else "false"
        else:
            setting = Setting(
                key="registration_enabled",
                value="true" if data.registration_enabled else "false",
            )
            db.add(setting)

    await db.commit()

    # 读取最新值
    result = await db.execute(
        select(Setting).where(Setting.key == "default_quota_bytes")
    )
    quota_setting = result.scalar_one_or_none()

    result = await db.execute(
        select(Setting).where(Setting.key == "registration_enabled")
    )
    reg_setting = result.scalar_one_or_none()

    from ..config import settings as app_settings
    default_quota_bytes = int(quota_setting.value) if quota_setting else app_settings.DEFAULT_QUOTA_BYTES
    registration_enabled = (reg_setting.value.lower() == "true") if reg_setting else True

    return SystemSettingsResponse(
        default_quota_bytes=default_quota_bytes,
        registration_enabled=registration_enabled,
    )


# ========== 文件管理（仅元数据） ==========


@router.get("/files", response_model=AdminFileListResponse)
async def list_all_files(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    获取所有用户的文件列表（仅元数据）

    权限：admin + superadmin
    安全红线：仅返回元数据，不提供下载入口
    """
    # 查询文件 + 用户名（join）
    result = await db.execute(
        select(File, User.username)
        .join(User, File.user_id == User.id)
        .order_by(File.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = result.all()

    # 查询总数
    result = await db.execute(select(func.count(File.id)))
    total = result.scalar()

    items = []
    for file, username in rows:
        items.append(AdminFileListItem(
            id=file.id,
            user_id=file.user_id,
            username=username,
            original_name=file.original_name,
            size=file.size,
            mime_type=file.mime_type,
            created_at=file.created_at,
        ))

    return AdminFileListResponse(items=items, total=total)



