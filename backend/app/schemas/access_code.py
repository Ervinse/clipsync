"""快速访问码相关 Pydantic 模型"""
import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from ..core.quick_access import normalize_access_code
from .text import TextSummary


class AccessTargetType(str, enum.Enum):
    """可以设置访问码的内容"""
    CLIPBOARD = "clipboard"
    TEXT = "text"
    FILE = "file"


class AccessCodeSet(BaseModel):
    """给某样内容设置 / 修改 / 清除访问码（code 为 null 表示清除）"""
    target_type: AccessTargetType
    target_id: Optional[int] = Field(None, description="文本或文件的 id；云剪切板不需要")
    code: Optional[str] = Field(None, max_length=64, description="访问码，4–32 位字母、数字与 _ - .，不区分大小写")
    expires_at: Optional[datetime] = Field(None, description="过期时间（可选）")

    @field_validator("code")
    @classmethod
    def _normalize(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else normalize_access_code(value)


class AccessCodeTarget(BaseModel):
    """一样挂着访问码的内容；label 为文本标题（无标题时取内容开头）或文件名，云剪切板为空"""
    target_type: AccessTargetType
    target_id: Optional[int]
    label: str
    access_code: Optional[str]
    access_expires_at: Optional[datetime]


class AccessCodeGroup(BaseModel):
    code: str
    items: list[AccessCodeTarget]


class AccessCodeOverview(BaseModel):
    """按访问码分组的总览；完整访问码为 username@code"""
    username: str
    groups: list[AccessCodeGroup]
    total: int


# ---------- 快速访问（凭完整访问码进入） ----------


class QuickLoginRequest(BaseModel):
    full_code: str = Field(..., min_length=1, max_length=200, description="用户名@访问码")


class QuickLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    owner_username: str
    code: str
    expires_in: int  # 凭证有效秒数


class QuickClipboardSummary(BaseModel):
    """快速访问里的云剪切板：字段含义同 TextSummary"""
    version: int
    content: Optional[str]
    preview: str
    size: int
    updated_at: datetime
    access_expires_at: Optional[datetime]


class QuickFileItem(BaseModel):
    id: int
    original_name: str
    size: int
    mime_type: str
    created_at: datetime
    access_expires_at: Optional[datetime]


class QuickItemsResponse(BaseModel):
    owner_username: str
    code: str
    clipboard: Optional[QuickClipboardSummary]
    texts: list[TextSummary]
    files: list[QuickFileItem]
