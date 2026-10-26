"""快速访问：访问码格式、输错锁定、访问凭证、访问码有效性、通知快速访问页

访问码挂在内容上（clipboard / texts / files 的 access_code 列），同一用户的多样内容可以用同一个码；
完整访问码为「用户名@访问码」。凭完整访问码换取 2 小时的快速访问凭证（JWT，typ=qa），
该凭证只能用于 /api/access/* 与 /ws，不能当登录凭证用（get_user_id_from_payload 拒绝带 typ 的 token）。
"""
import logging
import re
import time
from collections import OrderedDict
from datetime import timedelta
from typing import Iterable

from sqlalchemy import select, or_, literal
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import AsyncSessionLocal
from ..models import User, Clipboard, Text, File
from .security import create_access_token
from .timeutil import utcnow
from .ws_manager import manager

logger = logging.getLogger(__name__)

# 访问码：4–32 位字母、数字与 _ - .，不区分大小写（统一按小写存储与比较）
ACCESS_CODE_PATTERN = re.compile(r"^[a-z0-9_.\-]{4,32}$")
ACCESS_CODE_RULE = "访问码为 4–32 位，只能包含字母、数字和 _ - ."
MAX_EXPIRES_HOURS = 8760  # 访问码最长有效期：1 年

# 快速访问时内容已被删除、或不再挂着这个访问码：两种情况提示相同，不暴露是哪一种
CONTENT_GONE_DETAIL = "内容不存在或访问码已失效"

QUICK_TOKEN_TYPE = "qa"
QUICK_TOKEN_MINUTES = 120  # 快速访问凭证有效期：2 小时

# 同一用户（按用户名查到同一个人）在 LOCK_SECONDS 内累计输错 MAX_FAILURES 次，暂停其快速访问 LOCK_SECONDS 秒
MAX_FAILURES = 10
LOCK_SECONDS = 15 * 60
_TRACK_LIMIT = 10_000  # 失败记录条数的硬上限，防止大量随机用户名撑大内存

# 内容带访问码的三张表：都有 user_id / access_code / access_expires_at 三列
CODED_MODELS = (Clipboard, Text, File)


def normalize_access_code(value: str) -> str:
    """去掉首尾空白并转小写；不符合规则抛 ValueError"""
    code = (value or "").strip().lower()
    if not ACCESS_CODE_PATTERN.fullmatch(code):
        raise ValueError(ACCESS_CODE_RULE)
    return code


def parse_full_code(value: str) -> tuple[str, str] | None:
    """拆分「用户名@访问码」；格式不对返回 None（用户名本身不含 @，按 @ 拆分没有歧义）"""
    parts = (value or "").strip().split("@")
    if len(parts) != 2:
        return None
    username, raw_code = parts[0].strip(), parts[1]
    if not 1 <= len(username) <= 64:
        return None
    try:
        return username, normalize_access_code(raw_code)
    except ValueError:
        return None


def lock_key(owner_id: int | None, username: str) -> str:
    """
    输错锁定的计数键。用户名存在时以用户 id 为键：数据库比较用户名时忽略大小写、重音、
    零宽字符，同一个人的各种写法（alice / ALICE / alicé）必须落在同一个计数上，
    否则换个写法就能重新计数，绕过锁定。用户名不存在时没有 id 可用，以小写用户名为键
    （这类写法永远进不去，各自计数不会让攻击者得到好处）。
    """
    return f"u{owner_id}" if owner_id is not None else f"n:{username.lower()}"


class _Entry:
    """一个锁定键的记录：窗口内每次尝试的时间（clock 秒），以及锁定截止（0 表示未锁定）"""
    __slots__ = ("attempts", "locked_until")

    def __init__(self):
        self.attempts: list[float] = []
        self.locked_until = 0.0


