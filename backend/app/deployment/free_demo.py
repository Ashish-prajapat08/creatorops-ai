"""One-instance demo launcher: API and Celery/Beat share free web-service compute.

Not an always-on production worker. The host may suspend this whole process tree.
PostgreSQL retains jobs/approvals; the existing send barrier handles interrupted sends.
"""

import logging
import os
import signal
import subprocess
import sys
from threading import Event

logger = logging.getLogger("creatorops.demo")


def commands(port):
    return [
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--workers",
            "1",
            "--no-access-log",
        ],
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "app.workers.celery_app:celery",
            "worker",
            "-B",
            "--pool=solo",
            "--concurrency=1",
            "--loglevel=WARNING",
            "--schedule=/tmp/creatorops-demo-beat",
        ],
    ]


def stop_children(children, grace=20):
    # Signal process groups so the embedded Beat cannot survive its worker parent.
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    import time

    deadline = time.monotonic() + grace
    for child in children:
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
    for child in children:
        # Also remove any orphaned descendants if the direct child already exited.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def main():
    from app.core.config import settings

    settings()  # Fail before launching children on invalid production configuration.
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    stopped = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    children = []
    try:
        # Free web services have no pre-deploy step. Never start against an old schema.
        migration = subprocess.Popen(
            [sys.executable, "-m", "alembic", "upgrade", "head"], start_new_session=True
        )
        children.append(migration)
        while migration.poll() is None:
            if stopped.wait(0.25):
                return 0
        if migration.returncode:
            return migration.returncode
        children.clear()
        for command in commands(port):
            children.append(subprocess.Popen(command, start_new_session=True))
        while not stopped.wait(0.5):
            for child in children:
                if child.poll() is not None:
                    logger.error("demo_child_exited; restarting the whole service is required")
                    return child.returncode or 1
        return 0
    finally:
        stop_children(children)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
