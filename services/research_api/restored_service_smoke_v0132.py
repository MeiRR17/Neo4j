"""v0.13.2: authenticated, local-only read smoke on an isolated restored DBMS.

Operator opt-in only. Reuses v0.13.1 private offline load/consistency gates,
then starts a disposable Neo4j container on --network none, with no port
publication and a random per-run credential. Fixed read-only cypher-shell
queries measure graph/schema counts and compare operator-supplied minima.
Neither source DB nor DvirOS is contacted. This is NOT trusted RPO/RTO.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from services.research_api.offline_backup_v0130 import (
    PINNED_IMAGE, _canonical, read_private_manifest,
    verify_offline_dump_manifest,
)
from services.research_api.isolated_restore_v0131 import (
    VOLUME_PREFIX, _check_restored_store, _load_dump, _run_docker,
    _validate_output, _write_report, plan_isolated_restore_drill,
)

VERSION = "0.13.2"
CONTAINER_PREFIX = "dviros-neo-restored-smoke-"
MAX_COUNT = 2**63 - 1
START_TIMEOUT = 180
QUERY_TIMEOUT = 35
DOCKER_TIMEOUT = 50
QUERIES = (
    ("ping", "RETURN 1 AS result"),
    ("nodes", "MATCH (n) RETURN count(n) AS result"),
    ("relationships", "MATCH ()-[r]->() RETURN count(r) AS result"),
    ("passages", "MATCH (p:Passage) RETURN count(p) AS result"),
    ("source_records", "MATCH (s:SourceRecord) RETURN count(s) AS result"),
    ("constraints", "SHOW CONSTRAINTS YIELD name RETURN count(*) AS result"),
)
COUNTS = frozenset({"nodes", "relationships", "passages", "source_records", "constraints"})


def _minimums(value: object) -> dict[str, int]:
    """Accept only a bounded explicit threshold map; never Cypher or labels."""
    if type(value) is not dict or set(value) != COUNTS:
        raise ValueError("Five exact read-only count thresholds are required.")
    if any(type(n) is not int or not 0 <= n <= MAX_COUNT for n in value.values()):
        raise ValueError("Invalid minimum recovery count.")
    if not any(n > 0 for n in value.values()):
        raise ValueError("At least one nonzero expected recovered count is required.")
    return {name: value[name] for name in sorted(COUNTS)}


def plan_restored_service_smoke(
    archive: Path, manifest_path: Path, *, minimum_counts: dict,
) -> dict:
    limits = _minimums(minimum_counts)
    base = plan_isolated_restore_drill(Path(archive), Path(manifest_path))
    return {
        "schema_version": VERSION,
        "contract_kind": "dviros.neo.isolated_restored_service_smoke",
        "database": "neo4j",
        "neo4j_image": PINNED_IMAGE,
        "archive_sha256": base["archive_sha256"],
        "archive_bytes": base["archive_bytes"],
        "operator_minimum_counts": limits,
        "fixed_read_queries": [name for name, _ in QUERIES],
        "archive_integrity_verified": True,
        "docker_operations_performed": False,
        "network_access_enabled": False,
        "host_ports_published": False,
        "live_compose_volume_mounted": False,
        "restored_service_authenticated": False,
        "restored_read_smoke_passed": False,
        "verified_against_trusted_live_baseline": False,
        "rpo_rto_demonstrated": False,
        "research_release_status": "HOLD",
    }


def _docker(args: list[str], *, timeout: int = DOCKER_TIMEOUT,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    # Never invoke a shell or capture potentially private container logs.
    return subprocess.run(
        ["docker", *args], check=False, timeout=timeout,
        env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def _missing(kind: str, name: str) -> None:
    result = _docker([kind, "inspect", name])
    if result.returncode == 0:
        raise RuntimeError("Isolated Docker resource name already exists.")
    diagnostic = (result.stderr or "").lower()
    if not (
        "no such " + ("volume" if kind == "volume" else "container") in diagnostic
        or "not found" in diagnostic
    ):
        raise RuntimeError("Cannot confirm isolated Docker resource is absent.")


def _scalar(stdout: str) -> int:
    """Refuse ambiguous cypher-shell output instead of guessing success."""
    if type(stdout) is not str or len(stdout) > 1024:
        raise RuntimeError("Unexpected private scalar smoke output.")
    rows = [row.strip() for row in stdout.splitlines() if row.strip()]
    if len(rows) == 2 and rows[0] == "result":
        rows = rows[1:]
    if len(rows) != 1 or not re.fullmatch(r"[0-9]{1,19}", rows[0]):
        raise RuntimeError("Unexpected read-only count response.")
    count = int(rows[0])
    if count > MAX_COUNT:
        raise RuntimeError("Graph count exceeds bounded recovery response.")
    return count


def _query(container: str, password: str, cypher: str) -> int:
    """Only fixed module-supplied queries; authenticate within isolated loopback."""
    if cypher not in dict(QUERIES).values():
        raise ValueError("Unregistered read query.")
    # Password is placed in the subprocess environment, not argv or stdout.
    # Docker administrators can still inspect temporary container environment.
    env = {
        **os.environ, "NEO4J_PASSWORD": password,
        "NEO4J_USERNAME": "neo4j",
    }
    result = _docker(
        [
            "exec", "--env", "NEO4J_PASSWORD",
            "--env", "NEO4J_USERNAME", container,
            "cypher-shell", "--address", "bolt://localhost:7687",
            "--database", "neo4j", "--access-mode", "read",
            "--format", "plain", "--non-interactive", cypher,
        ],
        env=env, timeout=QUERY_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError("Authenticated isolated read query failed.")
    return _scalar(result.stdout)


def _wait_until_ready(container: str, password: str) -> None:
    deadline = time.monotonic() + START_TIMEOUT
    while True:
        try:
            if _query(container, password, QUERIES[0][1]) == 1:
                return
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Isolated restored service did not become ready.")
        time.sleep(2)


def _start_isolated_service(volume: str, container: str,
                            password: str) -> None:
    # Pinned image must already be local. No network, published port,
    # host database bind or Compose project. --env transfers the secret
    # from this process's environment instead of command-line arguments.
    env = {**os.environ, "NEO4J_AUTH": "neo4j/" + password}
    result = _docker([
        "run", "--detach", "--name", container,
        "--network", "none", "--pull", "never",
        "--pids-limit", "256",
        "--memory", "3g",
        "--mount", "type=volume,src=" + volume + ",dst=/data,volume-nocopy",
        "--env", "NEO4J_AUTH",
        "--env", "NEO4J_server_memory_heap_initial__size=256m",
        "--env", "NEO4J_server_memory_heap_max__size=768m",
        "--env", "NEO4J_server_memory_pagecache_size=256m",
        PINNED_IMAGE,
    ], timeout=75, env=env)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("Could not start the isolated restored DBMS.")


def execute_restored_service_smoke(
    archive: Path, manifest_path: Path, report_path: Path, *,
    minimum_counts: dict, acknowledged: bool,
) -> dict:
    """Run bounded read-only smoke; remove both container and volume.

    No success report is written until both resources were removed.
    """
    if acknowledged is not True:
        raise ValueError("Explicit restored DBMS execution acknowledgment required.")
    _validate_output(Path(report_path))
    plan = plan_restored_service_smoke(
        Path(archive), Path(manifest_path), minimum_counts=minimum_counts,
    )
    suffix = secrets.token_hex(12)
    volume = VOLUME_PREFIX + suffix
    container = CONTAINER_PREFIX + suffix
    _missing("volume", volume)
    _missing("container", container)
    password = secrets.token_urlsafe(36)
    start = time.monotonic()
    volume_created = False
    container_started = False
    cleanup_container = False
    cleanup_volume = False
    readings = {}
    error = None
    try:
        created = _run_docker([
            "volume", "create", "--driver", "local",
            "--label", "dviros.neo.restore-drill=v0.13.2",
            "--name", volume,
        ], capture=True)
        if created.returncode != 0:
            raise RuntimeError("Isolated restore volume creation failed.")
        volume_created = True
        if created.stdout.strip() != volume:
            raise RuntimeError("Unexpected isolated volume identity.")
        _load_dump(Path(archive), volume)
        _check_restored_store(volume)
        # Docker may create a container even if 'run' returns an error.
        # Flag it for cleanup before invoking start.
        container_started = True
        _start_isolated_service(volume, container, password)
        _wait_until_ready(container, password)
        for key, query in QUERIES[1:]:
            readings[key] = _query(container, password, query)
            if readings[key] < plan["operator_minimum_counts"][key]:
                raise RuntimeError("Restored graph count below explicit operator baseline.")
        # Existing dump and manifest remain unchanged after recovery.
        verified = verify_offline_dump_manifest(
            read_private_manifest(Path(manifest_path)), Path(archive),
        )
        if verified["archive_bytes"] != plan["archive_bytes"]:
            raise RuntimeError("Source archive changed after recovery.")
    except BaseException as exc:
        error = exc
    finally:
        if container_started:
            cleanup_container = _docker(
                ["container", "rm", "--force", container], timeout=90,
            ).returncode == 0
        if volume_created:
            cleanup_volume = _docker(
                ["volume", "rm", volume], timeout=75,
            ).returncode == 0
    if error is not None:
        if not (cleanup_container or not container_started) or not (
            cleanup_volume or not volume_created
        ):
            raise RuntimeError("Restore validation failed and cleanup is incomplete.") from error
        raise error
    if not (cleanup_container and cleanup_volume):
        raise RuntimeError("Restored test service or volume cleanup incomplete.")
    elapsed = round(time.monotonic() - start, 3)
    record = {
        **plan,
        "docker_operations_performed": True,
        "restored_service_authenticated": True,
        "restored_read_smoke_passed": True,
        "observed_counts": readings,
        "operator_minimums_satisfied": True,
        "offline_consistency_check_passed": True,
        "isolated_container_removed": True,
        "isolated_volume_removed": True,
        "recovery_drill_elapsed_seconds": elapsed,
        "verified_against_trusted_live_baseline": False,
        "rpo_rto_demonstrated": False,
        "research_release_status": "HOLD",
    }
    receipt = {
        "report": record,
        "report_sha256": sha256(_canonical(record)).hexdigest(),
        "report_digitally_signed": False,
    }
    _write_report(Path(report_path), receipt)
    return {
        "schema_version": VERSION,
        "authenticated_restored_read_smoke_passed": True,
        "observed_counts": readings,
        "isolated_resources_removed": True,
        "recovery_drill_elapsed_seconds": elapsed,
        "rpo_rto_demonstrated": False,
        "research_release_status": "HOLD",
    }
