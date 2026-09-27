"""Actual Cloudflare Siteverify transport for the optional training widget."""
import json
import os
import urllib.error
import urllib.request

TEST_SITEKEY = "3x00000000000000000000FF"
TEST_SECRET = "1x0000000000000000000000000000000AA"
SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class ProviderError(Exception):
    pass


class TurnstileProvider:
    def __init__(self):
        sitekey = os.environ.get("AXIS_TURNSTILE_SITEKEY", "").strip()
        secret = os.environ.get("AXIS_TURNSTILE_SECRET_KEY", "").strip()
        self.mode = "live" if sitekey and secret else "unconfigured" if sitekey or secret else "test"
        self.sitekey = sitekey or TEST_SITEKEY
        self._secret = secret or TEST_SECRET

    def config(self):
        return {"mode": self.mode, "sitekey": self.sitekey, "action": "axis-training",
                "description": "Official Cloudflare interactive test widget. Test mode does not measure bot resistance."
                if self.mode == "test" else "Configured Cloudflare widget."}

    def verify(self, token, hostname):
        if self.mode == "unconfigured":
            raise ProviderError("Set both AXIS_TURNSTILE_SITEKEY and AXIS_TURNSTILE_SECRET_KEY, or remove both to use official test mode.")
        request = urllib.request.Request(SITEVERIFY, data=json.dumps({"secret": self._secret, "response": token}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Oversized provider response")
                result = json.loads(raw)
        except (OSError, ValueError, urllib.error.URLError):
            raise ProviderError("Cloudflare verification is unavailable. Check the server's internet connection and retry.") from None
        if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
            raise ProviderError("Cloudflare returned an invalid verification response.")
        success = result["success"]
        if self.mode == "live" and success:
            success = result.get("hostname") == hostname and result.get("action") == "axis-training"
        return {"success": success, "mode": self.mode,
                "message": ("Cloudflare test token validated." if self.mode == "test" else "Cloudflare token validated.")
                if success else "Cloudflare rejected this token. Reload the widget and try again."}
