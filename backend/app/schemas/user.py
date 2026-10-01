"""用户相关 Pydantic 模型"""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from ..models import UserRole


class UserCreate(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$", description="用户名")
    password: str = Field(..., min_length=8, max_length=72, description="密码")
    invite_code: str = Field(..., min_length=1, max_length=32, description="邀请码")

    @field_validator("password")
    @classmethod
    def _password_bytes(cls, value: str) -> str:
        # bcrypt 只处理前 72 字节，多字节字符需按字节计算
        if len(value.encode("utf-8")) > 72:
            raise ValueError("密码不能超过 72 字节")
        return value


class UserLogin(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class Token(BaseModel):
    """JWT 令牌响应"""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """用户基本信息响应（不含 password_hash）"""
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
