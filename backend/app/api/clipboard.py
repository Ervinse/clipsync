"""剪贴板路由：当前文本 + 历史版本管理"""
from datetime import datetime

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
            updated_at=datetime.utcnow(),
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
    # 1. 查询当前文本
    result = await db.execute(
        select(Clipboard).where(Clipboard.user_id == current_user.id)
    )
    old_clipboard = result.scalar_one_or_none()

    # 2. 如果有旧内容，归档到历史
    if old_clipboard and old_clipboard.content:
        history_entry = ClipboardHistory(
            user_id=current_user.id,
            content=old_clipboard.content,
            created_at=old_clipboard.updated_at,
        )
        db.add(history_entry)

    # 3. Upsert 当前文本
    stmt = mysql_insert(Clipboard).values(
        user_id=current_user.id,
        content=data.content,
        updated_at=datetime.utcnow(),
    )
    stmt = stmt.on_duplicate_key_update(
        content=data.content,
        updated_at=datetime.utcnow(),
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
            .order_by(ClipboardHistory.created_at.asc())
            .limit(excess_count)
        )
        ids_to_delete = [row[0] for row in result.all()]

        if ids_to_delete:
            await db.execute(
                delete(ClipboardHistory).where(ClipboardHistory.id.in_(ids_to_delete))
            )

    await db.commit()

    # 5. 实时广播（排除当前连接，WebSocket 实现时传入）
    updated_at = datetime.utcnow()
    await manager.broadcast_to_user(
        user_id=current_user.id,
        message={
            "type": "clipboard_updated",
            "data": {"updated_at": updated_at.isoformat()},
        },
    )

    return ClipboardResponse(
        content=data.content,
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
        .order_by(desc(ClipboardHistory.created_at))
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

    # 2. 复用更新逻辑（将历史内容设为当前）
    return await update_clipboard(
        data=ClipboardUpdate(content=history_item.content),
        current_user=current_user,
        db=db,
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
