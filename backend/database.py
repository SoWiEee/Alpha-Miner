from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


def get_engine():
    settings = get_settings()
    kwargs = {}
    if settings.DATABASE_URL.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(settings.DATABASE_URL, **kwargs)


def get_db():
    engine = get_engine()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
