"""应用配置：读取 .env 环境变量"""
from urllib.parse import quote_plus
from pydantic_settings import BaseSettings


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
    DEPLOY_SCHEME: str = "http"
    COOKIE_SECURE: bool = False
    HSTS_ENABLED: bool = False
    CORS_ORIGINS: str = "http://localhost:5173"

    # 存储
    STORAGE_DIR: str = "./storage"
    DEFAULT_QUOTA_BYTES: int = 104857600  # 100MB
    MAX_FILE_BYTES: int = 524288000  # 500MB
    CHUNK_SIZE: int = 5242880  # 5MB

    # 其他
    HISTORY_KEEP: int = 50
    UPLOAD_SESSION_TTL_HOURS: int = 24

    @property
    def DATABASE_URL(self) -> str:
        # URL 编码密码中的特殊字符
        password_encoded = quote_plus(self.DB_PASSWORD)
        return f"mysql+aiomysql://{self.DB_USER}:{password_encoded}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def CORS_ORIGINS_LIST(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"


settings = Settings()
