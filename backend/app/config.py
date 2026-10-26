"""应用配置：读取 .env 环境变量"""
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings

# 示例 / 占位密钥中常见的片段，命中即视为未替换
_PLACEHOLDER_MARKERS = ("change_this", "changeme", "change-me", "your_", "secret_key_here", "example")
# 单个上传分片的上限：Nginx 的 client_max_body_size 是 10MB，留出 multipart 头和余量
MAX_CHUNK_SIZE = 8 * 1024 * 1024
# 密钥里至少要有这么多种不同字符；`openssl rand -hex 32` 生成的串几乎必然远超此值，32 个同一字符之类的低熵串过不了
_MIN_DISTINCT_CHARS = 10


class Settings(BaseSettings):
    # 数据库
    DB_HOST: str
    DB_PORT: int = 3306
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    # JWT
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 10080  # 7 天

    # 部署
    HSTS_ENABLED: bool = False
    CORS_ORIGINS: str = "http://localhost:5173"
    # 运行的版本号：Docker 部署由 compose 从 .env 的 CLIPSYNC_TAG 传入（版本号、提交号或 latest）；开发环境留空
    APP_VERSION: str = ""

    # 存储
    STORAGE_DIR: str = "./storage"
    DEFAULT_QUOTA_BYTES: int = 104857600  # 100MB
    MAX_FILE_BYTES: int = 524288000  # 500MB
    CHUNK_SIZE: int = 5242880  # 5MB，同时是单分片允许的最大字节数；不能超过 MAX_CHUNK_SIZE（8MB）
    MAX_UPLOAD_SESSIONS_PER_USER: int = 5  # 单用户同时进行中的上传会话上限

    # 其他
    HISTORY_KEEP: int = 50
    UPLOAD_SESSION_TTL_HOURS: int = 24

    @field_validator("JWT_SECRET")
    @classmethod
    def _check_jwt_secret(cls, value: str) -> str:
        # 安全红线：弱密钥 / 示例密钥可被用来伪造任意用户（含 superadmin）的 token，直接拒绝启动
        lowered = value.lower()
        if (
            len(value) < 32
            or len(set(value)) < _MIN_DISTINCT_CHARS
            or any(marker in lowered for marker in _PLACEHOLDER_MARKERS)
        ):
            raise ValueError(
                "JWT_SECRET 过弱或仍是示例值，请用 `openssl rand -hex 32` 生成随机串后写入 .env"
            )
        return value

    @field_validator("CHUNK_SIZE")
    @classmethod
    def _check_chunk_size(cls, value: int) -> int:
        # 一个分片就是一个请求体，还要加上 multipart 的头；超过 Nginx 的 client_max_body_size（10MB）会在 Nginx 被 413 拒绝
        if not 0 < value <= MAX_CHUNK_SIZE:
            raise ValueError(
                f"CHUNK_SIZE 必须在 1 到 {MAX_CHUNK_SIZE}（{MAX_CHUNK_SIZE // (1024 * 1024)}MB）字节之间："
                "分片加上请求头不能超过 Nginx 的 client_max_body_size（10MB）"
            )
        return value

    @field_validator("JWT_ALGORITHM")
    @classmethod
    def _check_jwt_algorithm(cls, value: str) -> str:
        # 只允许 HMAC 对称算法，避免误配成 none 或非对称算法导致验签被绕过
        if value not in ("HS256", "HS384", "HS512"):
            raise ValueError("JWT_ALGORITHM 仅支持 HS256 / HS384 / HS512")
        return value

    @property
    def DATABASE_URL(self) -> str:
        # URL 编码密码中的特殊字符
        password_encoded = quote_plus(self.DB_PASSWORD)
        return f"mysql+aiomysql://{self.DB_USER}:{password_encoded}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def CORS_ORIGINS_LIST(self) -> list[str]:
        # 安全红线：CORS 只允许显式白名单，忽略通配符
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
        return [origin for origin in origins if origin and origin != "*"]

    class Config:
        env_file = ".env"


settings = Settings()
