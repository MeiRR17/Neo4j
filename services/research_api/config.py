"""Fail-closed local service authentication configuration."""
from __future__ import annotations

import hmac
import os
from pathlib import Path
import secrets

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = REPO_ROOT / "secrets" / "research_api_token.txt"


def api_token_path() -> Path:
    value = os.environ.get("DVIROS_RESEARCH_API_TOKEN_FILE", "")
    return Path(value) if value else TOKEN_PATH


def load_token(path: Path | None = None) -> str:
    """Load a local server-to-server token. Never source one from GitHub."""
    path = Path(path or api_token_path())
    if path.is_symlink() or not path.is_file():
        raise ValueError("Research API token file missing or symlinked.")
    if os.name != "nt" and (path.stat().st_mode & 0o077):
        raise ValueError("Research API token file is accessible by group/other.")
    raw = path.read_text(encoding="utf-8").strip()
    if len(raw) < 40 or len(raw) > 256 or any(ch.isspace() for ch in raw):
        raise ValueError("Research API token is not a valid secret.")
    return raw


def check_bearer(supplied: str | None, *, path: Path | None = None) -> bool:
    if not supplied:
        return False
    expected = load_token(path)
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def bootstrap_token(path: Path | None = None) -> Path:
    """Idempotent token generation. Do not print or commit the value."""
    path = Path(path or api_token_path())
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Refusing symlinked token path.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt" and (path.parent.stat().st_mode & 0o077):
        raise ValueError("Secret directory is accessible by group/other.")
    if path.exists():
        load_token(path)
        return path
    token = secrets.token_urlsafe(48)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(token + "\n")
    if os.name != "nt":
        os.chmod(path, 0o600)
    load_token(path)
    return path
