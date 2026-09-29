"""剪贴板相关 Pydantic 模型"""
from datetime import datetime
from pydantic import BaseModel, Field


class ClipboardUpdate(BaseModel):
    """更新当前文本请求"""
    content: str = Field(..., max_length=16777215, description="文本内容（最大 16MB）")


class ClipboardResponse(BaseModel):
    """当前文本响应"""
    content: str
    updated_at: datetime

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
