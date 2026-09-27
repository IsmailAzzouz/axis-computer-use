"""Synthetic observer lifecycle endurance; not native desktop qualification."""
import gc
import json
import threading
import time

import pytest

from .test_temporal_worker import open_scene


def test_one_hundred_closed_observers_release_resources_when_retained(tmp_path, record_testsuite_property):
    psutil = pytest.importorskip("psutil")
    process = psutil.Process()
    resource_count = process.num_handles if hasattr(process, "num_handles") else process.num_fds
    # Separate one-time multiprocessing setup from per-reader resources.
    warmup = open_scene(tmp_path/"warmup")
    warmup.snapshot()
    warmup.close()
    gc.collect()
    before = resource_count()
    rss_before = process.memory_info().rss
    prior_children = {child.pid for child in process.children()}
    initial_threads = {thread.ident for thread in threading.enumerate()}
    retained, latencies, samples, counts = [], [], [], []
    for index in range(100):
        start = time.monotonic()
        observer = open_scene(tmp_path/f"idle-{index}")
        try:
            snapshot = observer.snapshot()
            assert snapshot["sequence"] == [] and not snapshot["active"]
            samples.append(snapshot["samples"])
        finally:
            observer.close()
        assert not observer.is_alive()
        assert observer._process is None and observer._stop is None
        retained.append(observer)  # Explicit close, not destructor/GC, must work.
        latencies.append(time.monotonic()-start)
        counts.append(resource_count())
    gc.collect()
    after = resource_count()
    new_children = {child.pid for child in process.children()}-prior_children
    extra_threads = [thread for thread in threading.enumerate()
                     if thread.ident not in initial_threads and thread.name == "axis-worker-io"]
    for thread in extra_threads:
        thread.join(1)
    evidence = {"iterations": len(retained), "handles_or_fds_before": before,
        "handles_or_fds_after": after, "handles_or_fds_peak_after_close": max(counts),
        "rss_delta_bytes": process.memory_info().rss-rss_before,
        "latency_mean_seconds": sum(latencies)/len(latencies), "latency_max_seconds": max(latencies),
        "minimum_samples": min(samples), "live_children": len(new_children),
        "live_io_threads": sum(thread.is_alive() for thread in extra_threads), "native": False}
    record_testsuite_property("observer_endurance", json.dumps(evidence))
    print(json.dumps(evidence))
    assert not new_children and not evidence["live_io_threads"]
    assert after <= before+4, evidence
    assert max(counts) <= before+8, evidence
