"""用户相关 Pydantic 模型"""
from datetime import datetime
from pydantic import BaseModel, Field

from ..models import UserRole


class UserCreate(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=3, max_length=64, description="用户名")
    password: str = Field(..., min_length=6, description="密码")
    invite_code: str = Field(..., description="邀请码")


class UserLogin(BaseModel):
    """登录请求"""
    username: str
    password: str


class Token(BaseModel):
    """JWT 令牌响应"""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """用户基本信息响应"""
    id: int
    username: str
    role: UserRole
    quota_bytes: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserWithStats(UserResponse):
    """用户信息 + 存储统计"""
    used_bytes: int  # 已用空间（需要业务层计算）
