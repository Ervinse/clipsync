"""访问码路由：给内容设置访问码 + 总览（需登录） / 凭「用户名@访问码」快速访问（公开，限流）

访问码挂在内容上：云剪切板、文本栏目里的每条文本、每个文件各自最多一个访问码，
同一用户的多样内容可以用同一个码。完整访问码为「用户名@访问码」，凭它换取 2 小时的快速访问凭证，
进入后能看到该码下的全部内容：文本可查看与修改，文件可下载；不能新建、删除、上传，也不能改访问码。
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, update, func, case, literal_column
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, Clipboard, Text, File
from ..schemas import (
    AccessTargetType,
    AccessCodeSet,
    AccessCodeTarget,
    AccessCodeGroup,
    AccessCodeOverview,
    QuickLoginRequest,
    QuickLoginResponse,
    QuickClipboardSummary,
    QuickFileItem,
    QuickItemsResponse,
    ClipboardUpdate,
    ClipboardResponse,
    TextUpdate,
    TextResponse,
)
from ..core.deps import get_current_user, security
from ..core.security import decode_access_token
from ..core.quick_access import (
    MAX_EXPIRES_HOURS,
    QUICK_TOKEN_MINUTES,
    LOCK_SECONDS,
    parse_full_code,
    parse_quick_payload,
    create_quick_token,
    code_is_active,
    valid_code_filter,
    failures,
    notify_quick_viewers,
)
from ..core.timeutil import utcnow, to_naive_utc
from ..core.ws_manager import manager
from ..rate_limit import limiter
from .clipboard import write_clipboard, to_clipboard_response
from .texts import write_text, summary_query, rows_to_summaries, to_text_response, INLINE_CONTENT_BYTES, PREVIEW_CHARS
from .files import stream_file_response

# 需登录的管理接口，挂载在 /api/access-codes
router = APIRouter()
# 免登录访问接口，挂载在 /api/access（与管理接口分开，避免公开处理函数出现在登录前缀下）
public_router = APIRouter()

# 换取凭证的接口按 IP 限流更严；持有凭证后的读写接口放宽，编辑与实时刷新不至于很快触发限流
LOGIN_RATE = "30/minute"
QUICK_RATE = "120/minute"

LABEL_CHARS = 30  # 总览里没有标题的文本取内容开头作为名称

INVALID_DETAIL = "访问码无效或已失效"
CONTENT_GONE_DETAIL = "内容不存在或访问码已失效"


def _check_expires(value: Optional[datetime]) -> Optional[datetime]:
    """过期时间转为 naive UTC，并校验晚于当前时间、不超过 1 年后"""
    try:
        expires_at = to_naive_utc(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="过期时间超出有效范围")
    if expires_at is not None and expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="过期时间必须晚于当前时间")
    # 最长有效期 1 年（前端同样校验）；留 1 分钟余量，避免前端按 8760 小时计算后因时钟误差被拒
    if expires_at is not None and expires_at > utcnow() + timedelta(hours=MAX_EXPIRES_HOURS, minutes=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"有效期最长 {MAX_EXPIRES_HOURS} 小时")
    return expires_at


def _text_label(title: str, head: str) -> str:
    return title or (head or "").strip()[:LABEL_CHARS] or "（空白文本）"


# ========== 需登录：设置访问码与总览 ==========


@router.put("", response_model=AccessCodeTarget)
async def set_access_code(
    data: AccessCodeSet,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    给云剪切板 / 一条文本 / 一个文件设置、修改或清除访问码（code 为 null 即清除）。

    安全红线：文本与文件按 (id, user_id) 定位，只能给自己的内容设置访问码；他人内容与不存在统一 404。
    改动后通知凭旧码、新码进入的快速访问页：旧码下没有内容了的直接断开。
    """
    owner_id = current_user.id
    code = data.code
    expires_at = _check_expires(data.expires_at) if code is not None else None

    if data.target_type == AccessTargetType.CLIPBOARD:
        result = await db.execute(select(Clipboard.access_code).where(Clipboard.user_id == owner_id))
        old_row = result.first()
        old_code = old_row[0] if old_row else None
        if old_row is not None or code is not None:
            # 还没有剪切板记录时建一条空的（version 0 表示还没有保存过内容）；已有记录只改访问码列
            stmt = mysql_insert(Clipboard).values(
                user_id=owner_id, content="", updated_at=utcnow(), version=0,
                access_code=code, access_expires_at=expires_at,
            ).on_duplicate_key_update(access_code=code, access_expires_at=expires_at)
            await db.execute(stmt)
        target_id, label = None, ""
    else:
        if data.target_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请指定要设置访问码的内容")
        if data.target_type == AccessTargetType.TEXT:
            columns = (Text.title, func.left(Text.content, LABEL_CHARS), Text.access_code)
            model = Text
        else:
            columns = (File.original_name, literal_column("''"), File.access_code)
            model = File
        result = await db.execute(
            select(*columns).where(model.id == data.target_id, model.user_id == owner_id)  # 安全红线：归属校验
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="内容不存在或无权访问")
        name, head, old_code = row
        await db.execute(
            update(model)
            .where(model.id == data.target_id, model.user_id == owner_id)
            .values(access_code=code, access_expires_at=expires_at)
        )
        target_id = data.target_id
        label = _text_label(name, head) if model is Text else name

    await db.commit()

    await manager.broadcast_to_user(user_id=owner_id, message={"type": "access_codes_changed", "data": {}})
    await notify_quick_viewers(owner_id, [old_code, code])

    return AccessCodeTarget(
        target_type=data.target_type,
        target_id=target_id,
        label=label,
        access_code=code,
        access_expires_at=expires_at,
    )


