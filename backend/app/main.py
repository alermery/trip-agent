from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.app.api.auth import router as auth_router
from backend.app.api.history import router as history_router
from backend.app.api.location import router as location_router
from backend.app.api.rag_admin import router as rag_admin_router
from backend.app.api.ws import router as ws_router
from backend.app.config import settings
from backend.app.db import Base, SessionLocal, engine
from backend.app import models as _models
from backend.app.models.user import User
from backend.app.security import hash_password

_ = _models

app = FastAPI(
    title="小C助手 API",
    version="0.1.0",
    description="基于 FastAPI 的小C助手智能体服务",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def _bootstrap_admin_user() -> None:
    """当 .env 中配置了 ADMIN_PASSWORD 时：创建或更新管理员账号，并把密码设为该值（与库中旧密码无关）。"""
    pwd = (settings.ADMIN_PASSWORD or "").strip()
    if not pwd:
        return
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
        if not u:
            db.add(
                User(
                    username=settings.ADMIN_USERNAME,
                    password_hash=hash_password(pwd),
                    is_admin=True,
                )
            )
        else:
            u.is_admin = True
            # 若 admin 曾被普通注册，仅设 is_admin 会导致与 .env 密码不一致，此处按 .env 覆盖哈希
            u.password_hash = hash_password(pwd)
        db.commit()
    finally:
        db.close()


@app.on_event("startup")
def init_pg_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false"
            )
        )
    if settings.APP_ENV != "production":
        Base.metadata.create_all(bind=engine)
        _dev_migrations = [
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(64)",
            "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS conversation_started_at TIMESTAMP",
            "UPDATE chat_messages SET conversation_id = ('legacy_' || id::text) WHERE conversation_id IS NULL",
            "UPDATE chat_messages SET conversation_started_at = created_at WHERE conversation_started_at IS NULL",
            "CREATE INDEX IF NOT EXISTS ix_chat_messages_conversation_id ON chat_messages (conversation_id)",
        ]
        with engine.begin() as conn:
            for sql in _dev_migrations:
                conn.execute(text(sql))
    _bootstrap_admin_user()


app.include_router(auth_router)
app.include_router(history_router)
app.include_router(location_router)
app.include_router(rag_admin_router)
app.include_router(ws_router)
