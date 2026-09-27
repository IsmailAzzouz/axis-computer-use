"""Native qualification setup must not leak its own workers on partial startup."""
from types import SimpleNamespace as NS

import pytest

from . import native_harness as module


def setup(monkeypatch, failure=None):
    events = []
    def stage(name):
        events.append(name)
        if name == failure:
            raise RuntimeError(name)
    def capabilities():
        stage("capabilities")
        return {"interactive": failure != "not_interactive"}
    platform = NS(capabilities=capabilities, close=lambda: stage("platform.close"))
    def runtime(*_, **__):
        stage("runtime")
        def close():
            stage("runtime.close")
            platform.close()
        return NS(close=close)
    def broker(*_, **__):
        stage("broker")
        return NS(server_address=("127.0.0.1", 12345), serve_forever=lambda: None,
                  shutdown=lambda: stage("shutdown"), server_close=lambda: stage("server_close"))
    def thread(**_):
        stage("thread")
        return NS(start=lambda: stage("start"), join=lambda _: stage("join"))
    monkeypatch.setattr(module, "create_platform", lambda: platform)
    monkeypatch.setattr(module, "Runtime", runtime)
    monkeypatch.setattr(module, "BrokerServer", broker)
    monkeypatch.setattr(module.threading, "Thread", thread)
    monkeypatch.setattr(module, "AxisClient", lambda **_: object())
    monkeypatch.setattr(module, "MCPServer", lambda _: stage("mcp"))
    return events


@pytest.mark.parametrize("failure", ["capabilities", "not_interactive", "runtime", "broker", "thread", "start", "mcp"])
def test_setup_failure_closes_each_acquired_resource_once(tmp_path, monkeypatch, failure):
    events = setup(monkeypatch, failure)
    with pytest.raises(RuntimeError):
        module.NativeHarness(tmp_path, ["test-app"])
    assert events.count("platform.close") == 1
    assert events.count("runtime.close") == int(failure in {"broker", "thread", "start", "mcp"})
    assert events.count("server_close") == int(failure in {"thread", "start", "mcp"})
    assert events.count("shutdown") == int(failure == "mcp")
    assert events.count("join") == int(failure == "mcp")


def test_normal_close_orders_resources_and_is_idempotent(tmp_path, monkeypatch):
    events = setup(monkeypatch)
    host = module.NativeHarness(tmp_path, ["test-app"])
    host.close()
    host.close()
    assert events[-5:] == ["shutdown", "join", "server_close", "runtime.close", "platform.close"]
    assert events.count("platform.close") == 1
    assert (tmp_path/"trace.json").read_text() == "[]"


def test_broker_cleanup_error_still_closes_worker_and_saves_trace(tmp_path, monkeypatch):
    events = setup(monkeypatch, "shutdown")
    host = module.NativeHarness(tmp_path, ["test-app"])
    with pytest.raises(RuntimeError, match="shutdown"):
        host.close()
    assert events[-5:] == ["shutdown", "join", "server_close", "runtime.close", "platform.close"]
    assert (tmp_path/"trace.json").read_text() == "[]"