class FailureTracker:
    """
    按锁定键（见 lock_key）统计 LOCK_SECONDS 内的输错次数（进程内存，后端单 worker；重启后清零）。
    不存在的用户名同样计数和锁定，响应与存在的用户名一致，不暴露用户名是否存在。

    用法：每次尝试先 begin_attempt（同步完成，期间没有 await，并发请求不会在计数前溜过锁定检查），
    随后再去比对访问码；比对通过用 confirm_success 退还这一次，不通过什么都不用做（已经计过数）。
    - 输对不会清零：知道某个有效访问码的人，也不能靠「输错 9 次、输对 1 次」循环绕过锁定去猜别的码
    - 只统计窗口内的失败，更早的自然作废，偶尔手滑的正常用户不会越攒越多
    - 记录数有硬上限 _TRACK_LIMIT：满了先丢最久没动静的未锁定记录
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        # 按最近一次尝试的先后排序（最久没动静的在最前），满了从前面淘汰
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def begin_attempt(self, key: str) -> bool:
        """登记一次尝试并按失败计数；已被锁定返回 False（此时不计数），否则返回 True"""
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None:
            if entry.locked_until > now:
                return False
            if entry.locked_until:
                # 锁定期已过：重新计数
                del self._entries[key]
                entry = None
            else:
                window_start = now - LOCK_SECONDS
                entry.attempts = [t for t in entry.attempts if t > window_start]
        if entry is None:
            if len(self._entries) >= _TRACK_LIMIT:
                self._make_room(now)
            entry = self._entries[key] = _Entry()
        else:
            self._entries.move_to_end(key)
        entry.attempts.append(now)
        if len(entry.attempts) >= MAX_FAILURES:
            entry.locked_until = now + LOCK_SECONDS
        return True

    def confirm_success(self, key: str) -> None:
        """访问码比对通过：退还 begin_attempt 预记的这一次，窗口内其余的失败照旧保留"""
        entry = self._entries.get(key)
        if entry is None:
            return
        if entry.attempts:
            entry.attempts.pop()
        if not entry.attempts:
            del self._entries[key]
        elif len(entry.attempts) < MAX_FAILURES:
            entry.locked_until = 0.0

    def clear(self) -> None:
        self._entries.clear()

    def _make_room(self, now: float) -> None:
        """记录满了：丢掉最久没动静的未锁定记录；全都在锁定中时丢最旧的一条"""
        victim = next((k for k, e in self._entries.items() if e.locked_until <= now), None)
        if victim is None:
            victim = next(iter(self._entries))
        del self._entries[victim]


failures = FailureTracker()


def create_quick_token(owner_id: int, code: str) -> str:
    return create_access_token(
        {"sub": str(owner_id), "typ": QUICK_TOKEN_TYPE, "code": code},
        expires_delta=timedelta(minutes=QUICK_TOKEN_MINUTES),
    )


def parse_quick_payload(payload: dict | None) -> tuple[int, str] | None:
    """从快速访问凭证的 payload 取出（属主 id, 访问码）；不是快速访问凭证返回 None"""
    if not payload or payload.get("typ") != QUICK_TOKEN_TYPE:
        return None
    try:
        owner_id = int(payload.get("sub"))
        code = normalize_access_code(payload.get("code") or "")
    except (TypeError, ValueError):
        return None
    return owner_id, code


def valid_code_filter(model, owner_id: int, code: str):
    """
    「属于该属主、访问码相同、未过期」的查询条件（过期的码在定时清理前同样视为无效）。
    安全红线：快速访问所有查询都必须带这组条件，访问凭证只能碰「属主 + 访问码」下的内容。
    """
    return (
        model.user_id == owner_id,
        model.access_code == code,
        or_(model.access_expires_at.is_(None), model.access_expires_at > utcnow()),
    )


async def code_is_active(db: AsyncSession, owner_id: int, code: str) -> bool:
    """该属主名下是否还有至少一样内容挂着这个访问码且未过期"""
    for model in CODED_MODELS:
        result = await db.execute(
            select(literal(1)).select_from(model).where(*valid_code_filter(model, owner_id, code)).limit(1)
        )
        if result.first() is not None:
            return True
    return False


async def quick_access_is_valid(db: AsyncSession, owner_id: int, code: str) -> bool:
    """快速访问仍然有效：属主存在且未禁用，且访问码下还有内容"""
    result = await db.execute(select(User.is_active).where(User.id == owner_id))
    is_active = result.scalar_one_or_none()
    return bool(is_active) and await code_is_active(db, owner_id, code)


async def notify_quick_viewers(owner_id: int, codes: Iterable[str | None]) -> None:
    """
    属主的内容有变化时通知相关的快速访问页（只发信号，不带内容）。
    codes 是受影响的访问码（变化前后的码都要传）；访问码下已经没有有效内容时，
    直接断开这些连接（1008），页面据此提示访问码已失效。没有在线的快速访问页时不查库。

    调用方此时数据已经提交：通知中途失败（如查库时连接断开）只记日志，不向外抛，
    否则接口会返回 500，客户端以为没保存，带原版本号重试还会收到 409。
    """
    try:
        affected = {c for c in codes if c} & manager.quick_codes(owner_id)
        if not affected:
            return
        async with AsyncSessionLocal() as db:
            alive = {c for c in affected if await quick_access_is_valid(db, owner_id, c)}
        await manager.notify_quick(owner_id, alive=alive, dead=affected - alive)
    except Exception:
        logger.exception("通知快速访问页失败 owner=%s", owner_id)
