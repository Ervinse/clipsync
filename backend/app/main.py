"""FastAPI 应用入口"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings
from .rate_limit import limiter
from .api import auth, clipboard, texts, files, ws, access, admin

app = FastAPI(
    title="ClipSync API",
    version="0.1.0",
    description="跨终端剪贴板与文件同步服务",
)

# 限流器配置
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS 中间件（安全红线：只允许 .env 中 CORS_ORIGINS 白名单，不用通配符）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS_LIST,
    allow_credentials=False,  # Token 走 Authorization header，不依赖 cookie
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Auth-Error"],  # 跨域部署时前端也能读到禁用标记
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """统一安全响应头；HSTS 仅在 .env 开启时下发（HTTP 部署阶段不能发）"""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if settings.HSTS_ENABLED:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.get("/")
async def root():
    """健康检查"""
    return {"status": "ok", "service": "ClipSync"}


# 挂载路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(clipboard.router, prefix="/api/clipboard", tags=["文本"])
app.include_router(texts.router, prefix="/api/texts", tags=["文本栏目"])
app.include_router(files.router, prefix="/api/files", tags=["文件"])
app.include_router(access.router, prefix="/api/access-codes", tags=["访问码管理"])
# 免登录访问接口单独挂载在 /api/access，不会出现在 /api/access-codes 前缀下
app.include_router(access.public_router, prefix="/api/access", tags=["快速访问"])
app.include_router(admin.router, prefix="/api/admin", tags=["管理后台"])
app.include_router(ws.router, tags=["WebSocket"])
