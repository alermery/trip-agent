# 密码哈希与 JWT 编解码：登录签发令牌，受保护路由解析 sub 与可选 role。

from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from backend.app.config import settings

# 采用密码哈希方案。
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# 对明文密码做单向哈希，仅存哈希值入库。
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

# 登录时比对明文与库中哈希是否一致。
def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

# exp 使用 UTC，与 python-jose 默认行为一致
def create_access_token(subject: str, *, role: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict = {"sub": subject, "exp": expire}
    if role:
        payload["role"] = role
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

# 校验签名与过期时间。
def decode_token_payload(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None

# 从合法 JWT 中提取用户名（标准字段 sub）。
def decode_access_token(token: str) -> str | None:
    payload = decode_token_payload(token)
    if not payload:
        return None
    return payload.get("sub")
