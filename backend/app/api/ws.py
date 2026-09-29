"""WebSocket 路由：实时连接管理"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import User
from ..core.security import decode_access_token
from ..core.ws_manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """
    WebSocket 连接端点：校验 JWT，维护用户连接，接收心跳。

    连接参数：
        ?token=<JWT>  通过查询参数传递 token（WebSocket 无法自定义 header）

    消息格式（可选扩展）：
        客户端发送: {"type": "ping"}
        服务端响应: {"type": "pong"}

    实时推送格式：
        {"type": "clipboard_updated", "data": {...}}
        {"type": "file_added", "data": {...}}
        {"type": "file_deleted", "data": {...}}
    """
    # 1. 解析 token，获取 user_id
    payload = decode_access_token(token)
    if not payload:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token payload")
        return

    # 2. 校验用户存在且活跃
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == int(user_id)))
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="User not found or inactive")
            return

    # 3. 接受连接，加入管理器
    await manager.connect(user.id, websocket)

    try:
        # 4. 保持连接，处理客户端消息（心跳等）
        while True:
            data = await websocket.receive_text()
            # 简单心跳响应（可选扩展）
            if data == '{"type":"ping"}':
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        # 5. 客户端断开连接
        manager.disconnect(user.id, websocket)
    except Exception:
        # 6. 异常断开
        manager.disconnect(user.id, websocket)
