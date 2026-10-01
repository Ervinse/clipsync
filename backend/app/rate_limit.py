"""限流配置

按客户端 IP 限流。request.client.host 由 uvicorn 的 ProxyHeadersMiddleware 根据
X-Forwarded-For 改写，只信任 FORWARDED_ALLOW_IPS（默认 127.0.0.1）发来的头，
因此反向代理必须与后端同机，或在启动参数里显式把代理 IP 加入 --forwarded-allow-ips。

计数存在进程内存中：后端必须单 worker 运行（WebSocket 广播同样依赖单进程）。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
