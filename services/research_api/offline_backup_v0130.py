"""v0.13.0: fail-closed offline integrity manifest for local Neo4j dumps.

This module does NOT invoke neo4j-admin, stop the database, restore data,
verify Neo4j archive format or certify RPO/RTO. An operator must generate an
offline Community dump separately. The manifest binds its exact bytes and
version context for an *isolated* later restore drill, never production.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

VERSION = "0.13.0"
MAX_DUMP_BYTES = 512 * 1024**3
MAX_MANIFEST_BYTES = 16_384
CHUNK_SIZE = 1024 * 1024
PINNED_IMAGE = "neo4j:2026.10.1"
DATABASE = "neo4j"
NAME_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}\.dump\Z")
HEX_RE = re.compile(r"[0-9a-f]{64}\Z")
PAYLOAD_FIELDS = frozenset({
    "schema_version", "contract_kind", "database", "archive_filename",
    "archive_bytes", "archive_sha256", "neo4j_image",
    "archive_source_kind", "offline_stop_operator_attested",
    "database_stop_independently_verified", "dump_format_verified",
    "isolated_restore_drill_passed", "rpo_rto_demonstrated",
    "immutable_graph_snapshot_verified", "source_rights_verified",
    "research_release_status", "note",
})
RECEIPT_FIELDS = frozenset({"manifest", "manifest_sha256"})


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _parents_safe(path: Path) -> None:
    """No symlink or non-directory components, including all ancestors."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Use an absolute path with no parent traversal.")
    current = path.parent
    while True:
        mode = current.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise ValueError("Symlinked or non-directory archive parent.")
        if current == current.parent:
            break
        current = current.parent


def _owner_only(path: Path, *, is_output: bool = False) -> None:
    """Reject broad POSIX access; Windows ACLs need manual inspection."""
    if os.name == "nt":
        return
    parent_mode = stat.S_IMODE(path.parent.stat().st_mode)
    if parent_mode & 0o077:
        raise ValueError("Private backup parent must be owner-only (0700).")
    if not is_output:
        mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
        if mode & 0o077:
            raise ValueError("Private backup must have no group/world permissions.")


def _regular_descriptor(path: Path) -> tuple[int, os.stat_result]:
    _parents_safe(path)
    _owner_only(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size <= 0 or info.st_size > MAX_DUMP_BYTES
        ):
            raise ValueError("Backup is not a bounded single-link regular file.")
        return fd, info
    except BaseException:
        os.close(fd)
        raise


