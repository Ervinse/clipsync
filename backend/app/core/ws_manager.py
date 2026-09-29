"""WebSocket 连接管理器：维护用户连接 + 实时广播"""
import json
from typing import Dict, Set
from fastapi import WebSocket


class ConnectionManager:
    """
    WebSocket 连接管理器

    维护 user_id → WebSocket 集合的映射，支持同一用户多终端在线。
    """

    def __init__(self):
        # user_id -> set of WebSocket connections
        self.active_connections: Dict[int, Set[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        """接受新连接，加入对应用户的连接集合"""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        """断开连接，从集合中移除"""
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            # 如果该用户没有在线连接，删除 key
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def broadcast_to_user(self, user_id: int, message: dict, exclude: WebSocket = None):
        """
        向指定用户的所有在线终端广播消息（可排除触发源）

        Args:
            user_id: 目标用户 ID
            message: 消息字典（将序列化为 JSON）
            exclude: 排除的连接（通常是触发本次变更的连接，避免自己收到自己的更新）
        """
        if user_id not in self.active_connections:
            return

        message_text = json.dumps(message)
        disconnected = set()

        for connection in self.active_connections[user_id]:
            if connection == exclude:
                continue
            try:
                await connection.send_text(message_text)
            except Exception:
                # 连接已断开，记录待清理
                disconnected.add(connection)

        # 清理失效连接
        for conn in disconnected:
            self.disconnect(user_id, conn)


# 全局单例
manager = ConnectionManager()
