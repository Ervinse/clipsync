"""文件相关 Pydantic 模型"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from ..core.http_utils import sanitize_filename


class UploadInitRequest(BaseModel):
    """初始化分片上传请求"""
    original_name: str = Field(..., min_length=1, max_length=255, description="原始文件名")
    total_size: int = Field(..., gt=0, description="文件总大小（字节）")
    chunk_size: int = Field(..., gt=0, description="每个分片大小（字节），不得超过服务端 CHUNK_SIZE")

    @field_validator("original_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        # 文件名只作展示与下载名，入库前去掉控制字符与路径分隔符
        return sanitize_filename(value)


class UploadInitResponse(BaseModel):
    """初始化分片上传响应"""
    upload_id: str = Field(..., description="上传会话 ID")
    total_chunks: int = Field(..., description="分片总数")
    chunk_size: int = Field(..., description="服务端确认的分片大小")


class UploadChunkRequest(BaseModel):
    """上传单个分片请求（multipart/form-data）"""
    upload_id: str
    chunk_index: int = Field(..., ge=0, description="分片索引（从 0 开始）")
    # chunk_data: 实际文件数据通过 UploadFile 接收


class UploadCompleteRequest(BaseModel):
    """完成上传请求"""
    upload_id: str = Field(..., min_length=36, max_length=36)


class FileResponse(BaseModel):
    """文件元数据响应"""
    id: int
    original_name: str
    size: int
    mime_type: str
    created_at: datetime
    access_code: Optional[str] = None
    access_expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FileListResponse(BaseModel):
    """文件列表响应"""
    items: list[FileResponse]
    total: int
    used_bytes: int  # 当前用户已用空间
    reserved_bytes: int  # 进行中上传会话占用的配额
    quota_bytes: int  # 配额
