"""文本栏目相关 Pydantic 模型"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .clipboard import check_content_bytes

MAX_TITLE_CHARS = 100


class TextCreate(BaseModel):
    """新建文本（标题可以不填）"""
    title: str = Field("", max_length=MAX_TITLE_CHARS, description="标题（可选，最多 100 字）")
    content: str = Field("", description="文本内容（UTF-8 编码后最大 4MB）")

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value):
        # before：先去首尾空格再校验长度
        return value.strip() if isinstance(value, str) else value

    @field_validator("content")
    @classmethod
    def _content_bytes(cls, value: str) -> str:
        return check_content_bytes(value)


class TextUpdate(BaseModel):
    """保存文本：title / content 省略时保持原值"""
    title: Optional[str] = Field(None, max_length=MAX_TITLE_CHARS, description="标题（最多 100 字）；省略表示不修改")
    content: Optional[str] = Field(None, description="文本内容（UTF-8 编码后最大 4MB）；省略表示不修改")
    base_version: Optional[int] = Field(
        None, ge=0, description="读取时的版本号；与服务端当前版本不一致返回 409。省略表示直接覆盖"
    )

    @field_validator("title", mode="before")
    @classmethod
    def _strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("content")
    @classmethod
    def _content_bytes(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else check_content_bytes(value)


class TextResponse(BaseModel):
    """单条文本（含全文）"""
    id: int
    title: str
    content: str
    version: int
    access_code: Optional[str]
    access_expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class TextSummary(BaseModel):
    """
    列表项：较短的文本直接带全文（content），较长的 content 为 null，只给开头（preview），
    需要时再按 id 取全文，避免一次传输大量内容。size 为 UTF-8 字节数。
    """
    id: int
    title: str
    version: int
    content: Optional[str]
    preview: str
    size: int
    access_code: Optional[str]
    access_expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class TextListResponse(BaseModel):
    items: list[TextSummary]
    total: int
    max_texts: int  # 每人最多可以有多少条
