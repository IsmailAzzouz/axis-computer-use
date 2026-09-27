"""CLI startup failures must not orphan a native worker. No real desktop used."""
import io
import sqlite3
from types import SimpleNamespace

import pytest

from cu_suite.v2 import cli, mcp, platforms
from .fake_platform import FakePlatform


@pytest.fixture(autouse=True)
def cli_output(monkeypatch):
    # Use the supported text-stream interface, not pytest's binary tempfile proxy.
    stream = io.StringIO()
    monkeypatch.setattr(cli, "sys", SimpleNamespace(stdout=stream, stdin=io.StringIO()))
    return stream


@pytest.fixture
def worker(monkeypatch):
    platform = FakePlatform()
    closed = []
    platform.close = lambda: closed.append(True)
    monkeypatch.setattr(platforms, "create_platform", lambda: platform)
    monkeypatch.delenv("AXIS_ALLOW_ALL", raising=False)
    return platform, closed


@pytest.mark.parametrize("mode", ["serve", "standalone", "allow_all"])
def test_journal_open_failure_closes_worker(tmp_path, monkeypatch, worker, mode):
    monkeypatch.setenv("AXIS_TOKEN", "test-token-"*4)
    command = ["serve"] if mode == "serve" else ["mcp", "--"+mode.replace("_", "-")]
    with pytest.raises(sqlite3.OperationalError):
        cli.main(command + ["--journal", str(tmp_path/"missing-parent"/"journal.db")])
    platform, closed = worker
    assert closed == [True] and not platform.calls


@pytest.mark.parametrize("failure", [None, ValueError("server failed"), KeyboardInterrupt()])
def test_standalone_closes_runtime_once_when_stream_ends_or_raises(tmp_path, monkeypatch, worker, failure):
    def serve(self):
        assert self.client._closed is False
        if failure is not None:
            raise failure
    monkeypatch.setattr(mcp.MCPServer, "serve", serve)
    command = ["mcp", "--standalone", "--journal", str(tmp_path/"journal.db")]
    if isinstance(failure, KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            cli.main(command)
    else:
        assert cli.main(command) == (1 if failure else 0)
    platform, closed = worker
    assert closed == [True] and not platform.calls


def test_invalid_mcp_concurrency_closes_worker(tmp_path, worker):
    assert cli.main(["mcp", "--standalone", "--max-calls", "0", "--journal", str(tmp_path/"journal.db")]) == 1
    assert worker[1] == [True] and not worker[0].calls


def test_broker_bind_failure_closes_worker(tmp_path, monkeypatch, worker):
    monkeypatch.setenv("AXIS_TOKEN", "test-token-"*4)
    def broken(*args, **kwargs):
        raise OSError("port already in use")
    monkeypatch.setattr(cli, "BrokerServer", broken)
    assert cli.main(["serve", "--journal", str(tmp_path/"journal.db")]) == 1
    assert worker[1] == [True] and not worker[0].calls


def test_missing_broker_token_does_not_start_worker(tmp_path, monkeypatch):
    monkeypatch.delenv("AXIS_TOKEN", raising=False)
    monkeypatch.setattr(platforms, "create_platform", lambda: pytest.fail("worker created before credential check"))
    assert cli.main(["serve", "--journal", str(tmp_path/"journal.db")]) == 1
