import signal
import subprocess
from unittest.mock import Mock

import pytest

from app.deployment import free_demo


@pytest.fixture(autouse=True)
def clean_database():
    # Launcher lifecycle contract tests never access a database.
    yield


def test_single_api_and_solo_worker_with_one_scheduler():
    api, worker = free_demo.commands(12345)
    assert api[api.index("--port") + 1] == "12345"
    assert api[api.index("--workers") + 1] == "1"
    assert "--no-access-log" in api
    assert "--pool=solo" in worker and worker.count("-B") == 1
    assert "--concurrency=1" in worker
    assert worker[-1].startswith("--schedule=/tmp/")


def setup_launcher(monkeypatch, migration, children=(), interrupted=False):
    monkeypatch.setenv("PORT", "12345")
    monkeypatch.setattr(free_demo.signal, "signal", Mock())
    event = Mock()
    event.wait.return_value = interrupted
    monkeypatch.setattr(free_demo, "Event", lambda: event)
    launch = Mock(side_effect=[migration, *children])
    monkeypatch.setattr(free_demo.subprocess, "Popen", launch)
    stop = Mock()
    monkeypatch.setattr(free_demo, "stop_children", stop)
    return launch, stop


def test_failed_migration_never_starts_api_or_worker(monkeypatch):
    migration = Mock(returncode=3)
    migration.poll.return_value = 3
    launch, stop = setup_launcher(monkeypatch, migration)
    assert free_demo.main() == 3
    assert launch.call_count == 1
    assert launch.call_args.args[0][-3:] == ["alembic", "upgrade", "head"]
    stop.assert_called_once_with([migration])


def test_child_failure_shuts_down_whole_service(monkeypatch):
    migration = Mock(returncode=0)
    migration.poll.return_value = 0
    api, worker = Mock(returncode=7), Mock()
    api.poll.return_value = 7
    launch, stop = setup_launcher(monkeypatch, migration, [api, worker])
    assert free_demo.main() == 7
    assert launch.call_count == 3
    assert all(call.kwargs["start_new_session"] for call in launch.call_args_list)
    stop.assert_called_once_with([api, worker])


def test_shutdown_during_migration_stops_migration(monkeypatch):
    migration = Mock()
    migration.poll.return_value = None
    launch, stop = setup_launcher(monkeypatch, migration, interrupted=True)
    assert free_demo.main() == 0
    assert launch.call_count == 1
    stop.assert_called_once_with([migration])


def test_shutdown_covers_scheduler_descendants_and_force_kills(monkeypatch):
    child = Mock(pid=12345)
    child.wait.side_effect = [subprocess.TimeoutExpired("worker", 0), 0]
    kill = Mock()
    monkeypatch.setattr(free_demo.os, "killpg", kill)
    free_demo.stop_children([child], grace=0)
    assert kill.call_args_list[0].args == (12345, signal.SIGTERM)
    assert kill.call_args_list[1].args == (12345, signal.SIGKILL)
    assert child.wait.call_count == 2
