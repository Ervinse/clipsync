"""FastAPI 应用入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

app = FastAPI(
    title="ClipSync API",
    version="0.1.0",
    description="跨终端剪贴板与文件同步服务",
)

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


# 后续阶段将在此挂载各路由模块：
# from .api import auth, clipboard, files, access, admin, ws
# app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
# ...
