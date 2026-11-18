"""v0.13.1: isolated offline Neo4j Community restore/load consistency drill.

Explicit opt-in only. Never uses Compose, the live graph volume, ports,
network access or a supplied destination volume. A fresh random Docker
volume is created, checked, and removed. A passing offline load/check
is NOT a successful authenticated service restore or an RPO/RTO proof.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import time

from services.research_api.offline_backup_v0130 import (
    CHUNK_SIZE, PINNED_IMAGE, _canonical, _owner_only, _parents_safe,
    _regular_descriptor, read_private_manifest, verify_offline_dump_manifest,
)

VERSION = "0.13.1"
ADMIN_IMAGE = "neo4j/neo4j-admin:2026.10.1"
VOLUME_PREFIX = "dviros-neo-restore-drill-"
MAX_REPORT_BYTES = 8192
LOAD_TIMEOUT = 7200
CHECK_TIMEOUT = 1800
DOCKER_TIMEOUT = 45
LABEL = "dviros.neo.restore-drill"


def _validate_output(output: Path) -> None:
    output = Path(output)
    if not output.is_absolute() or output.suffix != ".json":
        raise ValueError("Use an absolute private JSON report destination.")
    _parents_safe(output)
    _owner_only(output, is_output=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError("Restore drill report already exists.")


def plan_isolated_restore_drill(archive: Path, manifest_path: Path) -> dict:
    """Verify the exact dump bytes without making any Docker calls."""
    archive = Path(archive)
    manifest = read_private_manifest(Path(manifest_path))
    result = verify_offline_dump_manifest(manifest, archive)
    return {
        "schema_version": VERSION,
        "contract_kind": "dviros.neo.isolated_offline_restore_drill",
        "database": "neo4j",
        "database_image": PINNED_IMAGE,
        "offline_admin_image": ADMIN_IMAGE,
        "archive_filename": manifest["manifest"]["archive_filename"],
        "archive_bytes": result["archive_bytes"],
        "archive_sha256": manifest["manifest"]["archive_sha256"],
        "archive_integrity_verified": True,
        "execution_enabled": False,
        "docker_network_enabled": False,
        "host_live_volume_mounted": False,
        "existing_docker_volume_reused": False,
        "isolated_load_and_consistency_checked": False,
        "authenticated_restored_service_smoke_passed": False,
        "rpo_rto_demonstrated": False,
        "research_release_status": "HOLD",
    }


def _run_docker(args: list[str], *, timeout: int = DOCKER_TIMEOUT,
                capture: bool = False) -> subprocess.CompletedProcess:
    # Never use a shell, Docker Compose, network or any host data directory.
    return subprocess.run(
        ["docker", *args], check=False, timeout=timeout,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        text=capture,
    )


def _volume_args(volume: str) -> list[str]:
    if not volume.startswith(VOLUME_PREFIX) or len(volume) != len(VOLUME_PREFIX) + 24:
        raise ValueError("Unexpected isolated volume identifier.")
    return [
        "--rm", "--network", "none", "--pull", "never",
        "--pids-limit", "256",
        "--mount", "type=volume,src=" + volume + ",dst=/data,volume-nocopy",
        ADMIN_IMAGE,
    ]


def _load_dump(archive: Path, volume: str) -> None:
    """Stream the verified archive to stdin of an isolated, fixed admin image."""
    command = [
        "docker", "run", "--interactive", *_volume_args(volume),
        "neo4j-admin", "database", "load", "neo4j", "--from-stdin",
    ]
    fd, before = _regular_descriptor(archive)
    proc = None
    try:
        proc = subprocess.Popen(
            command, stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if proc.stdin is None:
            raise RuntimeError("Docker restore stdin unavailable.")
        with os.fdopen(fd, "rb") as source:
            fd = -1
            remaining = before.st_size
            while remaining:
                block = source.read(min(CHUNK_SIZE, remaining))
                if not block:
                    raise RuntimeError("Offline archive truncated during load.")
                proc.stdin.write(block)
                remaining -= len(block)
            if source.read(1):
                raise RuntimeError("Offline archive grew during load.")
            if (
                source.fileno() < 0
                or source.tell() != before.st_size
                or os.fstat(source.fileno()).st_size != before.st_size
            ):
                raise RuntimeError("Offline archive changed during load.")
        proc.stdin.close()
        if proc.wait(timeout=LOAD_TIMEOUT) != 0:
            raise RuntimeError("Isolated Neo4j offline load failed.")
    except BaseException:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        raise
    finally:
        if fd >= 0:
            os.close(fd)


def _check_restored_store(volume: str) -> None:
    command = [
        "run", *_volume_args(volume),
        "neo4j-admin", "database", "check", "neo4j",
    ]
    result = _run_docker(command, timeout=CHECK_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError("Isolated Neo4j offline consistency check failed.")


def _write_report(path: Path, report: dict) -> None:
    _validate_output(path)
    payload = _canonical(report) + b"\n"
    if len(payload) > MAX_REPORT_BYTES:
        raise ValueError("Isolated restore report exceeds size budget.")
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
        getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def execute_isolated_restore_drill(
    archive: Path, manifest_path: Path, report_path: Path, *,
    acknowledged: bool,
) -> dict:
    """Load and check only a newly created isolated volume; remove it even on failure.

    Requires local pinned neo4j/neo4j-admin image and Docker permissions.
    This is a *real* offline load + consistency check when invoked, but it
    never authenticates a running restored service or demonstrates RPO/RTO.
    """
    if acknowledged is not True:
        raise ValueError("Explicit isolated-restore acknowledgment required.")
    archive = Path(archive)
    report_path = Path(report_path)
    _validate_output(report_path)
    plan = plan_isolated_restore_drill(archive, Path(manifest_path))
    token = secrets.token_hex(12)
    volume = VOLUME_PREFIX + token
    # Refuse even an astronomically unlikely collision: 'create' is idempotent.
    inspection = _run_docker(["volume", "inspect", volume], capture=True)
    if inspection.returncode == 0:
        raise RuntimeError("Drill volume identifier already exists.")
    # Nonzero may mean daemon permission failure rather than 'not found'.
    # Creation of an idempotent Docker volume must not follow such a failure.
    diagnostic = (inspection.stderr or "").lower()
    if "no such volume" not in diagnostic and "not found" not in diagnostic:
        raise RuntimeError("Could not establish that drill volume is unused.")
    start = time.monotonic()
    created = False
    completed = False
    cleanup_ok = False
    try:
        made = _run_docker([
            "volume", "create", "--driver", "local",
            "--label", LABEL + "=v0.13.1",
            "--name", volume,
        ], capture=True)
        if made.returncode != 0:
            raise RuntimeError("Could not create isolated restore volume.")
        # A successful Docker create can still return unexpected output;
        # mark ownership for cleanup before refusing to continue.
        created = True
        if made.stdout.strip() != volume:
            raise RuntimeError("Unexpected Docker volume creation result.")
        _load_dump(archive, volume)
        _check_restored_store(volume)
        # Hash a second time: no silently changed archive after streaming.
        verified_again = verify_offline_dump_manifest(
            read_private_manifest(Path(manifest_path)), archive,
        )
        if verified_again["archive_bytes"] != plan["archive_bytes"]:
            raise RuntimeError("Archive changed after isolated restore.")
        completed = True
    finally:
        if created:
            cleaned = _run_docker(["volume", "rm", volume])
            cleanup_ok = cleaned.returncode == 0
    if not (completed and cleanup_ok):
        raise RuntimeError("Isolated restore drill or cleanup incomplete.")
    duration = round(time.monotonic() - start, 3)
    body = {
        **plan,
        "execution_enabled": True,
        "isolated_volume_created": True,
        "isolated_volume_removed": True,
        "isolated_load_and_consistency_checked": True,
        "offline_elapsed_seconds": duration,
        # No online database start, authenticated reads or recovery objectives.
        "authenticated_restored_service_smoke_passed": False,
        "end_to_end_restore_drill_passed": False,
        "rpo_rto_demonstrated": False,
        "research_release_status": "HOLD",
    }
    receipt = {
        "report": body,
        "report_sha256": sha256(_canonical(body)).hexdigest(),
        "report_digitally_signed": False,
    }
    _write_report(report_path, receipt)
    return {
        "schema_version": VERSION,
        "offline_load_and_consistency_passed": True,
        "isolated_volume_removed": True,
        "offline_elapsed_seconds": duration,
        "authenticated_restored_service_smoke_passed": False,
        "end_to_end_restore_drill_passed": False,
        "rpo_rto_demonstrated": False,
        "research_release_status": "HOLD",
    }
