"""管理后台路由：统计 + 用户管理 + 邀请码 + 系统设置 + 系统信息 + 文件元数据列表 + 超管只读查看用户文本"""
import logging
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, func, exists, delete as sql_delete, update as sql_update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..database import get_db
from ..models import (
    User,
    UserRole,
    File,
    Text,
    InviteBatch,
    InviteCode,
    Setting,
    Clipboard,
    ClipboardHistory,
    UploadSession,
    Deployment,
)
from ..schemas import (
    SystemStats,
    AdminUserListItem,
    AdminUserListResponse,
    AdminUserDetail,
    UpdateUserQuota,
    UpdateUserStatus,
    UpdateUserRole,
    ClipboardResponse,
    ClipboardHistoryItem,
    ClipboardHistoryList,
    TextResponse,
    TextListResponse,
    InviteBatchCreate,
    InviteBatchNoteUpdate,
    InviteCodeExpiryUpdate,
    InviteCodeExpiryResult,
    InviteCodeResponse,
    InviteBatchResponse,
    InviteBatchListResponse,
    InviteBatchDeleteResult,
    SystemSettingsResponse,
    UpdateSystemSettings,
    DeploymentResponse,
    DeployInfoResponse,
    DeploymentNoteUpdate,
    AdminFileListItem,
    AdminFileListResponse,
)
from ..core.deps import require_role
from ..core.storage import delete_user_storage, cleanup_upload_temp
from ..core.ws_manager import manager
from ..core.timeutil import utcnow, parse_future_expiry
from ..core.app_settings import (
    get_default_quota_bytes,
    get_registration_enabled,
    get_show_github_link,
)
from ..core.quick_access import CODED_MODELS
from ..core.invite_code import generate_invite_code
from ..core.deploy_info import STARTED_AT, current_build, current_deployment
from .clipboard import to_clipboard_response, history_list_query, rows_to_history_list, to_history_item
from .texts import summary_query, rows_to_summaries, to_text_response, MAX_TEXTS_PER_USER

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
    result = await db.execute(select(func.count(User.id)))
    total_users = result.scalar()

    result = await db.execute(
        select(func.count(User.id)).where(User.is_active.is_(True))
    )
    active_users = result.scalar()

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
    """用户详情（安全红线：只含元数据，云剪切板只给更新时间、不给内容）"""
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


def _ensure_admin_targets_plain_user(current_user: User, target: User) -> None:
    """安全红线：admin 只能管理普通用户，不能动其他 admin 和 superadmin（也包括自己）"""
    if current_user.role == UserRole.ADMIN and target.role != UserRole.USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理员只能管理普通用户",
        )


