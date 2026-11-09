#!/usr/bin/env python3
"""Create (once) a local Neo4j Docker secret without revealing credentials.

Python standard library only. Never rotates an existing secret: persistent
Neo4j databases retain their existing password even if a secret file changes.
"""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET_PATH = REPO_ROOT / "secrets" / "neo4j_auth.txt"


def load_auth(path: Path = DEFAULT_SECRET_PATH) -> tuple[str, str]:
    """Read validated local credentials. Reject symlinks and broad POSIX modes."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Authentication secret missing or not a regular file.")
    if os.name != "nt":
        if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
            raise ValueError("Secret directory must be owner-only (chmod 700).")
        if stat.S_IMODE(path.stat().st_mode) != 0o444:
            raise ValueError("Compose file-based secret must be read-only mode 0444 inside a 0700 directory.")
    value = path.read_text(encoding="utf-8").rstrip("\r\n")
    if "\r" in value or "\n" in value or not value.startswith("neo4j/"):
        raise ValueError("Expected a single neo4j/<password> line in the local secret.")
    password = value[len("neo4j/"):]
    if len(password) < 16 or "/" in password or "\x00" in password:
        raise ValueError("Local Neo4j password must be at least 16 characters.")
    return "neo4j", password


def create_secret(path: Path = DEFAULT_SECRET_PATH) -> bool:
    """Create local secret atomically; return False if valid secret already exists."""
    path = Path(path)
    if path.parent.is_symlink():
        raise ValueError("Refusing a symlinked secret directory.")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt" and (stat.S_IMODE(path.parent.stat().st_mode) & 0o077):
        raise ValueError("Refusing to store a secret in a group/world-accessible directory.")
    if path.is_symlink() or path.exists():
        load_auth(path)
        return False

    password = secrets.token_urlsafe(36)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(f"neo4j/{password}\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    # Compose mounts file-backed secrets without changing host file ownership.
    # Neo4j runs as uid 7474; it must be able to read the mounted secret.
    # Mode 0444 is safe here because its enclosing host directory is 0700.
    if os.name != "nt":
        path.chmod(0o444)
    load_auth(path)
    return True


def main() -> int:
    try:
        created = create_secret()
    except (OSError, ValueError) as exc:
        print(f"[FAIL] Local bootstrap: {exc}")
        return 1
    label = "created" if created else "already exists"
    print(f"[OK] Neo4j local auth secret {label}: secrets/neo4j_auth.txt")
    print("Credentials were not printed. Do not commit, upload, or share the secret.")
    print("Next: docker compose up -d; python scripts/smoke.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
