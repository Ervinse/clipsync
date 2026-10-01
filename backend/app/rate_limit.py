"""限流配置"""
from slowapi import Limiter
from slowapi.util import get_remote_address

# 初始化限流器，按客户端 IP 限流
limiter = Limiter(key_func=get_remote_address)
