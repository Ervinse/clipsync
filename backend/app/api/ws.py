"""WebSocket 路由：实时连接管理

认证方式：浏览器 WebSocket 不能自定义 Authorization 头，token 通过子协议传递：
    new WebSocket(url, ['clipsync.v1', 'bearer.<JWT>'])
服务端校验后只回选 'clipsync.v1'，token 不出现在 URL 中，不会被 access log 记录。

两种连接：
- 登录凭证：接收属主自己的全部推送
- 快速访问凭证（typ=qa）：只接收该访问码下内容有变化的信号（access_items_changed）；
  访问码失效、凭证到期或属主被禁用时以 1008 断开。每次心跳都重新确认一次，
  定时清理删掉过期访问码这类没有经过接口的变化，最迟一个心跳周期内也会断开
"""
import json
import logging
import time
from dataclasses import dataclass

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..models import User
from ..core.security import decode_access_token, get_user_id_from_payload
from ..core.quick_access import parse_quick_payload, quick_access_is_valid
from ..core.ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()

WS_PROTOCOL = "clipsync.v1"
_TOKEN_PREFIX = "bearer."
# 客户端只会发心跳，超过这个字符数的消息直接断开。单帧的字节数另由 uvicorn 的 --ws-max-size 4096 限制，
# 超大的帧在收完之前就被拒绝，这里只处理已经收到的消息
_MAX_MESSAGE_CHARS = 1024


@dataclass
class _Peer:
    user_id: int  # 登录连接为用户本人，快速访问连接为访问码的属主
    quick_code: str | None = None
    expires_at: float = 0  # 快速访问凭证的到期时间（Unix 秒）


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


async def _authenticate(websocket: WebSocket) -> _Peer | None:
    """安全红线：校验签名 + 过期 + 用户存在且未禁用；快速访问凭证还要求访问码下仍有内容"""
    payload = decode_access_token(_extract_token(websocket) or "")
    user_id = get_user_id_from_payload(payload)
    if user_id is not None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        return _Peer(user_id=user.id)

    quick = parse_quick_payload(payload)
    if quick is None:
        return None
    owner_id, code = quick
    async with AsyncSessionLocal() as db:
        if not await quick_access_is_valid(db, owner_id, code):
            return None
    return _Peer(user_id=owner_id, quick_code=code, expires_at=float(payload["exp"]))


async def _still_valid(peer: _Peer) -> bool:
    """连接是否仍然有效：登录连接要求用户存在且未禁用；快速访问连接要求凭证未到期、访问码下仍有内容"""
    async with AsyncSessionLocal() as db:
        if peer.quick_code is None:
            result = await db.execute(select(User.is_active).where(User.id == peer.user_id))
            return bool(result.scalar_one_or_none())
        if time.time() >= peer.expires_at:
            return False
        return await quick_access_is_valid(db, peer.user_id, peer.quick_code)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    消息格式：
        客户端: {"type": "ping"}  → 服务端: {"type": "pong"}
    推送（只带信号，不带正文）：
        登录连接：clipboard_updated / texts_changed / file_added / file_deleted / access_codes_changed / quota_updated
        快速访问连接：access_items_changed
    """
    peer = await _authenticate(websocket)
    if peer is None:
        # 握手前关闭：客户端收到 403，不会进入已连接状态
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept(subprotocol=WS_PROTOCOL)
    if peer.quick_code is None:
        manager.register(peer.user_id, websocket)
    else:
        manager.register_quick(peer.user_id, peer.quick_code, websocket)

    try:
        # 安全红线：握手校验到登记连接之间有空档，禁用 / 删除用户的断开动作可能恰好落在这段时间里、
        # 看不到这条连接。登记之后再确认一次，不通过就断开
        if not await _still_valid(peer):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        while True:
            data = await websocket.receive_text()
            if len(data) > _MAX_MESSAGE_CHARS:
                await websocket.close(code=status.WS_1009_MESSAGE_TOO_BIG)
                break
            try:
                message = json.loads(data)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get("type") == "ping":
                if peer.quick_code is not None and not await _still_valid(peer):
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                    break
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass  # 客户端正常断开
    except Exception:
        logger.exception("WebSocket 连接异常 user=%s", peer.user_id)
    finally:
        # 无论何种方式断开都清理，避免连接表残留
        if peer.quick_code is None:
            manager.disconnect(peer.user_id, websocket)
        else:
            manager.disconnect_quick(peer.user_id, websocket)