@router.get("", response_model=AccessCodeOverview)
async def access_code_overview(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """按访问码分组列出自己设置过访问码的内容（安全红线：强制按 user_id 过滤）"""
    uid = current_user.id
    items: list[AccessCodeTarget] = []

    result = await db.execute(
        select(Clipboard.access_code, Clipboard.access_expires_at)
        .where(Clipboard.user_id == uid, Clipboard.access_code.is_not(None))
    )
    for code, expires in result.all():
        items.append(AccessCodeTarget(
            target_type=AccessTargetType.CLIPBOARD, target_id=None, label="",
            access_code=code, access_expires_at=expires,
        ))

    result = await db.execute(
        select(Text.id, Text.title, func.left(Text.content, LABEL_CHARS), Text.access_code, Text.access_expires_at)
        .where(Text.user_id == uid, Text.access_code.is_not(None))
        .order_by(Text.updated_at.desc(), Text.id.desc())
    )
    for text_id, title, head, code, expires in result.all():
        items.append(AccessCodeTarget(
            target_type=AccessTargetType.TEXT, target_id=text_id, label=_text_label(title, head),
            access_code=code, access_expires_at=expires,
        ))

    result = await db.execute(
        select(File.id, File.original_name, File.access_code, File.access_expires_at)
        .where(File.user_id == uid, File.access_code.is_not(None))
        .order_by(File.created_at.desc(), File.id.desc())
    )
    for file_id, name, code, expires in result.all():
        items.append(AccessCodeTarget(
            target_type=AccessTargetType.FILE, target_id=file_id, label=name,
            access_code=code, access_expires_at=expires,
        ))

    groups: dict[str, list[AccessCodeTarget]] = {}
    for item in items:
        groups.setdefault(item.access_code, []).append(item)
    return AccessCodeOverview(
        username=current_user.username,
        groups=[AccessCodeGroup(code=code, items=groups[code]) for code in sorted(groups)],
        total=len(groups),
    )


# ========== 免登录：凭完整访问码换取快速访问凭证，再访问该码下的内容 ==========


@dataclass
class QuickViewer:
    owner_id: int
    owner_username: str
    code: str


def _quick_lost() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="访问码已失效，请重新输入",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_quick_viewer(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> QuickViewer:
    """
    依赖注入：校验快速访问凭证。
    安全红线：每次请求都回库确认属主未禁用、访问码下仍有未过期的内容。访问码被清除、修改、
    过期或属主被禁用后，凭证立即失效，不用等 2 小时到期。登录凭证不能用在这里（没有 typ=qa）。
    """
    parsed = parse_quick_payload(decode_access_token(credentials.credentials)) if credentials else None
    if parsed is None:
        raise _quick_lost()
    owner_id, code = parsed
    result = await db.execute(select(User).where(User.id == owner_id))
    owner = result.scalar_one_or_none()
    if owner is None or not owner.is_active or not await code_is_active(db, owner_id, code):
        raise _quick_lost()
    return QuickViewer(owner_id=owner_id, owner_username=owner.username, code=code)


@public_router.post("/login", response_model=QuickLoginResponse)
@limiter.limit(LOGIN_RATE)
async def quick_login(
    request: Request,
    data: QuickLoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    凭「用户名@访问码」换取快速访问凭证。

    安全红线：
    - 用户名不存在 / 访问码不对 / 已过期 / 属主被禁用，一律返回同样的 404，不暴露是哪一种
    - 同一用户名连续输错 10 次锁定 15 分钟（不存在的用户名同样计数），锁定期间输对也不放行
    """
    parsed = parse_full_code(data.full_code)
    if parsed is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请按「用户名@访问码」的格式输入")
    username, code = parsed

    if failures.is_locked(username):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"尝试次数过多，请 {LOCK_SECONDS // 60} 分钟后再试",
        )

    result = await db.execute(select(User).where(User.username == username))
    owner = result.scalar_one_or_none()
    if owner is None or not owner.is_active or not await code_is_active(db, owner.id, code):
        failures.record_failure(username)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=INVALID_DETAIL)

    failures.reset(username)
    return QuickLoginResponse(
        access_token=create_quick_token(owner.id, code),
        owner_username=owner.username,
        code=code,
        expires_in=QUICK_TOKEN_MINUTES * 60,
    )


@public_router.get("/items", response_model=QuickItemsResponse)
@limiter.limit(QUICK_RATE)
async def quick_items(
    request: Request,
    viewer: QuickViewer = Depends(get_quick_viewer),
    db: AsyncSession = Depends(get_db),
):
    """列出该访问码下的全部内容（长文本只给开头，打开时再取全文）"""
    size = func.octet_length(Clipboard.content)
    result = await db.execute(
        select(
            Clipboard.version,
            case((size <= INLINE_CONTENT_BYTES, Clipboard.content), else_=literal_column("NULL")).label("content"),
            func.left(Clipboard.content, PREVIEW_CHARS).label("preview"),
            size.label("size"),
            Clipboard.updated_at,
            Clipboard.access_expires_at,
        ).where(*valid_code_filter(Clipboard, viewer.owner_id, viewer.code))
    )
    clip_row = result.first()
    clipboard = QuickClipboardSummary(**clip_row._mapping) if clip_row else None

    result = await db.execute(summary_query(*valid_code_filter(Text, viewer.owner_id, viewer.code)))
    texts = rows_to_summaries(result.all())

    result = await db.execute(
        select(File)
        .where(*valid_code_filter(File, viewer.owner_id, viewer.code))
        .order_by(File.created_at.desc(), File.id.desc())
    )
    files = [
        QuickFileItem(
            id=f.id, original_name=f.original_name, size=f.size, mime_type=f.mime_type,
            created_at=f.created_at, access_expires_at=f.access_expires_at,
        )
        for f in result.scalars().all()
    ]

    return QuickItemsResponse(
        owner_username=viewer.owner_username,
        code=viewer.code,
        clipboard=clipboard,
        texts=texts,
        files=files,
    )


@public_router.get("/clipboard", response_model=ClipboardResponse)
@limiter.limit(QUICK_RATE)
async def quick_get_clipboard(
    request: Request,
    viewer: QuickViewer = Depends(get_quick_viewer),
    db: AsyncSession = Depends(get_db),
):
    """读取云剪切板全文（剪切板必须挂着这个访问码）"""
    result = await db.execute(select(Clipboard).where(*valid_code_filter(Clipboard, viewer.owner_id, viewer.code)))
    clipboard = result.scalar_one_or_none()
    if clipboard is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CONTENT_GONE_DETAIL)
    return to_clipboard_response(clipboard)


@public_router.put("/clipboard", response_model=ClipboardResponse)
@limiter.limit(QUICK_RATE)
async def quick_update_clipboard(
    request: Request,
    data: ClipboardUpdate,
    viewer: QuickViewer = Depends(get_quick_viewer),
    db: AsyncSession = Depends(get_db),
):
    """修改云剪切板：与登录编辑相同，旧内容进历史、做冲突检测、通知属主的其他终端"""
    return await write_clipboard(
        db, viewer.owner_id, data.content, base_version=data.base_version, require_code=viewer.code
    )


@public_router.get("/texts/{text_id}", response_model=TextResponse)
@limiter.limit(QUICK_RATE)
async def quick_get_text(
    request: Request,
    text_id: int,
    viewer: QuickViewer = Depends(get_quick_viewer),
    db: AsyncSession = Depends(get_db),
):
    """读取一条文本的全文（安全红线：文本必须属于属主且挂着这个访问码，否则 404）"""
    result = await db.execute(
        select(Text).where(Text.id == text_id, *valid_code_filter(Text, viewer.owner_id, viewer.code))
    )
    text = result.scalar_one_or_none()
    if text is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CONTENT_GONE_DETAIL)
    return to_text_response(text)


@public_router.put("/texts/{text_id}", response_model=TextResponse)
@limiter.limit(QUICK_RATE)
async def quick_update_text(
    request: Request,
    text_id: int,
    data: TextUpdate,
    viewer: QuickViewer = Depends(get_quick_viewer),
    db: AsyncSession = Depends(get_db),
):
    """修改一条文本的标题与内容（安全红线：加锁后再确认文本仍挂着这个访问码）"""
    return await write_text(db, viewer.owner_id, text_id, data, require_code=viewer.code)


@public_router.get("/files/{file_id}/download")
@limiter.limit(QUICK_RATE)
async def quick_download_file(
    request: Request,
    file_id: int,
    viewer: QuickViewer = Depends(get_quick_viewer),
    db: AsyncSession = Depends(get_db),
):
    """
    下载文件（流式）。
    安全红线：文件必须属于属主且挂着这个访问码；按 file_id 查库拿 stored_name，不信任客户端路径。
    """
    result = await db.execute(
        select(File).where(File.id == file_id, *valid_code_filter(File, viewer.owner_id, viewer.code))
    )
    file_record = result.scalar_one_or_none()
    if file_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CONTENT_GONE_DETAIL)
    return await stream_file_response(file_record, missing_detail=CONTENT_GONE_DETAIL)
