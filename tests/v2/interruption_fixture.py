"""Subprocess fault injection: simulated input only, never desktop access."""
import argparse
import os
from pathlib import Path
from cu_suite.v2.runtime import Runtime, Policy
from .fake_platform import FakePlatform
from .test_runtime import click, run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", required=True)
    parser.add_argument("--effect", required=True)
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    pal = FakePlatform()
    native_dispatch = pal.dispatch
    def dispatch(*values):
        result = native_dispatch(*values)
        Path(args.effect).write_text("one simulated input", encoding="utf-8")
        if args.phase == "after_input": os._exit(23)
        return result
    pal.dispatch = dispatch
    runtime = Runtime(pal, policy=Policy(frozenset({"test"})), journal_path=args.journal)
    commit = runtime._journal
    def journal(job, ordinal, step, phase):
        commit(job, ordinal, step, phase)
        if (args.phase, phase) in (("after_intention", "intention"), ("after_ack", "sent")):
            os._exit(23)
    runtime._journal = journal
    session = runtime.call("axis.observe", {"target_id": "test"})["session_id"]
    run(runtime, session, [click()], key="interrupted-request")
    raise AssertionError("Fault injection did not interrupt the process")


if __name__ == "__main__":
    main()
