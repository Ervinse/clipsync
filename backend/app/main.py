"""FastAPI 应用入口"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings
from .rate_limit import limiter
from .api import auth, clipboard, files, ws, access

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
app.include_router(clipboard.router, prefix="/api/clipboard", tags=["文本"])
app.include_router(files.router, prefix="/api/files", tags=["文件"])
app.include_router(access.router, prefix="/api/access-codes", tags=["访问码管理"])
app.include_router(ws.router, tags=["WebSocket"])

# 免登录访问路由（独立前缀）
# 注意：access.router 包含了需登录的管理接口和免登录的访问接口
# 通过路径区分：/api/access/{code} 是公开的
from fastapi import APIRouter as FastAPIRouter
access_public = FastAPIRouter()
access_public.add_api_route("/{code}", access.access_text, methods=["GET"], tags=["快速访问"])
access_public.add_api_route("/{code}/download", access.access_file_download, methods=["GET"], tags=["快速访问"])
app.include_router(access_public, prefix="/api/access")

# 后续阶段继续挂载：
# from .api import admin
# app.include_router(admin.router, prefix="/api/admin", tags=["管理后台"])
