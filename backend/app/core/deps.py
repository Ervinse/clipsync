"""依赖注入：当前用户 / 角色校验"""
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User, UserRole
from .security import decode_access_token, get_user_id_from_payload

# auto_error=False：缺少 token 时由下方统一返回 401（前端据此跳转登录页）
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    依赖注入：解析 JWT，返回当前登录用户。
    安全红线：所有需要登录的接口都必须通过此依赖获取用户；每次请求都回库校验用户存在且未禁用。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = get_user_id_from_payload(decode_access_token(credentials.credentials))
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )

    return user


def require_role(*allowed_roles: UserRole):
    """
    角色校验依赖工厂：生成依赖函数，校验用户角色。

    安全红线：管理后台接口必须通过此依赖校验角色；superadmin 专属接口只传 UserRole.SUPERADMIN。
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return current_user

    return role_checker
