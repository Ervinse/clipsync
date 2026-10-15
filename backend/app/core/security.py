"""安全模块：密码哈希 + JWT 生成与解析"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import jwt, JWTError

from ..config import settings

# bcrypt 只处理前 72 字节，超长密码一律拒绝而不是静默截断
BCRYPT_MAX_BYTES = 72

# 用户不存在时也跑一次 bcrypt，使登录耗时一致，防止按响应时间枚举用户名
_DUMMY_HASH = bcrypt.hashpw(b"clipsync-timing-dummy", bcrypt.gensalt()).decode("utf-8")


def hash_password(plain_password: str) -> str:
    """生成密码哈希（CPU 密集，异步路径中须放入线程池调用）"""
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > BCRYPT_MAX_BYTES:
        raise ValueError("密码不能超过 72 字节")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码（CPU 密集，异步路径中须放入线程池调用）"""
    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > BCRYPT_MAX_BYTES:
        return False
    return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))


def burn_password_check(plain_password: str) -> None:
    """用户不存在时调用：执行一次等价的 bcrypt 校验，结果丢弃"""
    verify_password(plain_password, _DUMMY_HASH)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """生成 JWT access token"""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": now})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """解析 JWT token，返回 payload 或 None（缺少 exp 的 token 一律视为无效）"""
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require_exp": True},
        )
    except JWTError:
        return None


def get_user_id_from_payload(payload: Optional[dict]) -> Optional[int]:
    """
    从登录凭证的 sub 中取出用户 ID；格式不对返回 None（而不是抛 500）。
    安全红线：只接受登录凭证。带 typ 的 token（如快速访问凭证 typ=qa）一律返回 None，不能当登录凭证用。
    """
    if not payload or "typ" in payload:
        return None
    try:
        return int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
