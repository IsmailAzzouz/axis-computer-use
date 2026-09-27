"""Opt-in wheel/console qualification. No native desktop input is used.

python -m tests.v2.installed_mcp_smoke --python <installed-python.exe>
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

from cu_suite.v2.runtime import Policy, Runtime
from cu_suite.v2.transport import AxisClient, BrokerServer
from .fake_platform import FakePlatform
from .test_public_mcp import TOKEN, check_stdio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    args = parser.parse_args()
    python = Path(args.python).resolve(strict=True)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "AXIS_TOKEN")}
    with tempfile.TemporaryDirectory(prefix="axis-wheel-smoke-") as directory:
        probe = subprocess.run([str(python), "-c",
            "import cu_suite,json,importlib.metadata as m,importlib.util; from importlib.resources import files; "
            "assert all(importlib.util.find_spec('cu_suite.'+name) is None for name in "
            "('agent_facade','platforms','providers','input_controller')), 'Legacy modules in distribution'; "
            "print(json.dumps({'origin':cu_suite.__file__,'version':m.version('axis-computer-use'),"
            "'ocr_resource':files('cu_suite.v2.platforms').joinpath('windows_ocr.ps1').is_file()}))"],
            cwd=directory, env=env, capture_output=True, check=True, timeout=10)
        evidence = json.loads(probe.stdout)
        assert "site-packages" in evidence["origin"], evidence
        assert evidence["version"] == "0.1.0" and evidence["ocr_resource"]
        # Append only for the test fixture, after installed site-packages. Both
        # supervisor and spawned child must import AXIS from the wheel.
        repository = str(Path(__file__).resolve().parents[2])
        worker_probe = subprocess.run([str(python), "-c",
            "import sys,json; sys.path.append("+repr(repository)+"); "
            "from cu_suite.v2.worker import SupervisedPlatform; "
            "w=SupervisedPlatform('tests.v2.worker_fixture','WorkerFixture'); "
            "target=w.bind('test'); frame=w.capture(target); "
            "print(json.dumps({'origin':w._rpc('runtime_origin'),'size':frame.size})); w.close()"],
            cwd=directory, env=env, capture_output=True, check=True, timeout=15)
        worker_evidence = json.loads(worker_probe.stdout)
        assert "site-packages" in worker_evidence["origin"] and worker_evidence["size"] == [200, 200]
        evidence["installed_worker"] = worker_evidence
        observer_probe = subprocess.run([str(python), "-c",
            "import sys,json,time; sys.path.append("+repr(repository)+"); "
            "import cu_suite.v2.temporal_worker as t; "
            "settings={'probes':[{'name':'red','region':[0,0,20,20]}],'interval':.01,'max_gap':.2}; "
            "r=t.TemporalObserver('tests.v2.temporal_fixture','SceneSource',{'marker':'unused-marker'},"
            "settings,{'red':[0,0,0]},time.monotonic()+5); snapshot=r.snapshot(); r.close(); "
            "print(json.dumps({'origin':t.__file__,'samples':snapshot['samples'],'mode':snapshot['observation_mode']}))"],
            cwd=directory, env=env, capture_output=True, check=True, timeout=10)
        observer_evidence = json.loads(observer_probe.stdout)
        assert "site-packages" in observer_evidence["origin"] and observer_evidence["samples"] >= 2
        assert observer_evidence["mode"] == "continuous"
        evidence["installed_observer"] = observer_evidence
        pal = FakePlatform()
        runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=str(Path(directory)/"journal.db"))
        server = BrokerServer(runtime, token=TOKEN, port=0)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            client = AxisClient(token=TOKEN, port=server.server_address[1])
            for module in ("cu_suite.mcp.server", "cu_suite.mcp", "cu_suite.cli", "cu_suite"):
                check_stdio(module, client, pal, python=python, cwd=directory)
            assert len(pal.calls) == 4  # one native-double dispatch per two-step plan
            for name in ("axis", "axis-cu", "cu-suite", "axis-mcp"):
                executable = python.parent / (name + (".exe" if os.name == "nt" else ""))
                command = [str(executable)] + ([] if name == "axis-mcp" else ["mcp"])
                requests = (b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
                            b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"axis.help","arguments":{}}}\n')
                result = subprocess.run(command, input=requests,
                                        cwd=directory, env=env, capture_output=True, check=True, timeout=10)
                replies = {r["id"]: r for r in map(json.loads, result.stdout.splitlines())}
                assert len(replies[1]["result"]["tools"]) == 6
                from cu_suite.v2.help import guide
                assert replies[2]["result"]["structuredContent"] == guide()
                assert not replies[2]["result"]["isError"]
            evidence.update(stdio_modules=4, console_commands=4, simulated_dispatches=4, native=False)
            print(json.dumps(evidence))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
            runtime.close()


if __name__ == "__main__":
    main()
