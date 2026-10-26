"""FastAPI 应用入口"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from .config import settings
from .rate_limit import limiter
from .api import auth, clipboard, texts, files, ws, access, admin
from .database import AsyncSessionLocal
from .core.deploy_info import current_build, record_deployment
from .core.logging_setup import setup_app_logging

# app 下各模块的日志输出到容器日志：审计日志（超管查看 / 下载他人内容）与部署登记依赖 INFO 级别能输出
setup_app_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时登记部署记录；登记失败只记日志，不影响服务启动"""
    try:
        async with AsyncSessionLocal() as db:
            await record_deployment(db, current_build())
    except Exception:
        logger.exception("登记部署记录失败")
    yield


app = FastAPI(
    title="ClipSync API",
    # 与后台「系统信息」显示的版本一致；开发环境没有版本号
    version=settings.APP_VERSION or "dev",
    description="跨终端剪贴板与文件同步服务",
    lifespan=lifespan,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """限流 → 429 + 中文 detail（slowapi 默认返回英文的 error 字段，前端按 detail 显示）"""
    return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"detail": "操作过于频繁，请稍后再试"})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """
    请求校验失败 → 422。详情只含 type / loc / msg，不回传原始输入：
    输入里若有孤立代理字符（如 JSON 里的 "\\ud800"），FastAPI 默认把它原样写进响应会因编码失败变成 500；
    不回传输入也避免把客户端提交的密码等内容原样返回。
    """
    detail = [
        {"type": error["type"], "loc": list(error["loc"]), "msg": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": detail})


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
    """统一安全响应头；HSTS 仅在 .env 开启时下发（HTTP 部署时不能发）"""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api"):
        # 接口响应不是页面：不允许加载任何资源、不允许被嵌入。/docs 等开发用的页面需要内联脚本，不加
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if settings.HSTS_ENABLED:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.get("/")
async def root():
    """健康检查"""
    return {"status": "ok", "service": "ClipSync"}


app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(clipboard.router, prefix="/api/clipboard", tags=["云剪切板"])
app.include_router(texts.router, prefix="/api/texts", tags=["文本栏目"])
app.include_router(files.router, prefix="/api/files", tags=["文件"])
app.include_router(access.router, prefix="/api/access-codes", tags=["访问码管理"])
# 免登录访问接口单独挂载在 /api/access，不会出现在 /api/access-codes 前缀下
app.include_router(access.public_router, prefix="/api/access", tags=["快速访问"])
app.include_router(admin.router, prefix="/api/admin", tags=["管理后台"])
app.include_router(ws.router, tags=["WebSocket"])
