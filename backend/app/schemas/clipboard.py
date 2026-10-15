"""剪贴板相关 Pydantic 模型"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# 文本上限 8MB，按 UTF-8 字节算（多字节字符按字符数校验会放过超长内容）。
# 必须小于 Nginx 的 client_max_body_size（10m）：请求体还含 JSON 外壳与转义，超过 Nginx 上限的请求到不了后端。
# 数据库列 MEDIUMTEXT 的容量是 16MB，这里留有余量。云剪切板与文本栏目共用这个上限。
MAX_CONTENT_BYTES = 8 * 1024 * 1024


def check_content_bytes(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise ValueError("文本内容不能超过 8MB（按 UTF-8 字节计）")
    return value


class ClipboardUpdate(BaseModel):
    """更新当前文本请求"""
    content: str = Field(..., description="文本内容（UTF-8 编码后最大 8MB）")
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
    """文本历史版本"""
    id: int
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ClipboardHistoryList(BaseModel):
    """文本历史列表响应"""
    items: list[ClipboardHistoryItem]
    total: int
