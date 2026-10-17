"""管理后台路由：统计 + 用户管理 + 邀请码 + 系统设置"""
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, func, delete as sql_delete, update as sql_update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..database import get_db
from ..models import (
    User,
    UserRole,
    File,
    Text,
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
from ..core.deps import require_role
from ..core.storage import delete_user_storage, cleanup_upload_temp
from ..core.ws_manager import manager
from ..core.timeutil import utcnow, to_naive_utc
from ..core.app_settings import (
    get_default_quota_bytes,
    get_registration_enabled,
    get_show_github_link,
)
from ..core.quick_access import CODED_MODELS

logger = logging.getLogger(__name__)

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

    # 3. 访问码统计：按「属主 + 访问码」去重计数（同一个码挂在多样内容上算一个）
    #    有效 = 未过期、属主未被禁用（与快速访问时的校验口径一致：属主被禁用后其访问码一并失效）
    total_codes: set[tuple[int, str]] = set()
    active_codes: set[tuple[int, str]] = set()
    now = utcnow()
    for model in CODED_MODELS:
        result = await db.execute(
            select(model.user_id, model.access_code, model.access_expires_at, User.is_active)
            .join(User, model.user_id == User.id)
            .where(model.access_code.is_not(None))
            .distinct()
        )
        for owner_id, code, expires_at, owner_active in result.all():
            total_codes.add((owner_id, code))
            if owner_active and (expires_at is None or expires_at > now):
                active_codes.add((owner_id, code))
    total_access_codes = len(total_codes)
    active_access_codes = len(active_codes)

    return SystemStats(
        total_users=total_users,
        active_users=active_users,
        total_files=total_files,
        total_storage_bytes=total_storage_bytes,
        total_access_codes=total_access_codes,
        active_access_codes=active_access_codes,
    )


# ========== 用户管理 ==========


async def _file_stats(db: AsyncSession, user_ids: list[int]) -> dict[int, tuple[int, int]]:
    """一次 IN + GROUP BY 查出多个用户的（已用空间, 文件数），避免逐用户查询的 N+1"""
    if not user_ids:
        return {}
    result = await db.execute(
        select(File.user_id, func.coalesce(func.sum(File.size), 0), func.count(File.id))
        .where(File.user_id.in_(user_ids))
        .group_by(File.user_id)
    )
    return {uid: (int(used), int(count)) for uid, used, count in result.all()}


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


async def _build_user_detail(db: AsyncSession, user: User) -> AdminUserDetail:
    """用户详情（安全红线：只含元数据，剪贴板只给更新时间、不给内容）"""
    used_bytes, file_count = (await _file_stats(db, [user.id])).get(user.id, (0, 0))
    result = await db.execute(
        select(Clipboard.updated_at).where(Clipboard.user_id == user.id)
    )
    return AdminUserDetail(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        quota_bytes=user.quota_bytes,
        used_bytes=used_bytes,
        file_count=file_count,
        clipboard_updated_at=result.scalar_one_or_none(),
        created_at=user.created_at,
    )


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
    # id 作为第二排序键：同一秒注册的用户分页时不会重复或漏掉
    result = await db.execute(
        select(User)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset(skip)
        .limit(limit)
    )
    users = result.scalars().all()

    result = await db.execute(select(func.count(User.id)))
    total = result.scalar()

    stats = await _file_stats(db, [u.id for u in users])
    items = [
        AdminUserListItem(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            quota_bytes=user.quota_bytes,
            used_bytes=stats.get(user.id, (0, 0))[0],
            file_count=stats.get(user.id, (0, 0))[1],
            created_at=user.created_at,
        )
        for user in users
    ]

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
    user = await _get_user_or_404(db, user_id)
    return await _build_user_detail(db, user)


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
    user = await _get_user_or_404(db, user_id)
    user.quota_bytes = data.quota_bytes
    await db.commit()

    # 通知目标用户的在线终端刷新侧栏配额
    await manager.broadcast_to_user(
        user_id=user_id,
        message={"type": "quota_updated", "data": {"quota_bytes": data.quota_bytes}},
    )
    # expire_on_commit=False，提交后属性仍可直接读取，无需 refresh
    return await _build_user_detail(db, user)


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

    # 安全红线：superadmin 之间互不可禁用
    if user.role == UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能修改其他超级管理员的状态",
        )

    # 3. 更新状态
    user.is_active = data.is_active
    await db.commit()
    await db.refresh(user)

    # 安全红线：禁用后立即断开其实时连接（HTTP 接口由 get_current_user 每次回库拦截）
    if not user.is_active:
        await manager.disconnect_user(user.id)

    # 4. 返回详情
    return await _build_user_detail(db, user)


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
    - 级联删除：文件（磁盘+记录）、剪贴板、文本栏目等（访问码挂在这些内容上，随之删除）
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

    # 安全红线：superadmin 之间互不可删除
    if user.role == UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能删除其他超级管理员",
        )

    # 3. 锁住被删用户行，与 init_upload 的加锁串行化：防止「读到的 upload_ids」与随后并发 init 新建的会话
    #    之间出现空档，导致新会话的临时目录成为无主孤儿。加锁前先 commit 结束鉴权读视图（MySQL 默认 RR）。
    await db.commit()
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())

    # 进行中的上传会话（用于清理临时目录）
    result = await db.execute(select(UploadSession.upload_id).where(UploadSession.user_id == user_id))
    upload_ids = [row[0] for row in result.all()]

    # 4. 显式按依赖顺序删除关联数据（迁移中外键没有 ON DELETE CASCADE，不能依赖数据库级联）
    await db.execute(sql_delete(UploadSession).where(UploadSession.user_id == user_id))
    await db.execute(sql_delete(File).where(File.user_id == user_id))
    await db.execute(sql_delete(Text).where(Text.user_id == user_id))
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

    # 5. 删除磁盘文件与临时目录（rmtree 可能涉及大量文件，放入线程池避免阻塞事件循环）
    #    记录已删除：磁盘清理失败只记日志，残留目录由 scripts/cleanup_expired.py 的孤儿扫描兜底
    try:
        await run_in_threadpool(delete_user_storage, user_id)
    except OSError:
        logger.exception("删除用户存储目录失败 user_id=%s", user_id)
    for upload_id in upload_ids:
        try:
            await run_in_threadpool(cleanup_upload_temp, upload_id)
        except OSError:
            logger.exception("清理上传临时目录失败 upload_id=%s", upload_id)

    # 6. 断开该用户所有实时连接
    await manager.disconnect_user(user_id)

    return None


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
    try:
        expires_at = to_naive_utc(data.expires_at)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="过期时间超出有效范围",
        )
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

    # 新建的码必然未被使用，不需要再查使用者
    return InviteCodeResponse(
        id=invite_code.id,
        code=invite_code.code,
        created_by=invite_code.created_by,
        created_by_username=current_user.username,
        used_by=None,
        used_by_username=None,
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
    # 创建者 join、使用者 outer join，一次查完（避免逐条查使用者用户名的 N+1）
    creator, used_by_user = aliased(User), aliased(User)
    result = await db.execute(
        select(InviteCode, creator.username, used_by_user.username)
        .join(creator, InviteCode.created_by == creator.id)
        .outerjoin(used_by_user, InviteCode.used_by == used_by_user.id)
        .order_by(InviteCode.created_at.desc(), InviteCode.id.desc())
    )
    rows = result.all()

    items = []
    for invite_code, creator_username, used_by_username in rows:
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

    # 已使用的码保留作为注册审计记录，不允许删除（used_at 非空即用过，使用者被删后 used_by 会置空）
    if invite_code.used_at is not None or invite_code.used_by is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邀请码已被使用，不能删除",
        )

    # 删除邀请码
    await db.execute(sql_delete(InviteCode).where(InviteCode.id == invite_code_id))
    await db.commit()

    return None


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
    return await _read_system_settings(db)


