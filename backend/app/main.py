# FastAPI 应用入口：挂载路由、CORS、启动时初始化数据库与管理员账号。

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

# 导入 models 包以注册 SQLAlchemy 的表映射（副作用导入，下划线变量避免 linter 报未使用）
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
    # 负载均衡或容器探针使用的存活检查，不访问数据库。
    return {"status": "ok"}

def _bootstrap_admin_user() -> None:
    # 当 .env 中配置了 ADMIN_PASSWORD 时：创建或更新管理员账号，并把密码设为该值（与库中旧密码无关）。
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
    # 启动时：补全 users.is_admin 列；非生产环境建表并执行轻量迁移 SQL。
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false"
            )
        )
    if settings.APP_ENV != "production":
        # 开发/测试：自动建缺失的表
        Base.metadata.create_all(bind=engine)
        # 会话维度字段的渐进式迁移（IF NOT EXISTS 保证可重复执行）
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
    # 根据 .env 中的管理员密码同步库内管理员账号
    _bootstrap_admin_user()

# 业务路由：认证、历史、定位、RAG 管理、WebSocket 对话
app.include_router(auth_router)
app.include_router(history_router)
app.include_router(location_router)
app.include_router(rag_admin_router)
app.include_router(ws_router)
