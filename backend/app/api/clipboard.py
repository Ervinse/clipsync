"""剪贴板路由：当前文本 + 历史版本管理"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete, desc, func, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.mysql import insert as mysql_insert

from ..database import get_db
from ..models import User, Clipboard, ClipboardHistory
from ..schemas import (
    ClipboardUpdate,
    ClipboardResponse,
    ClipboardHistoryItem,
    ClipboardHistoryList,
)
from ..core.deps import get_current_user
from ..core.ws_manager import manager
from ..core.quick_access import notify_quick_viewers
from ..core.timeutil import utcnow
from ..config import settings
from .texts import INLINE_CONTENT_BYTES, PREVIEW_CHARS

router = APIRouter()

CONFLICT_DETAIL = "内容已在别处更新，请先载入最新内容"


def to_clipboard_response(clipboard: Clipboard | None) -> ClipboardResponse:
    if clipboard is None:
        # 用户首次使用，返回空内容；version 0 表示还没有保存过
        return ClipboardResponse(content="", updated_at=utcnow(), version=0)
    return ClipboardResponse(
        content=clipboard.content,
        updated_at=clipboard.updated_at,
        version=clipboard.version,
        access_code=clipboard.access_code,
        access_expires_at=clipboard.access_expires_at,
    )


@router.get("", response_model=ClipboardResponse)
async def get_current_clipboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的最新剪贴板文本。

    安全红线：查询强制按 user_id 过滤。
    """
    result = await db.execute(
        select(Clipboard).where(Clipboard.user_id == current_user.id)
    )
    return to_clipboard_response(result.scalar_one_or_none())


