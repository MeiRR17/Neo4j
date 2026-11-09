"""DvirOS -> Research API HMAC service identity, replay and clock-skew guard.

Shared secret is ONLY stored in a local 0600 file (not a browser, Git repo
or environment literal). The signature authenticates exact GET path+query,
timestamp and nonce. It supplements — never replaces — the existing bearer.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import threading
import time

from services.research_api.config import bootstrap_token, load_token

SIGNATURE_WINDOW_SECONDS = 60
NONCE_PATTERN = re.compile(r"^[a-f0-9]{32}$")
SIGNATURE_PATTERN = re.compile(r"^[a-f0-9]{64}$")
CLIENT_ID = "dvir-os/research-bff/v1"
DEFAULT_KEY_FILE = Path(__file__).resolve().parents[2] / "secrets" / "dviros_hmac_key.txt"


def signature_key_path() -> Path:
    raw = os.environ.get("DVIROS_SIGNATURE_KEY_FILE")
    return Path(raw) if raw else DEFAULT_KEY_FILE


def bootstrap_signature_key(path: Path | None = None) -> Path:
    return bootstrap_token(path or signature_key_path())


def signature_message(method: str, raw_target: str, timestamp: int, nonce: str) -> bytes:
    if method != "GET" or not raw_target.startswith("/v1/") or "\n" in raw_target:
        raise ValueError("Signed requests must be canonical /v1 GET requests.")
    if not NONCE_PATTERN.fullmatch(nonce) or not isinstance(timestamp, int):
        raise ValueError("Malformed signed service identity.")
    return f"{CLIENT_ID}\n{method}\n{raw_target}\n{timestamp}\n{nonce}".encode("utf-8")


def sign_request(secret: str, method: str, raw_target: str,
                 timestamp: int, nonce: str) -> str:
    return hmac.new(secret.encode("utf-8"),
                    signature_message(method, raw_target, timestamp, nonce),
                    hashlib.sha256).hexdigest()


class ReplayGuard:
    """Bounded in-process nonce cache. A multi-instance deploy needs shared TTL."""

    def __init__(self) -> None:
        self.seen: dict[str, int] = {}
        self.lock = threading.Lock()

    def consume(self, nonce: str, now: int) -> bool:
        with self.lock:
            # Cache is scoped to the current process. Restarting does not
            # extend the 60s window because timestamps remain mandatory.
            self.seen = {key: exp for key, exp in self.seen.items() if exp > now}
            if nonce in self.seen:
                return False
            if len(self.seen) >= 5000:
                return False
            self.seen[nonce] = now + SIGNATURE_WINDOW_SECONDS
            return True


def verify_signed_request(headers, raw_target: str, *, path: Path | None,
                          guard: ReplayGuard, now: int | None = None) -> bool:
    """Returns false for bad signature/timing/replay; file errors propagate."""
    from services.research_api.config import load_token

    client = headers.get("x-dviros-client")
    timestamp_text = headers.get("x-dviros-timestamp", "")
    nonce = headers.get("x-dviros-nonce", "")
    supplied = headers.get("x-dviros-signature", "")
    if client != CLIENT_ID or not re.fullmatch(r"[0-9]{10,11}", timestamp_text):
        return False
    if not NONCE_PATTERN.fullmatch(nonce) or not SIGNATURE_PATTERN.fullmatch(supplied):
        return False
    timestamp = int(timestamp_text)
    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > SIGNATURE_WINDOW_SECONDS:
        return False
    expected = sign_request(load_token(path or signature_key_path()), "GET",
                            raw_target, timestamp, nonce)
    if not hmac.compare_digest(expected, supplied):
        return False
    return guard.consume(nonce, current)
