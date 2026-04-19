from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from backend.app.config import settings

class Base(DeclarativeBase):
    pass

engine = create_engine(settings.PG_DSN, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
