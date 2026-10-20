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


# 配额上限 1TB：远小于 BIGINT 上限，避免超大值写库越界导致 500
MAX_QUOTA_BYTES = 1024 ** 4


class UpdateUserQuota(BaseModel):
    """修改用户配额"""
    quota_bytes: int = Field(..., ge=0, le=MAX_QUOTA_BYTES, description="配额（字节，最大 1TB）")


class UpdateUserStatus(BaseModel):
    """修改用户状态"""
    is_active: bool


MAX_INVITE_BATCH = 20
MAX_INVITE_EXPIRY_IDS = 500


class InviteCodeCreate(BaseModel):
    """创建邀请码请求：一次生成 count 个，同一批共用一个过期时间"""
    count: int = Field(1, ge=1, le=MAX_INVITE_BATCH, description="生成数量（1–20）")
    expires_at: Optional[datetime] = Field(None, description="过期时间（可选，空为永久有效）")


class InviteCodeExpiryUpdate(BaseModel):
    """批量修改邀请码有效期请求"""
    ids: list[int] = Field(..., min_length=1, max_length=MAX_INVITE_EXPIRY_IDS, description="邀请码 id 列表")
    expires_at: Optional[datetime] = Field(None, description="新的过期时间（空为永久有效）")


class InviteCodeExpiryResult(BaseModel):
    """批量修改有效期结果"""
    updated: int
    expires_at: Optional[datetime]


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
    show_github_link: bool

    class Config:
        from_attributes = True


class UpdateSystemSettings(BaseModel):
    """更新系统设置"""
    default_quota_bytes: Optional[int] = Field(None, ge=0, le=MAX_QUOTA_BYTES, description="默认配额（字节，最大 1TB）")
    registration_enabled: Optional[bool] = Field(None, description="是否开放注册")
    show_github_link: Optional[bool] = Field(None, description="登录后侧栏是否显示 GitHub 链接")


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
