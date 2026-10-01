"""WebSocket 连接管理器：维护用户连接 + 实时广播

注意：连接表存在进程内存中，后端必须单 worker 运行。
"""
import asyncio
import json
from typing import Dict, Set

from fastapi import WebSocket

# 单个连接发送超时：网络卡住的终端不能无限期阻塞广播
SEND_TIMEOUT_SECONDS = 5


class ConnectionManager:
    """维护 user_id → WebSocket 集合的映射，支持同一用户多终端在线。"""

    def __init__(self):
        self.active_connections: Dict[int, Set[WebSocket]] = {}

    def register(self, user_id: int, websocket: WebSocket):
        """登记已 accept 的连接"""
        self.active_connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        """断开连接，从集合中移除；空集合删 key，避免内存泄漏"""
        connections = self.active_connections.get(user_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            del self.active_connections[user_id]

    async def disconnect_user(self, user_id: int, code: int = 1008):
        """
        主动关闭某用户的全部连接。
        安全红线：用户被禁用或删除后，已建立的 WebSocket 不能继续接收推送。
        """
        connections = self.active_connections.pop(user_id, set())
        for connection in list(connections):
            try:
                await connection.close(code=code)
            except Exception:
                pass

    async def broadcast_to_user(self, user_id: int, message: dict, exclude: WebSocket = None):
        """向指定用户的所有在线终端广播消息（可排除触发源）"""
        connections = self.active_connections.get(user_id)
        if not connections:
            return

        message_text = json.dumps(message, ensure_ascii=False)

        async def _send(connection: WebSocket) -> WebSocket | None:
            """发送成功返回 None，失败或超时返回该连接以便清理"""
            try:
                await asyncio.wait_for(connection.send_text(message_text), timeout=SEND_TIMEOUT_SECONDS)
                return None
            except Exception:
                return connection

        # 复制一份再并发发送：await 期间集合可能被其他协程修改；
        # 单个卡住的终端最多拖 SEND_TIMEOUT_SECONDS，不会拖慢触发广播的 HTTP 请求太久
        targets = [c for c in list(connections) if c is not exclude]
        for failed in await asyncio.gather(*(_send(c) for c in targets)):
            if failed is not None:
                self.disconnect(user_id, failed)


# 全局单例
manager = ConnectionManager()