@router.patch("/users/{user_id}/quota", response_model=AdminUserDetail)
async def update_user_quota(
    user_id: int,
    data: UpdateUserQuota,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    修改用户配额

    权限：admin（只能改普通用户）+ superadmin（可改所有人）
    """
    user = await _get_user_or_404(db, user_id)
    _ensure_admin_targets_plain_user(current_user, user)
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
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    修改用户状态（启用/禁用）

    权限：admin（只能操作普通用户）+ superadmin（不能操作其他 superadmin）
    """
    user = await _get_user_or_404(db, user_id)

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
    _ensure_admin_targets_plain_user(current_user, user)

    user.is_active = data.is_active
    await db.commit()

    # 安全红线：禁用后立即断开其实时连接（HTTP 接口由 get_current_user 每次回库拦截）
    if not user.is_active:
        await manager.disconnect_user(user.id)

    # expire_on_commit=False，提交后属性仍可直接读取，无需 refresh
    return await _build_user_detail(db, user)


@router.patch("/users/{user_id}/role", response_model=AdminUserDetail)
async def update_user_role(
    user_id: int,
    data: UpdateUserRole,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    修改用户角色（普通用户 ↔ 管理员）

    权限：仅 superadmin
    安全红线：admin 不能改角色（否则被盗的管理员账号可以再提拔别的账号）；
    不能把人设为 superadmin（schema 只接受 user / admin），也不能改自己或其他 superadmin 的角色
    """
    user = await _get_user_or_404(db, user_id)
    if user.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改自己的角色")
    if user.role == UserRole.SUPERADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不能修改超级管理员的角色")

    user.role = UserRole(data.role)
    await db.commit()

    # 通知目标用户的在线终端刷新身份：降级后管理后台入口立即消失（接口权限由 get_current_user 每次回库判断）
    await manager.broadcast_to_user(
        user_id=user_id,
        message={"type": "role_updated", "data": {"role": user.role.value}},
    )
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
    - 级联删除：文件（磁盘+记录）、云剪切板、文本栏目等（访问码挂在这些内容上，随之删除）
    """
    user = await _get_user_or_404(db, user_id)

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

    # 1. 锁住被删用户行，与 init_upload 的加锁串行化：防止「读到的 upload_ids」与随后并发 init 新建的会话
    #    之间出现空档，导致新会话的临时目录成为无主孤儿。加锁前先 commit 结束鉴权读视图（MySQL 默认 RR）。
    await db.commit()
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())

    # 进行中的上传会话（用于清理临时目录）
    result = await db.execute(select(UploadSession.upload_id).where(UploadSession.user_id == user_id))
    upload_ids = [row[0] for row in result.all()]

    # 2. 显式按依赖顺序删除关联数据（迁移中外键没有 ON DELETE CASCADE，不能依赖数据库级联）
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
    # 邀请码批次：码被删光的批次一起删除，还剩已使用码的批次转记到操作者名下（保留备注）
    await db.execute(
        sql_delete(InviteBatch).where(
            InviteBatch.created_by == user_id,
            ~exists().where(InviteCode.batch_id == InviteBatch.id),
        )
    )
    await db.execute(
        sql_update(InviteBatch).where(InviteBatch.created_by == user_id).values(created_by=current_user.id)
    )
    await db.execute(sql_delete(User).where(User.id == user_id))
    await db.commit()

    # 3. 删除磁盘文件与临时目录（rmtree 可能涉及大量文件，放入线程池避免阻塞事件循环）
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

    # 4. 断开该用户所有实时连接
    await manager.disconnect_user(user_id)

    return None


# ========== 邀请码管理 ==========


def _parse_invite_expiry(value: datetime | None) -> datetime | None:
    """过期时间统一转 naive UTC（与 register 中的 utcnow() 比较口径一致），且必须晚于当前时间；邀请码没有最长期限"""
    try:
        return parse_future_expiry(value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _is_used(invite: InviteCode) -> bool:
    """邀请码是否已用过：used_at 非空即用过（使用者被删后 used_by 会置空，used_at 仍保留）"""
    return invite.used_at is not None or invite.used_by is not None


async def _load_batches(db: AsyncSession, batch_id: int | None = None) -> list[InviteBatchResponse]:
    """查批次及其中的码：批次 + 创建者、码 + 使用者各一次查询，不逐批查（避免 N+1）；batch_id 为空时查全部"""
    creator, used_by_user = aliased(User), aliased(User)
    batch_query = (
        select(InviteBatch, creator.username)
        .join(creator, InviteBatch.created_by == creator.id)
        .order_by(InviteBatch.created_at.desc(), InviteBatch.id.desc())
    )
    code_query = (
        select(InviteCode, used_by_user.username)
        .outerjoin(used_by_user, InviteCode.used_by == used_by_user.id)
        .order_by(InviteCode.id)
    )
    if batch_id is not None:
        batch_query = batch_query.where(InviteBatch.id == batch_id)
        code_query = code_query.where(InviteCode.batch_id == batch_id)

    batches = (await db.execute(batch_query)).all()
    if not batches:
        return []
    codes_by_batch: dict[int, list[InviteCodeResponse]] = defaultdict(list)
    for invite, used_by_username in (await db.execute(code_query)).all():
        codes_by_batch[invite.batch_id].append(InviteCodeResponse(
            id=invite.id,
            code=invite.code,
            used_by=invite.used_by,
            used_by_username=used_by_username,
            expires_at=invite.expires_at,
            used_at=invite.used_at,
        ))
    return [
        InviteBatchResponse(
            id=batch.id,
            note=batch.note,
            created_by=batch.created_by,
            created_by_username=creator_username,
            created_at=batch.created_at,
            codes=codes_by_batch[batch.id],
        )
        for batch, creator_username in batches
    ]


@router.post("/invite-batches", response_model=InviteBatchResponse)
async def create_invite_batch(
    data: InviteBatchCreate,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    生成一批邀请码：一次 1–20 个（1 个也算一批），同一批共用一个过期时间和备注；全部成功或全部不生成

    权限：admin + superadmin
    """
    expires_at = _parse_invite_expiry(data.expires_at)

    # 生成 count 个互不相同、且库里不存在的码（重名概率极低，有冲突就重新抽，最多 5 轮）
    codes: set[str] = set()
    for _ in range(5):
        while len(codes) < data.count:
            codes.add(generate_invite_code())
        result = await db.execute(select(InviteCode.code).where(InviteCode.code.in_(codes)))
        taken = set(result.scalars().all())
        if not taken:
            break
        codes -= taken
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="邀请码生成失败，请重试",
        )

    now = utcnow()
    batch = InviteBatch(note=data.note, created_by=current_user.id, created_at=now)
    db.add(batch)
    await db.flush()
    db.add_all(
        InviteCode(batch_id=batch.id, code=code, created_by=current_user.id, expires_at=expires_at, created_at=now)
        for code in codes
    )
    try:
        await db.commit()
    except IntegrityError:
        # 唯一约束兜底：查重之后有并发请求恰好生成了同一个码
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="邀请码生成失败，请重试",
        )

    # 与列表接口同一个格式，码按生成顺序排列
    return (await _load_batches(db, batch.id))[0]


@router.patch("/invite-codes/expiry", response_model=InviteCodeExpiryResult)
async def update_invite_codes_expiry(
    data: InviteCodeExpiryUpdate,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    批量修改邀请码有效期（单个修改也走这里）：只能改未使用的码，已过期但未使用的可借此续期

    任何一个 id 不存在（404）或已被使用（409）时整批不改。
    行锁与注册时的 FOR UPDATE 互斥，避免「刚被用掉的码又被改了有效期」。

    权限：admin + superadmin
    """
    expires_at = _parse_invite_expiry(data.expires_at)
    ids = set(data.ids)

    result = await db.execute(
        select(InviteCode).where(InviteCode.id.in_(ids)).with_for_update()
    )
    invites = result.scalars().all()

    if len(invites) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="部分邀请码不存在，请刷新列表后重试",
        )
    if any(_is_used(i) for i in invites):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="已使用的邀请码不能修改有效期",
        )

    await db.execute(
        sql_update(InviteCode).where(InviteCode.id.in_(ids)).values(expires_at=expires_at)
    )
    await db.commit()
    return InviteCodeExpiryResult(updated=len(ids), expires_at=expires_at)


@router.get("/invite-batches", response_model=InviteBatchListResponse)
async def list_invite_batches(
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    获取邀请码批次列表（按创建时间倒序），每批带其中全部邀请码及使用者

    权限：admin + superadmin
    """
    items = await _load_batches(db)
    return InviteBatchListResponse(items=items, total=len(items))


@router.patch("/invite-batches/{batch_id}", response_model=InviteBatchResponse)
async def update_invite_batch_note(
    batch_id: int,
    data: InviteBatchNoteUpdate,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    修改批次备注（空字符串为清空）；批次里的码已全部用掉也可以改

    权限：admin + superadmin
    """
    batch = (await db.execute(
        select(InviteBatch).where(InviteBatch.id == batch_id)
    )).scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="批次不存在",
        )
    batch.note = data.note
    await db.commit()
    return (await _load_batches(db, batch_id))[0]


@router.delete("/invite-batches/{batch_id}", response_model=InviteBatchDeleteResult)
async def delete_invite_batch_unused(
    batch_id: int,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    删除批次里所有未使用的邀请码（含已过期未使用的）；已使用的保留作审计记录。
    批次里不剩码时批次一起删除，否则批次与备注保留。

    行锁与注册时的 FOR UPDATE 互斥，避免删除的同时有人用这批里的码注册。

    权限：admin + superadmin
    """
    batch = (await db.execute(
        select(InviteBatch).where(InviteBatch.id == batch_id).with_for_update()
    )).scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="批次不存在",
        )

    invites = (await db.execute(
        select(InviteCode).where(InviteCode.batch_id == batch_id).with_for_update()
    )).scalars().all()
    unused_ids = [i.id for i in invites if not _is_used(i)]

    if unused_ids:
        await db.execute(sql_delete(InviteCode).where(InviteCode.id.in_(unused_ids)))
    batch_deleted = len(unused_ids) == len(invites)
    if batch_deleted:
        await db.execute(sql_delete(InviteBatch).where(InviteBatch.id == batch_id))
    await db.commit()
    return InviteBatchDeleteResult(deleted=len(unused_ids), batch_deleted=batch_deleted)


@router.delete("/invite-codes/{invite_code_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invite_code(
    invite_code_id: int,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    删除单个未使用的邀请码；批次里不剩码时批次一起删除

    行锁与注册时的 FOR UPDATE 互斥：注册正在用这个码时，等它提交后再判断「是否已使用」，
    不会把刚被用掉的码删掉（已使用的码要保留作审计记录）。

    权限：admin + superadmin
    """
    # 查询邀请码（加锁读，读到的是最新状态）
    result = await db.execute(
        select(InviteCode).where(InviteCode.id == invite_code_id).with_for_update()
    )
    invite_code = result.scalar_one_or_none()

    if not invite_code:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="邀请码不存在",
        )

    # 已使用的码保留作为注册审计记录，不允许删除
    if _is_used(invite_code):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邀请码已被使用，不能删除",
        )

    # 删除邀请码；批次被删空时一起删除，列表里不留空批次
    await db.execute(sql_delete(InviteCode).where(InviteCode.id == invite_code_id))
    await db.execute(
        sql_delete(InviteBatch).where(
            InviteBatch.id == invite_code.batch_id,
            ~exists().where(InviteCode.batch_id == InviteBatch.id),
        )
    )
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
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    更新系统设置

    权限：admin + superadmin
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


