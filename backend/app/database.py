"""数据库连接：异步 engine 与 session 工厂"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from .config import settings

# 异步引擎
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=False,  # aiomysql 0.3.x 与 SQLAlchemy 的 ping 兼容性问题，暂时禁用
    pool_recycle=3600,
)

# 异步 session 工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ORM 基类
Base = declarative_base()


async def get_db() -> AsyncSession:
    """依赖注入：提供 DB session"""
    async with AsyncSessionLocal() as session:
        yield session
