#!/usr/bin/env python3
"""Versioned idempotent Neo4j ontology migration runner (standard library).

Usage:
  python scripts/migrate.py dry-run  # no database connection
  python scripts/migrate.py apply    # local Docker Neo4j only
  python scripts/migrate.py check    # all declared migrations applied?

Only shipped CREATE ... IF NOT EXISTS schema statements are accepted.
No DDL is rolled back automatically; check documentation before upgrades.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import re
from urllib import error, request

try:
    from scripts.bootstrap import DEFAULT_SECRET_PATH, load_auth
    from scripts.smoke import NoRedirect, query_url
except ModuleNotFoundError:
    from bootstrap import DEFAULT_SECRET_PATH, load_auth
    from smoke import NoRedirect, query_url

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO_ROOT / "research_graph" / "migrations"
FILE_NAME = re.compile(r"^[0-9]{3}_[a-z0-9_]+\.cypher$")
ID_NAME = re.compile(r"^[0-9]{3}$")
ALLOWED_DDL = re.compile(r"^CREATE\s+(?:CONSTRAINT|INDEX)\s+\w+\s+IF\s+NOT\s+EXISTS\b", re.IGNORECASE)


@dataclass(frozen=True)
class Migration:
    id: str
    file_name: str
    version: str
    checksum: str
    statements: tuple[str, ...]


def parse_statements(raw: str) -> tuple[str, ...]:
    """Only line comments are allowed; semicolons delimit individual DDL."""
    if "\x00" in raw or "/*" in raw or "*/" in raw:
        raise ValueError("Invalid migration source.")
    text = "\n".join(
        line for line in raw.splitlines() if not line.lstrip().startswith("//")
    ).strip()
    if not text.endswith(";"):
        raise ValueError("Every migration statement must end with a semicolon.")
    statements = tuple(piece.strip() for piece in text.split(";") if piece.strip())
    if not statements:
        raise ValueError("Empty migration file.")
    if any(not ALLOWED_DDL.match(stmt) for stmt in statements):
        raise ValueError("Only idempotent CREATE INDEX/CONSTRAINT IF NOT EXISTS is allowed.")
    return statements


def load_migrations(directory: Path = MIGRATIONS) -> list[Migration]:
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Migration directory must not be a symlink.")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Migration manifest must not be a symlink.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = manifest["schema_version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid schema version.")
    result: list[Migration] = []
    for item in manifest["migrations"]:
        id_value = item["id"]
        path_name = item["path"]
        if not ID_NAME.fullmatch(id_value) or not FILE_NAME.fullmatch(path_name):
            raise ValueError("Invalid migration ID or path.")
        if not path_name.startswith(id_value + "_"):
            raise ValueError("Migration ID and filename mismatch.")
        path = directory / path_name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Migration source must be a regular file.")
        source = path.read_bytes()
        try:
            statements = parse_statements(source.decode("utf-8"))
        except UnicodeError as exc:
            raise ValueError("Migration must use UTF-8.") from exc
        result.append(Migration(id_value, path_name, version,
                                hashlib.sha256(source).hexdigest(), statements))
    ids = [item.id for item in result]
    if not ids or ids != sorted(set(ids)):
        raise ValueError("Manifest migrations must have unique ascending IDs.")
    disk = {item.name for item in directory.glob("[0-9][0-9][0-9]_*.cypher")}
    if disk != {item.file_name for item in result}:
        raise ValueError("Manifest must enumerate every migration file.")
    return result


class LocalQueryClient:
    """Only the loopback Query API is supported. No proxy or redirects."""

    def __init__(self, base_url: str, secret_path: Path):
        self.endpoint = query_url(base_url)
        username, password = load_auth(secret_path)
        auth = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self.headers = {
            "Authorization": "Basic " + auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def query(self, statement: str, params: dict | None = None) -> list:
        payload = json.dumps({"statement": statement, "parameters": params or {}}).encode("utf-8")
        req = request.Request(self.endpoint, data=payload, method="POST", headers=self.headers)
        try:
            with self.opener.open(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
                if response.status != 202:
                    raise RuntimeError(f"Neo4j Query API returned HTTP {response.status}.")
        except error.HTTPError as exc:
            # Do not log body: may contain source information, query or credentials.
            raise RuntimeError(f"Neo4j query rejected with HTTP {exc.code}.") from None
        if body.get("errors"):
            # Neo4j may report HTTP 202 with query-level errors.
            codes = [str(e.get("code", "unknown")) for e in body["errors"]]
            raise RuntimeError("Neo4j query failed: " + ", ".join(codes))
        return body.get("data", {}).get("values", [])


def applied_checksum(client: LocalQueryClient, migration_id: str) -> str | None:
    rows = client.query(
        "MATCH (m:SchemaMigration {id: $id}) RETURN m.checksum AS checksum",
        {"id": migration_id},
    )
    if len(rows) > 1:
        raise RuntimeError("Schema migration marker is duplicated.")
    return rows[0][0] if rows else None


def migrate(migrations: list[Migration], client: LocalQueryClient | None,
            mode: str) -> bool:
    """Return True when the full manifest is applied and checksums match."""
    if mode == "dry-run":
        for migration in migrations:
            print(f"[PLAN] {migration.id} {migration.file_name}: "
                  f"{len(migration.statements)} statements SHA256={migration.checksum[:12]}")
        return True

    if client is None:
        raise ValueError("A database client is required for apply/check modes.")

    # Check *all* markers before writing, fail closed on tampering or gaps.
    existing = {m.id: applied_checksum(client, m.id) for m in migrations}
    for migration in migrations:
        checksum = existing[migration.id]
        if checksum and checksum != migration.checksum:
            raise RuntimeError(f"Migration {migration.id} changed after being applied.")
    seen_gap = False
    for migration in migrations:
        if existing[migration.id] is None:
            seen_gap = True
        elif seen_gap:
            raise RuntimeError("Out-of-order migration markers; manual review required.")

    if mode == "check":
        missing = [m.id for m in migrations if existing[m.id] is None]
        if missing:
            print("[INCOMPLETE] Missing migrations: " + ", ".join(missing))
            return False
        print(f"[OK] All {len(migrations)} migrations are applied and checksums match.")
        return True

    if mode != "apply":
        raise ValueError("Unsupported migration mode.")
    for migration in migrations:
        if existing[migration.id] is not None:
            print(f"[SKIP] {migration.id} already applied; checksum verified.")
            continue
        for statement in migration.statements:
            client.query(statement)
        rows = client.query(
            "MERGE (m:SchemaMigration {id: $id}) "
            "ON CREATE SET m.checksum = $checksum, "
            "m.schema_version = $schema_version, "
            "m.statement_count = $statement_count, "
            "m.applied_at = datetime() "
            "RETURN m.checksum AS checksum",
            {
                "id": migration.id, "checksum": migration.checksum,
                "schema_version": migration.version,
                "statement_count": len(migration.statements),
            },
        )
        if rows != [[migration.checksum]]:
            raise RuntimeError(f"Migration {migration.id} marker mismatch.")
        print(f"[APPLIED] {migration.id} {migration.file_name}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["dry-run", "apply", "check"])
    parser.add_argument("--url", default="http://127.0.0.1:7474")
    parser.add_argument("--secret", type=Path, default=DEFAULT_SECRET_PATH)
    args = parser.parse_args()
    try:
        migrations = load_migrations()
        client = None if args.mode == "dry-run" else LocalQueryClient(args.url, args.secret)
        return 0 if migrate(migrations, client, args.mode) else 1
    except (ValueError, OSError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
        print(f"[FAIL] Ontology migration: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