# ========== 系统信息（版本与部署记录） ==========

# 部署记录一次返回最近的条数
DEPLOY_HISTORY_LIMIT = 50


@router.get("/deploy-info", response_model=DeployInfoResponse)
async def get_deploy_info(
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    正在运行的版本、本次启动时间、已运行时长与最近的部署记录

    权限：admin + superadmin（只含版本与部署信息，不含用户数据）
    """
    build = current_build()
    result = await db.execute(
        select(Deployment).order_by(Deployment.id.desc()).limit(DEPLOY_HISTORY_LIMIT)
    )
    history = result.scalars().all()
    total = (await db.execute(select(func.count(Deployment.id)))).scalar()
    current = await current_deployment(db, build)
    return DeployInfoResponse(
        app_version=build.app_version,
        commit_sha=build.commit_sha,
        branch=build.branch,
        built_at=build.built_at,
        started_at=STARTED_AT,
        uptime_seconds=max(0, int((utcnow() - STARTED_AT).total_seconds())),
        current=DeploymentResponse.model_validate(current) if current else None,
        history=[DeploymentResponse.model_validate(item) for item in history],
        total=total,
    )


@router.patch("/deployments/{deployment_id}", response_model=DeploymentResponse)
async def update_deployment_note(
    deployment_id: int,
    data: DeploymentNoteUpdate,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    修改部署备注，空字符串表示清除

    权限：仅 superadmin
    """
    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部署记录不存在")
    deployment.note = data.note
    await db.commit()
    return DeploymentResponse.model_validate(deployment)


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
    result = await db.execute(
        select(File, User.username)
        .join(User, File.user_id == User.id)
        # id 作为第二排序键：同一秒上传的文件分页时不会重复或漏掉
        .order_by(File.created_at.desc(), File.id.desc())
        .offset(skip)
        .limit(limit)
    )
    rows = result.all()

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


# ========== 查看用户文本内容（仅 superadmin，只读） ==========
# 安全红线：这一组接口是唯一能读到他人文本内容的入口，只放行 superadmin；全部只读，
# 不提供修改、删除、恢复；每次读取写一条日志，便于事后追溯谁看过谁的内容


async def _content_owner_or_404(db: AsyncSession, current_user: User, user_id: int, what: str) -> User:
    # 安全红线：超管查看他人内容的审计日志点，只记操作者、对象和内容类别，不记正文
    user = await _get_user_or_404(db, user_id)
    logger.info("超管查看用户内容 operator=%s target=%s what=%s", current_user.id, user_id, what)
    return user


@router.get("/users/{user_id}/clipboard", response_model=ClipboardResponse)
async def get_user_clipboard(
    user_id: int,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """查看某用户云剪切板的当前文本（权限：仅 superadmin，只读）"""
    await _content_owner_or_404(db, current_user, user_id, "clipboard")
    result = await db.execute(select(Clipboard).where(Clipboard.user_id == user_id))
    return to_clipboard_response(result.scalar_one_or_none())


@router.get("/users/{user_id}/clipboard/history", response_model=ClipboardHistoryList)
async def get_user_clipboard_history(
    user_id: int,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """查看某用户云剪切板的历史列表，长内容只给开头（权限：仅 superadmin，只读）"""
    await _content_owner_or_404(db, current_user, user_id, "clipboard_history")
    result = await db.execute(history_list_query(user_id))
    return rows_to_history_list(result.all())


@router.get("/users/{user_id}/clipboard/history/{history_id}", response_model=ClipboardHistoryItem)
async def get_user_clipboard_history_item(
    user_id: int,
    history_id: int,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """查看某用户一条历史的全文（权限：仅 superadmin，只读；按「用户 + 历史 id」定位）"""
    await _content_owner_or_404(db, current_user, user_id, f"clipboard_history:{history_id}")
    result = await db.execute(
        select(ClipboardHistory).where(
            ClipboardHistory.id == history_id,
            ClipboardHistory.user_id == user_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="历史记录不存在")
    return to_history_item(item)


@router.get("/users/{user_id}/texts", response_model=TextListResponse)
async def list_user_texts(
    user_id: int,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """查看某用户的文本栏目列表，长内容只给开头（权限：仅 superadmin，只读）"""
    await _content_owner_or_404(db, current_user, user_id, "texts")
    result = await db.execute(summary_query(Text.user_id == user_id))
    items = rows_to_summaries(result.all())
    return TextListResponse(items=items, total=len(items), max_texts=MAX_TEXTS_PER_USER)


@router.get("/users/{user_id}/texts/{text_id}", response_model=TextResponse)
async def get_user_text(
    user_id: int,
    text_id: int,
    current_user: User = Depends(require_role(UserRole.SUPERADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """查看某用户一条文本的全文（权限：仅 superadmin，只读；按「用户 + 文本 id」定位）"""
    await _content_owner_or_404(db, current_user, user_id, f"text:{text_id}")
    result = await db.execute(select(Text).where(Text.id == text_id, Text.user_id == user_id))
    text = result.scalar_one_or_none()
    if text is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文本不存在")
    return to_text_response(text)
