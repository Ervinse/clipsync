"""数据库连接与会话管理"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    # 不用 pool_pre_ping：SQLAlchemy 2.0.36 + aiomysql 0.3.2 下 do_ping 调用 ping() 缺 reconnect 参数，
    # 每次取连接都会抛 TypeError。改由 pool_recycle（远小于 MySQL 默认 wait_timeout 8 小时）回收旧连接
    pool_recycle=3600,
    # 会话时区固定 UTC：server_default=now() 与代码里的 utcnow() 口径一致，过期判断才可靠
    connect_args={"init_command": "SET time_zone = '+00:00'"},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """请求级会话：由各接口显式 commit；异常时回滚未提交的改动"""
    async with AsyncSessionLocal() as db:
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