async def _read_system_settings(db: AsyncSession) -> SystemSettingsResponse:
    """统一走 core/app_settings 读取：脏数据回落默认值，不会 500"""
    return SystemSettingsResponse(
        default_quota_bytes=await get_default_quota_bytes(db),
        registration_enabled=await get_registration_enabled(db),
        show_github_link=await get_show_github_link(db),
    )


async def _upsert_setting(db: AsyncSession, key: str, value: str) -> None:
    """INSERT ... ON DUPLICATE KEY UPDATE：并发首次写入同一 key 不会撞主键"""
    stmt = mysql_insert(Setting).values(key=key, value=value, updated_at=utcnow())
    stmt = stmt.on_duplicate_key_update(value=value, updated_at=utcnow())
    await db.execute(stmt)


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
    if data.default_quota_bytes is not None:
        await _upsert_setting(db, "default_quota_bytes", str(data.default_quota_bytes))

    if data.registration_enabled is not None:
        await _upsert_setting(
            db, "registration_enabled", "true" if data.registration_enabled else "false"
        )

    if data.show_github_link is not None:
        await _upsert_setting(
            db, "show_github_link", "true" if data.show_github_link else "false"
        )

    await db.commit()
    return await _read_system_settings(db)


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
        # id 作为第二排序键：同一秒上传的文件分页时不会重复或漏掉
        .order_by(File.created_at.desc(), File.id.desc())
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



