"""管理后台相关 Pydantic 模型"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from ..models import UserRole


class SystemStats(BaseModel):
    """系统统计数据"""
    total_users: int
    active_users: int
    total_files: int
    total_storage_bytes: int
    total_access_codes: int
    active_access_codes: int


class AdminUserListItem(BaseModel):
    """用户列表项（管理员视图）"""
    id: int
    username: str
    role: UserRole
    is_active: bool
    quota_bytes: int
    used_bytes: int
    file_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class AdminUserListResponse(BaseModel):
    """用户列表响应"""
    items: list[AdminUserListItem]
    total: int


class AdminUserDetail(BaseModel):
    """用户详情（管理员视图，仅元数据）"""
    id: int
    username: str
    role: UserRole
    is_active: bool
    quota_bytes: int
    used_bytes: int
    file_count: int
    clipboard_updated_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class UpdateUserQuota(BaseModel):
    """修改用户配额"""
    quota_bytes: int = Field(..., ge=0, description="配额（字节）")


class UpdateUserStatus(BaseModel):
    """修改用户状态"""
    is_active: bool


class InviteCodeCreate(BaseModel):
    """创建邀请码请求"""
    expires_at: Optional[datetime] = Field(None, description="过期时间（可选）")


class InviteCodeResponse(BaseModel):
    """邀请码响应"""
    id: int
    code: str
    created_by: int
    created_by_username: str
    used_by: Optional[int]
    used_by_username: Optional[str]
    expires_at: Optional[datetime]
    used_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class InviteCodeListResponse(BaseModel):
    """邀请码列表响应"""
    items: list[InviteCodeResponse]
    total: int


class SystemSettingsResponse(BaseModel):
    """系统设置响应"""
    default_quota_bytes: int
    registration_enabled: bool

    class Config:
        from_attributes = True


class UpdateSystemSettings(BaseModel):
    """更新系统设置"""
    default_quota_bytes: Optional[int] = Field(None, ge=0, description="默认配额（字节）")
    registration_enabled: Optional[bool] = Field(None, description="是否开放注册")


class AdminFileListItem(BaseModel):
    """文件列表项（管理员视图，仅元数据）"""
    id: int
    user_id: int
    username: str
    original_name: str
    size: int
    mime_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class AdminFileListResponse(BaseModel):
    """文件列表响应（管理员视图）"""
    items: list[AdminFileListItem]
    total: int
