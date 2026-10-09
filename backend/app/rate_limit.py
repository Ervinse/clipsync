"""限流配置

按客户端 IP 限流。request.client.host 由 uvicorn 的 ProxyHeadersMiddleware 根据
X-Forwarded-For 改写，只信任 --forwarded-allow-ips 指定来源发来的头（默认 127.0.0.1）。
Docker 部署在 docker-compose.yml 里把它设为 compose 固定子网，即只信任前端容器的 Nginx；
Nginx 用 $remote_addr 覆盖 X-Forwarded-For，客户端自带的值不会被采信。

计数存在进程内存中：后端必须单 worker 运行（WebSocket 广播同样依赖单进程）。
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
