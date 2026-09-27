"""The only OS selection boundary. Core modules do not import this factory."""
import sys
from importlib.metadata import entry_points

from ..contracts import AxisError
from ..worker import SupervisedPlatform
from ..pal_contract import validate_adapter


def _validated(adapter):
    try:
        validate_adapter(adapter)
    except BaseException:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
        raise
    return adapter


def create_platform():
    if sys.platform == "win32":
        return _validated(SupervisedPlatform("cu_suite.v2.platforms.windows", "WindowsPlatform",
            observer_factory=("cu_suite.v2.platforms.windows_capture_source", "WindowsCaptureSource")))
    candidates = [entry for entry in entry_points(group="axis.platforms") if entry.name == sys.platform]
    if len(candidates) > 1:
        raise AxisError("ADAPTER_CONTRACT_ERROR", "Multiple adapters registered for this OS; host must select one installation")
    if candidates:
        return _validated(candidates[0].load()())
    raise AxisError("CAPABILITY_UNAVAILABLE", "No certified v2 adapter installed for this OS")


def operator_safety(**arguments):
    if sys.platform != "win32":
        raise AxisError("CAPABILITY_UNAVAILABLE", "No operator safety adapter for this OS")
    from .windows_safety import operator_safety as windows_safety
    return windows_safety(**arguments)
