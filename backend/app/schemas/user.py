"""用户相关 Pydantic 模型"""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from ..models import UserRole

# 用户名只能含字母、数字与 _ . -：快速访问码「用户名@访问码」按 @ 拆分，用户名里不能出现 @。
# 注册接口与 scripts/create_superadmin.py 共用这条规则
USERNAME_PATTERN = r"^[A-Za-z0-9_.\-]+$"


class UserCreate(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=3, max_length=64, pattern=USERNAME_PATTERN, description="用户名")
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
    """用户信息 + 存储统计 + 前端需要的站点级显示开关"""
    used_bytes: int  # 已用空间（需要业务层计算）
    reserved_bytes: int  # 进行中上传会话占用的配额
    show_github_link: bool  # 系统设置：侧栏是否显示 GitHub 链接（普通用户读不了后台设置接口，随 /auth/me 下发）
