"""WebSocket 路由：实时连接管理

认证方式：浏览器 WebSocket 不能自定义 Authorization 头，token 通过子协议传递：
    new WebSocket(url, ['clipsync.v1', 'bearer.<JWT>'])
服务端校验后只回选 'clipsync.v1'，token 不出现在 URL 中，不会被 access log 记录。
"""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..models import User
from ..core.security import decode_access_token, get_user_id_from_payload
from ..core.ws_manager import manager

router = APIRouter()

WS_PROTOCOL = "clipsync.v1"
_TOKEN_PREFIX = "bearer."
_MAX_MESSAGE_BYTES = 1024  # 客户端只会发心跳，超长消息直接断开


def _extract_token(websocket: WebSocket) -> str | None:
    """从 Sec-WebSocket-Protocol 中取出 token"""
    raw = websocket.headers.get("sec-websocket-protocol", "")
    protocols = [p.strip() for p in raw.split(",") if p.strip()]
    if WS_PROTOCOL not in protocols:
        return None
    for proto in protocols:
        if proto.startswith(_TOKEN_PREFIX):
            return proto[len(_TOKEN_PREFIX):]
    return None


async def _authenticate(websocket: WebSocket) -> User | None:
    """安全红线：校验签名 + 过期 + 用户存在且未禁用"""
    user_id = get_user_id_from_payload(decode_access_token(_extract_token(websocket) or ""))
    if user_id is None:
        return None
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    消息格式：
        客户端: {"type": "ping"}  → 服务端: {"type": "pong"}
    推送：
        {"type": "clipboard_updated" | "file_added" | "file_deleted", "data": {...}}
    """
    user = await _authenticate(websocket)
    if user is None:
        # 握手前关闭：客户端收到 403，不会进入已连接状态
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept(subprotocol=WS_PROTOCOL)
    manager.register(user.id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            if len(data) > _MAX_MESSAGE_BYTES:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                break
            try:
                message = json.loads(data)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # 无论何种方式断开都清理，避免连接表残留
        manager.disconnect(user.id, websocket)
