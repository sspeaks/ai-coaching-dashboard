import shutil
from pathlib import Path

import pytest

from evidence_api.config import Settings


@pytest.fixture
def settings() -> Settings:
    root = Path("services/evidence-worker/tests/.runtime")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return Settings(
        environment="test",
        auth_mode="development",
        database_url=f"sqlite:///{root / 'evidence.db'}",
        media_root=root / "media",
    )