@router.put("", response_model=ClipboardResponse)
async def update_clipboard(
    data: ClipboardUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    更新当前剪贴板文本（upsert），旧内容归档到历史，实时广播。

    安全红线：
    - 操作强制绑定 user_id
    - 历史保留策略：超出 HISTORY_KEEP 限制时自动清理最旧记录
    """
    return await write_clipboard(db, current_user.id, data.content, base_version=data.base_version)


async def write_clipboard(
    db: AsyncSession,
    user_id: int,
    content: str,
    base_version: int | None = None,
    consumed_history_id: int | None = None,
    require_code: str | None = None,
) -> ClipboardResponse:
    """
    写入当前文本：归档旧内容 + upsert + 清理超额历史 + 广播。登录编辑与快速访问共用。

    base_version：读取时的版本号；与当前版本不一致返回 409（内容已在别处被改过），None 表示直接覆盖。
    consumed_history_id：restore 时传入，被恢复的那条历史在同一事务里删除，避免重复。
    require_code：快速访问写入时传入，加锁后再确认剪切板仍挂着这个访问码且未过期，否则 404。
    """
    # 0. 锁住用户行，同一用户的剪贴板写操作串行化，防止并发时重复归档、丢失中间版本。
    #    不锁 Clipboard 行：首次写入时该行不存在，会退化为 gap lock，两个 INSERT 容易死锁。
    #    加锁前先 commit：MySQL 默认 REPEATABLE READ，鉴权读已固定了本事务的读视图，
    #    若不结束该视图，加锁后的普通 SELECT 仍读旧快照，锁等于白加。commit 开启新读视图。
    await db.commit()
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())

    # 1. 查询当前文本
    result = await db.execute(
        select(Clipboard).where(Clipboard.user_id == user_id)
    )
    old_clipboard = result.scalar_one_or_none()
    current_version = old_clipboard.version if old_clipboard else 0

    if require_code is not None and not (
        old_clipboard is not None
        and old_clipboard.access_code == require_code
        and (old_clipboard.access_expires_at is None or old_clipboard.access_expires_at > utcnow())
    ):
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="内容不存在或访问码已失效")

    if base_version is not None and base_version != current_version:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CONFLICT_DETAIL)

    if consumed_history_id is not None:
        await db.execute(
            delete(ClipboardHistory).where(
                ClipboardHistory.id == consumed_history_id,
                ClipboardHistory.user_id == user_id,
            )
        )

    # 2. 旧内容非空且与新内容不同才归档（保存相同内容不产生重复历史）
    if old_clipboard and old_clipboard.content and old_clipboard.content != content:
        history_entry = ClipboardHistory(
            user_id=user_id,
            content=old_clipboard.content,
            created_at=old_clipboard.updated_at,
        )
        db.add(history_entry)

    # 3. Upsert 当前文本（user_id 为主键，一人一条）；访问码列不在这里改
    updated_at = utcnow()
    new_version = current_version + 1
    stmt = mysql_insert(Clipboard).values(
        user_id=user_id,
        content=content,
        updated_at=updated_at,
        version=new_version,
    )
    stmt = stmt.on_duplicate_key_update(
        content=content,
        updated_at=updated_at,
        version=new_version,
    )
    await db.execute(stmt)

    # 4. 清理超出保留限制的历史记录
    result = await db.execute(
        select(func.count(ClipboardHistory.id)).where(
            ClipboardHistory.user_id == user_id
        )
    )
    total_count = result.scalar()

    if total_count > settings.HISTORY_KEEP:
        # 删除最旧的多余记录
        excess_count = total_count - settings.HISTORY_KEEP
        result = await db.execute(
            select(ClipboardHistory.id)
            .where(ClipboardHistory.user_id == user_id)
            # created_at 精度只到秒，同一秒可能有多条，加 id 保证删的确实是最旧的
            .order_by(ClipboardHistory.created_at.asc(), ClipboardHistory.id.asc())
            .limit(excess_count)
        )
        ids_to_delete = [row[0] for row in result.all()]

        if ids_to_delete:
            await db.execute(
                delete(ClipboardHistory).where(ClipboardHistory.id.in_(ids_to_delete))
            )

    await db.commit()

    # 5. 实时广播（只发信号，不带正文）：登录终端 + 凭剪切板访问码进入的快速访问页
    await manager.broadcast_to_user(
        user_id=user_id,
        message={
            "type": "clipboard_updated",
            "data": {"updated_at": updated_at.isoformat()},
        },
    )
    access_code = old_clipboard.access_code if old_clipboard else None
    await notify_quick_viewers(user_id, [access_code])

    return ClipboardResponse(
        content=content,
        updated_at=updated_at,
        version=new_version,
        access_code=access_code,
        access_expires_at=old_clipboard.access_expires_at if old_clipboard else None,
    )


def history_list_query(user_id: int):
    """
    某用户的历史列表查询（按时间倒序）；本人查看与超管只读查看共用。
    在数据库里算字节数与开头：长文本不把全文读进内存（OCTET_LENGTH 按字节计，LEFT 按字符截取）。
    """
    size = func.octet_length(ClipboardHistory.content)
    return (
        select(
            ClipboardHistory.id,
            case((size <= INLINE_CONTENT_BYTES, ClipboardHistory.content), else_=literal_column("NULL")).label("content"),
            func.left(ClipboardHistory.content, PREVIEW_CHARS).label("preview"),
            size.label("size"),
            ClipboardHistory.created_at,
        )
        .where(ClipboardHistory.user_id == user_id)
        .order_by(desc(ClipboardHistory.created_at), desc(ClipboardHistory.id))
    )


def rows_to_history_list(rows) -> ClipboardHistoryList:
    items = [ClipboardHistoryItem(**row._mapping) for row in rows]
    return ClipboardHistoryList(items=items, total=len(items))


def to_history_item(item: ClipboardHistory) -> ClipboardHistoryItem:
    """单条历史的全文"""
    return ClipboardHistoryItem(
        id=item.id,
        content=item.content,
        preview=item.content[:PREVIEW_CHARS],
        size=len(item.content.encode("utf-8")),
        created_at=item.created_at,
    )


@router.get("/history", response_model=ClipboardHistoryList)
async def get_clipboard_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户的文本历史版本列表（按时间倒序）。

    安全红线：查询强制按 user_id 过滤。
    """
    result = await db.execute(history_list_query(current_user.id))
    return rows_to_history_list(result.all())


@router.get("/history/{history_id}", response_model=ClipboardHistoryItem)
async def get_clipboard_history_item(
    history_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    读取某条历史的全文（列表里的长内容只有开头，点开时用这个接口取全文）。

    安全红线：校验 history_id 归属于当前用户，他人的与不存在的统一 404。
    """
    result = await db.execute(
        select(ClipboardHistory).where(
            ClipboardHistory.id == history_id,
            ClipboardHistory.user_id == current_user.id,  # 安全红线：归属校验
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="历史记录不存在或无权访问",
        )
    return to_history_item(item)


@router.post("/history/{history_id}/restore", response_model=ClipboardResponse)
async def restore_clipboard_history(
    history_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    恢复某个历史版本为当前文本，实时广播。

    安全红线：
    - 校验 history_id 归属于当前用户（防越权）
    - 恢复逻辑复用 write_clipboard 的归档与广播
    """
    result = await db.execute(
        select(ClipboardHistory).where(
            ClipboardHistory.id == history_id,
            ClipboardHistory.user_id == current_user.id,  # 安全红线：归属校验
        )
    )
    history_item = result.scalar_one_or_none()

    if not history_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="历史记录不存在或无权访问",
        )

    # 复用写入逻辑；被恢复的那条历史在同一事务里删除，避免恢复后历史重复
    return await write_clipboard(
        db, current_user.id, history_item.content, consumed_history_id=history_item.id
    )


@router.delete("/history/{history_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_clipboard_history(
    history_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    删除某条历史记录。

    安全红线：校验 history_id 归属于当前用户。
    """
    result = await db.execute(
        select(ClipboardHistory).where(
            ClipboardHistory.id == history_id,
            ClipboardHistory.user_id == current_user.id,
        )
    )
    history_item = result.scalar_one_or_none()

    if not history_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="历史记录不存在或无权访问",
        )

    await db.execute(
        delete(ClipboardHistory).where(ClipboardHistory.id == history_id)
    )
    await db.commit()

    # 其他终端打开着历史面板时据此重拉（只发信号）
    await manager.broadcast_to_user(
        user_id=current_user.id,
        message={"type": "clipboard_updated", "data": {}},
    )

    return None
