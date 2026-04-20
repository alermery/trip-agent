# FastAPI 依赖注入：从 Bearer Token 解析当前用户或管理员（用于受保护路由）。

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models.user import User
from backend.app.security import decode_access_token, decode_token_payload

# OAuth2PasswordBearer 与 OpenAPI 文档中的「Authorize」流程配合；实际客户端也可直接传 Authorization: Bearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
# 管理接口强制要求 Authorization 头，缺失时自动 403/401
admin_bearer = HTTPBearer(auto_error=True)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    # 解析 JWT 的 sub 为用户名，并加载数据库中的 User 实体。
    username = decode_access_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def get_current_admin_user(
    creds: HTTPAuthorizationCredentials = Depends(admin_bearer),
    db: Session = Depends(get_db),
) -> User:
    # 除校验 JWT 外，还要求 payload 中 role=admin 且数据库用户 is_admin 为真。
    payload = decode_token_payload(creds.credentials)
    if not payload or payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员令牌",
        )
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非管理员")
    return user
