"""Boot actual API and Celery/Redis workers for isolated browser tests."""

import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
backend = root / "backend"
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "TEST_MODE": "true",
        "TEST_AUTH_SECRET": "e2e-only-signing-secret-at-least-32-characters",
        "DATABASE_URL": os.getenv(
            "E2E_DATABASE_URL",
            "postgresql+psycopg://creatorops:creatorops@localhost:55432/creatorops_test",
        ),
        "REDIS_URL": os.getenv("E2E_REDIS_URL", "redis://localhost:56379/1"),
        "FRONTEND_URL": "http://127.0.0.1:3001",
    }
)
if not os.environ["DATABASE_URL"].endswith("_test"):
    raise RuntimeError("E2E requires a dedicated test database")
# Exercise the same API/worker/scheduler launcher used by the free hosted demo.
os.environ["PORT"] = "8001"
os.chdir(backend)
os.execv(sys.executable, [sys.executable, "-m", "app.deployment.free_demo"])
