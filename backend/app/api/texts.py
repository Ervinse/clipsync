"""文本栏目路由：每人多条独立文本（新建 / 列表 / 读取 / 保存 / 删除）"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete, func, case, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, Text
from ..schemas import TextCreate, TextUpdate, TextResponse, TextSummary, TextListResponse
from ..core.deps import get_current_user
from ..core.ws_manager import manager
from ..core.quick_access import notify_quick_viewers, valid_code_filter
from ..core.timeutil import utcnow

router = APIRouter()

MAX_TEXTS_PER_USER = 200
# 列表里不超过这个字节数的文本直接带全文；更长的只给开头，打开时再取全文
INLINE_CONTENT_BYTES = 64 * 1024
PREVIEW_CHARS = 200

NOT_FOUND_DETAIL = "文本不存在或无权访问"
CONFLICT_DETAIL = "内容已在别处更新，请先载入最新内容"


def summary_query(*conditions):
    """
    列表查询：在数据库里算字节数与开头，长文本不把全文读进内存。
    OCTET_LENGTH 按字节计（与 8MB 上限的口径一致），LEFT 按字符截取。
    """
    size = func.octet_length(Text.content)
    return (
        select(
            Text.id, Text.title, Text.version,
            case((size <= INLINE_CONTENT_BYTES, Text.content), else_=literal_column("NULL")).label("content"),
            func.left(Text.content, PREVIEW_CHARS).label("preview"),
            size.label("size"),
            Text.access_code, Text.access_expires_at, Text.created_at, Text.updated_at,
        )
        .where(*conditions)
        # updated_at 精度只到秒，加 id 保证顺序稳定
        .order_by(Text.updated_at.desc(), Text.id.desc())
    )


def rows_to_summaries(rows) -> list[TextSummary]:
    return [TextSummary(**row._mapping) for row in rows]


def to_text_response(text: Text) -> TextResponse:
    return TextResponse(
        id=text.id,
        title=text.title,
        content=text.content,
        version=text.version,
        access_code=text.access_code,
        access_expires_at=text.access_expires_at,
        created_at=text.created_at,
        updated_at=text.updated_at,
    )


async def broadcast_texts_changed(user_id: int, text_id: int, codes: list[str | None]):
    """通知属主的登录终端与相关快速访问页（只发信号，不带正文）"""
    await manager.broadcast_to_user(user_id=user_id, message={"type": "texts_changed", "data": {"id": text_id}})
    await notify_quick_viewers(user_id, codes)


async def write_text(
    db: AsyncSession,
    user_id: int,
    text_id: int,
    data: TextUpdate,
    require_code: str | None = None,
) -> TextResponse:
    """
    保存一条文本：登录编辑与快速访问共用。

    安全红线：按 (id, user_id) 定位，只能改属主自己的文本；require_code 为快速访问时的访问码，
    加锁读取时一并校验文本仍挂着这个码且未过期，否则按不存在处理。
    base_version 与当前版本不一致返回 409，不覆盖别处的修改。
    """
    # 先结束鉴权读视图（MySQL 默认 REPEATABLE READ），加锁读到的才是最新版本
    await db.commit()
    conditions = [Text.id == text_id, Text.user_id == user_id]
    if require_code is not None:
        conditions = [Text.id == text_id, *valid_code_filter(Text, user_id, require_code)]
    result = await db.execute(select(Text).where(*conditions).with_for_update())
    text = result.scalar_one_or_none()
    if text is None:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if data.base_version is not None and data.base_version != text.version:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CONFLICT_DETAIL)

    if data.title is not None:
        text.title = data.title
    if data.content is not None:
        text.content = data.content
    text.version += 1
    text.updated_at = utcnow()
    await db.commit()

    await broadcast_texts_changed(user_id, text.id, [text.access_code])
    return to_text_response(text)


@router.get("", response_model=TextListResponse)
async def list_texts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出自己的全部文本（安全红线：强制按 user_id 过滤）"""
    result = await db.execute(summary_query(Text.user_id == current_user.id))
    items = rows_to_summaries(result.all())
    return TextListResponse(items=items, total=len(items), max_texts=MAX_TEXTS_PER_USER)


@router.post("", response_model=TextResponse, status_code=status.HTTP_201_CREATED)
async def create_text(
    data: TextCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新建文本；每人最多 MAX_TEXTS_PER_USER 条"""
    # 锁住用户行再数：并发新建时不会都通过数量检查而超出上限
    await db.commit()
    await db.execute(select(User.id).where(User.id == current_user.id).with_for_update())
    result = await db.execute(select(func.count(Text.id)).where(Text.user_id == current_user.id))
    if result.scalar() >= MAX_TEXTS_PER_USER:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"最多只能有 {MAX_TEXTS_PER_USER} 条文本，请先删除不需要的",
        )

    now = utcnow()
    text = Text(
        user_id=current_user.id,
        title=data.title,
        content=data.content,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(text)
    await db.commit()

    # 新文本没有访问码，只通知登录终端
    await manager.broadcast_to_user(
        user_id=current_user.id, message={"type": "texts_changed", "data": {"id": text.id}}
    )
    return to_text_response(text)


@router.get("/{text_id}", response_model=TextResponse)
async def get_text(
    text_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """读取一条文本的全文（安全红线：归属校验，他人文本与不存在统一 404）"""
    result = await db.execute(select(Text).where(Text.id == text_id, Text.user_id == current_user.id))
    text = result.scalar_one_or_none()
    if text is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return to_text_response(text)


@router.put("/{text_id}", response_model=TextResponse)
async def update_text(
    text_id: int,
    data: TextUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """保存标题与内容；带 base_version 时做冲突检测"""
    return await write_text(db, current_user.id, text_id, data)


@router.delete("/{text_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_text(
    text_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除文本，它的访问码随之消失（安全红线：仅归属者）"""
    result = await db.execute(select(Text).where(Text.id == text_id, Text.user_id == current_user.id))
    text = result.scalar_one_or_none()
    if text is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)

    await db.execute(delete(Text).where(Text.id == text_id, Text.user_id == current_user.id))
    await db.commit()

    if text.access_code:
        await manager.broadcast_to_user(
            user_id=current_user.id, message={"type": "access_codes_changed", "data": {}}
        )
    await broadcast_texts_changed(current_user.id, text_id, [text.access_code])
    return None
