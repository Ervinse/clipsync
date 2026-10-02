"""访问码相关 Pydantic 模型"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from ..models import AccessCodeTargetType


class AccessCodeCreate(BaseModel):
    """创建访问码请求"""
    target_type: AccessCodeTargetType = Field(..., description="目标类型：text 或 file")
    file_id: Optional[int] = Field(None, description="文件 ID（文件码必填）")
    expires_at: Optional[datetime] = Field(None, description="过期时间（可选）")


class AccessCodeResponse(BaseModel):
    """访问码响应"""
    id: int
    code: str
    target_type: AccessCodeTargetType
    file_id: Optional[int]
    expires_at: Optional[datetime]
    is_revoked: bool
    created_at: datetime
    access_url: str  # 完整访问 URL（由后端动态拼接）

    class Config:
        from_attributes = True


class AccessCodeListResponse(BaseModel):
    """访问码列表响应"""
    items: list[AccessCodeResponse]
    total: int


class AccessTextResponse(BaseModel):
    """文本访问码解析响应"""
    content: str
    updated_at: datetime
    owner_username: str
