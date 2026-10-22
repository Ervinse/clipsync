"""WebSocket 连接管理器：维护用户连接 + 快速访问页连接 + 实时推送

注意：连接表存在进程内存中，后端必须单 worker 运行。
"""
import asyncio
import json
from typing import Dict, Iterable, Set

from fastapi import WebSocket

# 单个连接发送超时：网络卡住的终端不能无限期阻塞广播
SEND_TIMEOUT_SECONDS = 5

QUICK_ITEMS_CHANGED = {"type": "access_items_changed", "data": {}}


class ConnectionManager:
    """
    - active_connections：user_id → 已登录终端的连接集合（同一用户多终端在线）
    - quick_connections：属主 user_id → {快速访问页连接: 访问码}，只接收与该访问码有关的信号
    """

    def __init__(self):
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        self.quick_connections: Dict[int, Dict[WebSocket, str]] = {}

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

    def register_quick(self, owner_id: int, code: str, websocket: WebSocket):
        """登记快速访问页的连接（凭访问码进入，不是登录用户）"""
        self.quick_connections.setdefault(owner_id, {})[websocket] = code

    def disconnect_quick(self, owner_id: int, websocket: WebSocket):
        connections = self.quick_connections.get(owner_id)
        if connections is None:
            return
        connections.pop(websocket, None)
        if not connections:
            del self.quick_connections[owner_id]

    def quick_codes(self, owner_id: int) -> set[str]:
        """该属主当前有快速访问页在线的访问码"""
        return set(self.quick_connections.get(owner_id, {}).values())

    async def disconnect_user(self, user_id: int, code: int = 1008):
        """
        主动关闭某用户的全部连接，包括凭其访问码进入的快速访问页。
        安全红线：用户被禁用或删除后，已建立的 WebSocket 不能继续接收推送。
        """
        connections = list(self.active_connections.pop(user_id, set()))
        connections += list(self.quick_connections.pop(user_id, {}).keys())
        await asyncio.gather(*(self._close_quietly(c, code) for c in connections))

    @staticmethod
    async def _close_quietly(connection: WebSocket, code: int):
        """关闭连接：出错或超时都忽略，网络卡住的终端不能拖住调用方（如禁用用户的 HTTP 请求）"""
        try:
            await asyncio.wait_for(connection.close(code=code), timeout=SEND_TIMEOUT_SECONDS)
        except Exception:
            pass

    @staticmethod
    async def _send_all(connections: Iterable[WebSocket], message: dict) -> list[WebSocket]:
        """并发发送，返回发送失败或超时的连接"""
        message_text = json.dumps(message, ensure_ascii=False)

        async def _send(connection: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(connection.send_text(message_text), timeout=SEND_TIMEOUT_SECONDS)
                return None
            except Exception:
                return connection

        return [c for c in await asyncio.gather(*(_send(c) for c in connections)) if c is not None]

    async def broadcast_to_user(self, user_id: int, message: dict):
        """向指定用户的所有在线终端广播消息；不发给快速访问页"""
        connections = self.active_connections.get(user_id)
        if not connections:
            return

        # 复制一份再并发发送：await 期间集合可能被其他协程修改；
        # 单个卡住的终端最多拖 SEND_TIMEOUT_SECONDS，不会拖慢触发广播的 HTTP 请求太久
        failed_connections = await self._send_all(list(connections), message)
        for failed in failed_connections:
            self.disconnect(user_id, failed)
        # 只摘掉不关闭的话，ws.py 的接收循环还在回心跳，前端以为连接正常，不会重连，
        # 该终端之后再也收不到推送；关闭后前端 onclose 走重连，重连成功会补拉数据
        if failed_connections:
            await asyncio.gather(*(self._close_quietly(c, 1011) for c in failed_connections))

    async def notify_quick(self, owner_id: int, alive: set[str], dead: set[str]):
        """
        通知快速访问页：访问码仍有效（alive）的发「内容有变化」信号，已失效（dead）的以 1008 断开。
        由 core/quick_access.notify_quick_viewers 判定有效性后调用。
        """
        connections = dict(self.quick_connections.get(owner_id, {}))
        to_close = [ws for ws, code in connections.items() if code in dead]
        targets = [ws for ws, code in connections.items() if code in alive]
        failed = await self._send_all(targets, QUICK_ITEMS_CHANGED)
        for ws in to_close + failed:
            self.disconnect_quick(owner_id, ws)
        await asyncio.gather(
            *(self._close_quietly(ws, 1008) for ws in to_close),
            *(self._close_quietly(ws, 1011) for ws in failed),
        )


# 全局单例
manager = ConnectionManager()
