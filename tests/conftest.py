import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.models  # noqa: F401 — registers all ORM models with Base.metadata
from backend.database import Base, get_db

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_engine():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_db(test_engine):
    SessionLocal = sessionmaker(bind=test_engine)
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture(scope="function")
def client(test_engine):
    # Import app here to avoid circular imports before models are registered
    from backend.main import app

    SessionLocal = sessionmaker(bind=test_engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
