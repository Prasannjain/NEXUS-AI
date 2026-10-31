import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="nexus-ai-tests-")

os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{os.path.join(_TMP, 'nexus_test.db')}",
        "CHECKPOINT_DATABASE_PATH": os.path.join(_TMP, "checkpoints.db"),
        "GENERATED_DOCUMENTS_DIR": os.path.join(_TMP, "documents"),
        "SECRET_KEY": "test-only-secret-key-at-least-32-bytes-long",
        "LLM_PROVIDER": "none",
        "OLLAMA_BASE_URL": "",
        "REDIS_URL": "",
        "SEED_DEMO_DATA": "false",
        "DEMO_PASSWORD": "NexusTest123!",
    }
)

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.seed import bootstrap  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_database():
    bootstrap()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def operator(db):
    return db.scalar(select(User).where(User.email == "operator@nexus-ai.example"))


@pytest.fixture
def approver(db):
    return db.scalar(select(User).where(User.email == "admin@nexus-ai.example"))
