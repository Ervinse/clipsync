"""剪贴板相关 Pydantic 模型"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# 文本上限 4MB，按 UTF-8 字节算（多字节字符按字符数校验会放过超长内容）。
# 请求体是 JSON：换行、制表符、引号、反斜杠转义后占 2 字节，所以 4MB 的文本最多约 8MB，
# 仍小于 Nginx 的 client_max_body_size（10m），超限时由后端返回中文提示而不是 Nginx 的 413 页面。
# 数据库列 MEDIUMTEXT 的容量是 16MB，这里留有余量。云剪切板与文本栏目共用这个上限。
MAX_CONTENT_BYTES = 4 * 1024 * 1024


def check_content_bytes(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise ValueError("文本内容不能超过 4MB（按 UTF-8 字节计）")
    return value


class ClipboardUpdate(BaseModel):
    """更新当前文本请求"""
    content: str = Field(..., description="文本内容（UTF-8 编码后最大 4MB）")
    base_version: Optional[int] = Field(
        None, ge=0, description="读取时的版本号；与服务端当前版本不一致返回 409。省略表示直接覆盖"
    )

    @field_validator("content")
    @classmethod
    def _content_bytes(cls, value: str) -> str:
        return check_content_bytes(value)


class ClipboardResponse(BaseModel):
    """当前文本响应（version 为 0 表示还没有保存过）"""
    content: str
    updated_at: datetime
    version: int
    access_code: Optional[str] = None
    access_expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClipboardHistoryItem(BaseModel):
    """
    文本历史版本。列表里较短的内容直接带全文（content），较长的 content 为 null，只给开头（preview），
    需要时再按 id 取全文（GET /api/clipboard/history/{id}），避免一次传输最多 HISTORY_KEEP × 4MB 的内容。
    size 为 UTF-8 字节数。
    """
    id: int
    content: Optional[str]
    preview: str
    size: int
    created_at: datetime


class ClipboardHistoryList(BaseModel):
    """文本历史列表响应"""
    items: list[ClipboardHistoryItem]
    total: int
