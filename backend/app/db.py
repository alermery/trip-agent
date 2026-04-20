# SQLAlchemy 引擎与会话工厂：供 FastAPI 依赖注入与各业务模块获取数据库连接。

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from backend.app.config import settings

class Base(DeclarativeBase):
    # 所有 ORM 模型的声明式基类。
    pass

# pool_pre_ping：连接池取出连接前 ping 一次，避免 PostgreSQL 侧断连导致首次查询失败
engine = create_engine(settings.PG_DSN, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    # 请求级会话：yield 给路由使用，请求结束后在 finally 中关闭，避免连接泄漏。
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