def _stamp(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _verified_bytes(path: Path, *, max_bytes: int) -> bytes:
    fd, original = _regular_descriptor(path)
    try:
        if original.st_size > max_bytes:
            raise ValueError("Private manifest too large.")
        with os.fdopen(fd, "rb") as source:
            data = source.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("Private manifest too large.")
            after = os.fstat(source.fileno())
            if _stamp(original) != _stamp(after):
                raise ValueError("Private manifest changed while reading.")
        on_disk = path.stat(follow_symlinks=False)
        if _stamp(original) != _stamp(on_disk):
            raise ValueError("Private manifest path changed while reading.")
        return data
    except BaseException:
        # fdopen closes on both success and failure once entered.
        raise


def _hash_archive(path: Path) -> tuple[int, str]:
    if not NAME_RE.fullmatch(path.name):
        raise ValueError("Expected a bounded .dump filename.")
    fd, original = _regular_descriptor(path)
    digest = sha256()
    try:
        with os.fdopen(fd, "rb") as stream:
            remaining = original.st_size
            while remaining:
                chunk = stream.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ValueError("Neo4j dump truncated during hashing.")
                digest.update(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise ValueError("Neo4j dump grew during hashing.")
            if _stamp(original) != _stamp(os.fstat(stream.fileno())):
                raise ValueError("Neo4j dump changed during hashing.")
        if _stamp(original) != _stamp(path.stat(follow_symlinks=False)):
            raise ValueError("Neo4j dump path changed during hashing.")
        return original.st_size, digest.hexdigest()
    except BaseException:
        raise


def _require_valid_receipt(value: object) -> dict:
    if type(value) is not dict or set(value) != RECEIPT_FIELDS:
        raise ValueError("Backup manifest envelope has unexpected fields.")
    data = value["manifest"]
    if type(data) is not dict or set(data) != PAYLOAD_FIELDS:
        raise ValueError("Backup manifest fields incomplete or unexpected.")
    if (
        data["schema_version"] != VERSION
        or data["contract_kind"] != "dviros.neo.offline_dump_integrity"
        or data["database"] != DATABASE
        or data["neo4j_image"] != PINNED_IMAGE
        or data["archive_source_kind"] != "operator_supplied_offline_dump"
        or type(data["archive_filename"]) is not str
        or not NAME_RE.fullmatch(data["archive_filename"])
        or type(data["archive_bytes"]) is not int
        or not 0 < data["archive_bytes"] <= MAX_DUMP_BYTES
        or type(data["archive_sha256"]) is not str
        or not HEX_RE.fullmatch(data["archive_sha256"])
        or data["offline_stop_operator_attested"] is not True
        or any(data[field] is not False for field in (
            "database_stop_independently_verified", "dump_format_verified",
            "isolated_restore_drill_passed", "rpo_rto_demonstrated",
            "immutable_graph_snapshot_verified", "source_rights_verified",
        ))
        or data["research_release_status"] != "HOLD"
        or type(data["note"]) is not str
        or len(data["note"]) > 600
    ):
        raise ValueError("Backup manifest violates strict offline trust contract.")
    raw = _canonical(data)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Backup manifest exceeds allowed size.")
    digest = sha256(raw).hexdigest()
    if type(value["manifest_sha256"]) is not str or not HEX_RE.fullmatch(
        value["manifest_sha256"]
    ) or value["manifest_sha256"] != digest:
        raise ValueError("Backup metadata checksum invalid.")
    return data


def create_offline_dump_manifest(
    archive: Path, *, operator_stopped_database: bool,
) -> dict:
    """Compute checksum of pre-existing private offline dump, no DB access."""
    if operator_stopped_database is not True:
        raise ValueError("Explicit operator-confirmed offline stop required.")
    archive = Path(archive)
    size, digest = _hash_archive(archive)
    data = {
        "schema_version": VERSION,
        "contract_kind": "dviros.neo.offline_dump_integrity",
        "database": DATABASE,
        "archive_filename": archive.name,
        "archive_bytes": size,
        "archive_sha256": digest,
        "neo4j_image": PINNED_IMAGE,
        "archive_source_kind": "operator_supplied_offline_dump",
        "offline_stop_operator_attested": True,
        "database_stop_independently_verified": False,
        "dump_format_verified": False,
        "isolated_restore_drill_passed": False,
        "rpo_rto_demonstrated": False,
        "immutable_graph_snapshot_verified": False,
        "source_rights_verified": False,
        "research_release_status": "HOLD",
        "note": (
            "Checksum of an existing operator-supplied private .dump only; "
            "no database stop, Neo4j format, isolated restore, RPO/RTO, "
            "licensing or authentic snapshot has been independently proven."
        ),
    }
    return {"manifest": data, "manifest_sha256": sha256(_canonical(data)).hexdigest()}


def verify_offline_dump_manifest(
    value: object, archive: Path, *,
    expected_image: str = PINNED_IMAGE,
) -> dict:
    """Verify original bytes against exact manifest with no graph connection."""
    data = _require_valid_receipt(value)
    if expected_image != PINNED_IMAGE:
        raise ValueError("Expected Neo4j image differs from pinned release.")
    archive = Path(archive)
    if archive.name != data["archive_filename"]:
        raise ValueError("Neo4j dump filename differs from manifest.")
    size, digest = _hash_archive(archive)
    if size != data["archive_bytes"] or digest != data["archive_sha256"]:
        raise ValueError("Neo4j dump content does not match manifest.")
    return {
        "schema_version": VERSION,
        "integrity_sha256_verified": True,
        "archive_bytes": size,
        "neo4j_image": PINNED_IMAGE,
        "database_stop_independently_verified": False,
        "neo4j_dump_format_verified": False,
        "isolated_restore_drill_passed": False,
        "rpo_rto_demonstrated": False,
        "ready_for_production_restore": False,
        "research_release_status": "HOLD",
    }


def read_private_manifest(path: Path) -> dict:
    """Reject noncanonical JSON and duplicate keys before trusting fields."""
    def unique(items: list[tuple[str, object]]) -> dict:
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("Duplicate JSON key in backup manifest.")
            result[k] = v
        return result
    raw = _verified_bytes(Path(path), max_bytes=MAX_MANIFEST_BYTES)
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                            parse_constant=lambda x: (_ for _ in ()).throw(
                                ValueError("Non-finite JSON value.")
                            ))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Malformed private backup manifest.") from None
    _require_valid_receipt(parsed)
    if raw != _canonical(parsed) + b"\n":
        raise ValueError("Private backup manifest is not canonical JSON.")
    return parsed


def create_private_manifest_file(path: Path, value: object) -> None:
    """Write once, using O_EXCL, under an owner-only local backup directory."""
    _require_valid_receipt(value)
    path = Path(path)
    if path.suffix != ".json":
        raise ValueError("Expected private JSON output filename.")
    _parents_safe(path)
    _owner_only(path, is_output=True)
    raw = _canonical(value) + b"\n"
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Backup manifest output too large.")
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL |
        getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
