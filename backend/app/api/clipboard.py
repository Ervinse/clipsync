"""剪贴板路由：当前文本 + 历史版本管理"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, insert, delete, desc, func
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
from ..core.timeutil import utcnow
from ..config import settings

router = APIRouter()


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
    clipboard = result.scalar_one_or_none()

    if not clipboard:
        # 用户首次使用，返回空内容
        return ClipboardResponse(
            content="",
            updated_at=utcnow(),
        )

    return ClipboardResponse(
        content=clipboard.content,
        updated_at=clipboard.updated_at,
    )


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
    return await _write_clipboard(db, current_user, data.content)


async def _write_clipboard(
    db: AsyncSession,
    current_user: User,
    content: str,
    consumed_history_id: int | None = None,
) -> ClipboardResponse:
    """
    写入当前文本：归档旧内容 + upsert + 清理超额历史 + 广播。

    consumed_history_id：restore 时传入，被恢复的那条历史在同一事务里删除，避免重复。
    """
    # 0. 锁住当前用户行，同一用户的剪贴板写操作串行化，防止并发时重复归档、丢失中间版本。
    #    不锁 Clipboard 行：首次写入时该行不存在，会退化为 gap lock，两个 INSERT 容易死锁。
    await db.execute(select(User.id).where(User.id == current_user.id).with_for_update())

    # 1. 查询当前文本
    result = await db.execute(
        select(Clipboard).where(Clipboard.user_id == current_user.id)
    )
    old_clipboard = result.scalar_one_or_none()

    if consumed_history_id is not None:
        await db.execute(
            delete(ClipboardHistory).where(
                ClipboardHistory.id == consumed_history_id,
                ClipboardHistory.user_id == current_user.id,
            )
        )

    # 2. 旧内容非空且与新内容不同才归档（保存相同内容不产生重复历史）
    if old_clipboard and old_clipboard.content and old_clipboard.content != content:
        history_entry = ClipboardHistory(
            user_id=current_user.id,
            content=old_clipboard.content,
            created_at=old_clipboard.updated_at,
        )
        db.add(history_entry)

    # 3. Upsert 当前文本（user_id 为主键，一人一条）
    updated_at = utcnow()
    stmt = mysql_insert(Clipboard).values(
        user_id=current_user.id,
        content=content,
        updated_at=updated_at,
    )
    stmt = stmt.on_duplicate_key_update(
        content=content,
        updated_at=updated_at,
    )
    await db.execute(stmt)

    # 4. 清理超出保留限制的历史记录
    # 查询该用户历史记录总数
    result = await db.execute(
        select(func.count(ClipboardHistory.id)).where(
            ClipboardHistory.user_id == current_user.id
        )
    )
    total_count = result.scalar()

    if total_count > settings.HISTORY_KEEP:
        # 删除最旧的多余记录
        excess_count = total_count - settings.HISTORY_KEEP
        # 查询最旧的 excess_count 条记录的 ID
        result = await db.execute(
            select(ClipboardHistory.id)
            .where(ClipboardHistory.user_id == current_user.id)
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

    # 5. 实时广播（只发信号，不带正文）
    await manager.broadcast_to_user(
        user_id=current_user.id,
        message={
            "type": "clipboard_updated",
            "data": {"updated_at": updated_at.isoformat()},
        },
    )

    return ClipboardResponse(
        content=content,
        updated_at=updated_at,
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
    # 查询历史记录
    result = await db.execute(
        select(ClipboardHistory)
        .where(ClipboardHistory.user_id == current_user.id)
        .order_by(desc(ClipboardHistory.created_at), desc(ClipboardHistory.id))
    )
    history_items = result.scalars().all()

    return ClipboardHistoryList(
        items=[
            ClipboardHistoryItem(
                id=item.id,
                content=item.content,
                created_at=item.created_at,
            )
            for item in history_items
        ],
        total=len(history_items),
    )


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
    - 恢复逻辑复用 update_clipboard 的归档与广播
    """
    # 1. 查询历史记录，校验归属
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

    # 2. 复用写入逻辑；被恢复的那条历史在同一事务里删除，避免恢复后历史重复
    return await _write_clipboard(
        db, current_user, history_item.content, consumed_history_id=history_item.id
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
    # 校验归属
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

    return None
