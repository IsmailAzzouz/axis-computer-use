"""WinRT OCR adapter. A failed language/backend is unavailable, never empty text."""
from pathlib import Path
import base64
import json
import subprocess
import tempfile

from ..contracts import AxisError
from ..perception import checked_region


def recognize(image, region=None):
    box = checked_region(region, image.size)
    with tempfile.TemporaryDirectory(prefix="axis-ocr-") as directory:
        path = Path(directory)/"crop.png"
        image.crop(box).save(path)
        try:
            process = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                str(Path(__file__).with_suffix(".ps1")), "-ImagePath", str(path)],
                capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW)
        except (subprocess.TimeoutExpired, OSError):
            raise AxisError("CAPABILITY_UNAVAILABLE", "Windows OCR unavailable or timed out")
        if process.returncode:
            raise AxisError("CAPABILITY_UNAVAILABLE", "Windows OCR backend/language unavailable")
        try:
            result = json.loads(base64.b64decode(process.stdout.strip()).decode("utf-8"))
        except (ValueError, UnicodeError):
            raise AxisError("OBSERVATION_UNAVAILABLE", "OCR returned invalid data")
        for line in result["lines"]:
            for word in line["words"]:
                word["bounds"][0] += box[0]
                word["bounds"][2] += box[0]
                word["bounds"][1] += box[1]
                word["bounds"][3] += box[1]
        return {**result, "region": box, "provenance": "windows_winrt_ocr", "coordinate_space": "window_frame",
                "coverage": "unverified", "confidence": None}
