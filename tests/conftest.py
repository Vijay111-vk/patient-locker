import os
import sys
import tempfile
from pathlib import Path

# Isolated data dir, rules engine, console notifiers: tests never call external services.
_tmp = tempfile.mkdtemp(prefix="locker-test-")
os.environ.update(DATA_DIR=_tmp, DATABASE_URL="", LLM_PROVIDER="none", WHATSAPP_PROVIDER="console",
                  EMAIL_PROVIDER="console", SECRET_KEY="test-secret", API_KEY="test-api-key",
                  TEST_RECIPIENT_PHONE="", TEST_RECIPIENT_EMAIL="")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def seeded():
    import subprocess

    root = Path(__file__).resolve().parent.parent
    if not (root / "sample_data" / "profiles.json").exists():
        subprocess.check_call([sys.executable, str(root / "scripts" / "make_sample_data.py")])
    from scripts import seed

    sys.argv = ["seed"]
    seed.main()
    from app import pipeline

    pipeline.SYNC = True
    return root / "sample_data"


@pytest.fixture()
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def login(client, username, password):
    import re

    r = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', r.text).group(1)
    r = client.post("/login", data={"username": username, "password": password, "next": "/", "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303
    page = client.get("/account")
    return re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
