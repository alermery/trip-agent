from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.app.db import get_db
from backend.app.models.user import User
from backend.app.schemas.auth import TokenResponse, UserLoginRequest, UserRegisterRequest
from backend.app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# 新用户注册：用户名唯一校验通过后写入哈希密码并返回访问令牌。
@router.post("/register", response_model=TokenResponse)
def register(payload: UserRegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已存在")

    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()

    token = create_access_token(payload.username)
    return TokenResponse(access_token=token)

# 普通用户登录：校验密码成功后签发不含 admin role 的 JWT。
@router.post("/login", response_model=TokenResponse)
def login(payload: UserLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user.username)
    return TokenResponse(access_token=token)

    # 仅 is_admin=true 的用户可获取带 role=admin 的 JWT，用于 RAG 管理等接口。
@router.post("/admin/login", response_model=TokenResponse)
def admin_login(payload: UserLoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非管理员账号")
    token = create_access_token(user.username, role="admin")
    return TokenResponse(access_token=token)
