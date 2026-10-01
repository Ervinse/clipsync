"""WebSocket 连接管理器：维护用户连接 + 实时广播

注意：连接表存在进程内存中，后端必须单 worker 运行。
"""
import json
from typing import Dict, Set

from fastapi import WebSocket


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
        disconnected = set()

        # 复制一份再遍历：await 期间集合可能被其他协程修改
        for connection in list(connections):
            if connection is exclude:
                continue
            try:
                await connection.send_text(message_text)
            except Exception:
                disconnected.add(connection)

        for conn in disconnected:
            self.disconnect(user_id, conn)


# 全局单例
manager = ConnectionManager()
