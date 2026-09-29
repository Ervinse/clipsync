"""文件相关 Pydantic 模型"""
from datetime import datetime
from pydantic import BaseModel, Field


class UploadInitRequest(BaseModel):
    """初始化分片上传请求"""
    original_name: str = Field(..., max_length=255, description="原始文件名")
    total_size: int = Field(..., gt=0, description="文件总大小（字节）")
    chunk_size: int = Field(..., gt=0, description="每个分片大小（字节）")


class UploadInitResponse(BaseModel):
    """初始化分片上传响应"""
    upload_id: str = Field(..., description="上传会话 ID")
    total_chunks: int = Field(..., description="分片总数")


class UploadChunkRequest(BaseModel):
    """上传单个分片请求（multipart/form-data）"""
    upload_id: str
    chunk_index: int = Field(..., ge=0, description="分片索引（从 0 开始）")
    # chunk_data: 实际文件数据通过 UploadFile 接收


class UploadCompleteRequest(BaseModel):
    """完成上传请求"""
    upload_id: str


class FileResponse(BaseModel):
    """文件元数据响应"""
    id: int
    original_name: str
    size: int
    mime_type: str
    created_at: datetime

    class Config:
        from_attributes = True


class FileListResponse(BaseModel):
    """文件列表响应"""
    items: list[FileResponse]
    total: int
    used_bytes: int  # 当前用户已用空间
    quota_bytes: int  # 配额
