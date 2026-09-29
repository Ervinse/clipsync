"""FastAPI 应用入口"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings
from .rate_limit import limiter
from .api import auth

app = FastAPI(
    title="ClipSync API",
    version="0.1.0",
    description="跨终端剪贴板与文件同步服务",
)

# 限流器配置
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS_LIST,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """健康检查"""
    return {"status": "ok", "service": "ClipSync"}


# 挂载路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])

# 后续阶段继续挂载：
# from .api import clipboard, files, access, admin, ws
# app.include_router(clipboard.router, prefix="/api/clipboard", tags=["文本"])
# ...
