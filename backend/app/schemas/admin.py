"""管理后台相关 Pydantic 模型"""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

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


class UpdateUserRole(BaseModel):
    """修改用户角色：只能在普通用户与管理员之间切换，超级管理员只能用 scripts/create_superadmin.py 创建"""
    role: Literal["user", "admin"]


MAX_INVITE_BATCH = 20
MAX_INVITE_EXPIRY_IDS = 500
MAX_INVITE_NOTE_CHARS = 100


class InviteBatchCreate(BaseModel):
    """生成一批邀请码：一次生成 count 个，同一批共用一个过期时间和备注"""
    count: int = Field(1, ge=1, le=MAX_INVITE_BATCH, description="生成数量（1–20）")
    expires_at: Optional[datetime] = Field(None, description="过期时间（可选，空为永久有效）")
    note: str = Field("", max_length=MAX_INVITE_NOTE_CHARS, description="备注（可选，最多 100 字）")

    @field_validator("note", mode="before")
    @classmethod
    def _strip_note(cls, value):
        # before：先去首尾空格再校验长度，正文正好上限、前后带空格的备注不会被误拒
        return value.strip() if isinstance(value, str) else value


class InviteBatchNoteUpdate(BaseModel):
    """修改批次备注（空字符串表示清空）"""
    note: str = Field(..., max_length=MAX_INVITE_NOTE_CHARS, description="备注（最多 100 字）")

    @field_validator("note", mode="before")
    @classmethod
    def _strip_note(cls, value):
        # before：先去首尾空格再校验长度，正文正好上限、前后带空格的备注不会被误拒
        return value.strip() if isinstance(value, str) else value


class InviteCodeExpiryUpdate(BaseModel):
    """批量修改邀请码有效期请求"""
    ids: list[int] = Field(..., min_length=1, max_length=MAX_INVITE_EXPIRY_IDS, description="邀请码 id 列表")
    expires_at: Optional[datetime] = Field(None, description="新的过期时间（空为永久有效）")


class InviteCodeExpiryResult(BaseModel):
    """批量修改有效期结果"""
    updated: int
    expires_at: Optional[datetime]


class InviteCodeResponse(BaseModel):
    """批次里的一个邀请码；创建人与创建时间见所属批次"""
    id: int
    code: str
    used_by: Optional[int]
    used_by_username: Optional[str]
    expires_at: Optional[datetime]
    used_at: Optional[datetime]


class InviteBatchResponse(BaseModel):
    """一批邀请码：codes 按生成顺序排列"""
    id: int
    note: str
    created_by: int
    created_by_username: str
    created_at: datetime
    codes: list[InviteCodeResponse]


class InviteBatchListResponse(BaseModel):
    """批次列表响应：按创建时间倒序"""
    items: list[InviteBatchResponse]
    total: int


class InviteBatchDeleteResult(BaseModel):
    """删除批次里未使用的码：deleted 为删掉的个数；批次里不剩码时批次一起删除"""
    deleted: int
    batch_deleted: bool


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


MAX_DEPLOYMENT_NOTE_CHARS = 200


class DeploymentResponse(BaseModel):
    """一条部署记录；app_version 为空表示没走 Docker 部署（开发环境）"""
    id: int
    app_version: str
    commit_sha: str
    branch: str
    built_at: Optional[datetime]
    deployed_at: datetime
    note: str

    class Config:
        from_attributes = True


class DeployInfoResponse(BaseModel):
    """
    正在运行的版本与部署记录。
    app_version / commit_sha / branch / built_at 是运行中进程的信息；current 是对应的部署记录（登记失败时为空）；
    started_at 为本次启动时间，uptime_seconds 为已运行秒数；history 为最近的部署记录，按时间倒序
    """
    app_version: str
    commit_sha: str
    branch: str
    built_at: Optional[datetime]
    started_at: datetime
    uptime_seconds: int
    current: Optional[DeploymentResponse]
    history: list[DeploymentResponse]
    total: int


class DeploymentNoteUpdate(BaseModel):
    """修改部署备注（仅超管）；空字符串表示清除"""
    note: str = Field(..., max_length=MAX_DEPLOYMENT_NOTE_CHARS, description="备注（最多 200 字）")

    @field_validator("note", mode="before")
    @classmethod
    def _strip_note(cls, value):
        # before：先去首尾空格再校验长度，正文正好上限、前后带空格的备注不会被误拒
        return value.strip() if isinstance(value, str) else value


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
