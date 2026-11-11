"""v0.9.12 bounded audit-observation revision ledger (metadata-only).

One Neo4j auto-commit statement appends a linked receipt and updates the
corresponding AuditRevisionHead under a write lock and CAS precondition.
This prevents cooperating callers from silently advancing a stale head.
It does not lock Work/Evidence writers or establish graph immutability,
transaction snapshots, rights approval, or a production RBAC boundary.
"""
from __future__ import annotations

from hashlib import sha256
import hmac
import re
import time

from research_graph.ontology import require_canonical_id
from services.research_api.audit_export_v0911 import (
    canonical_bytes, verify_audit_export,
)

VERSION = "0.9.12"
MAX_REVISIONS = 32
ZERO_CHAIN = "0" * 64
CHAIN_DOMAIN = b"dviros/audit-observation-revision/v0.9.12\n"
HEX = re.compile(r"^[0-9a-f]{64}$")

HEAD_FIELDS = (
    "id", "source_work_id", "target_work_id", "sequence",
    "latest_revision_id", "chain_sha256",
)
RECORD_FIELDS = (
    "scope_id", "sequence", "previous_revision_id",
    "previous_chain_sha256", "manifest_sha256", "source_work_id",
    "target_work_id", "observed_link_count", "captured_at_unix",
    "recorded_at_unix", "query_template_sha256",
)
RECORD_COLUMNS = ("id", *RECORD_FIELDS, "chain_sha256")
HEAD_READ = """
MATCH (h:AuditRevisionHead {id:$scope_id})
RETURN h.id, h.source_work_id, h.target_work_id, h.sequence,
       h.latest_revision_id, h.chain_sha256
""".strip()
BOOTSTRAP = """
MERGE (h:AuditRevisionHead {id:$scope_id})
ON CREATE SET h.source_work_id=$source, h.target_work_id=$target,
              h.sequence=0, h.latest_revision_id='',
              h.chain_sha256=$zero
RETURN h.id, h.source_work_id, h.target_work_id, h.sequence,
       h.latest_revision_id, h.chain_sha256
""".strip()
APPEND = """
MATCH (h:AuditRevisionHead {id:$scope_id})
SET h.sequence = h.sequence
WITH h
WHERE h.sequence=$expected_sequence
  AND h.chain_sha256=$expected_chain
  AND h.latest_revision_id=$previous_revision_id
  AND h.source_work_id=$source_work_id
  AND h.target_work_id=$target_work_id
CREATE (r:AuditRevision {
  id:$revision_id, scope_id:$scope_id, sequence:$sequence,
  previous_revision_id:$previous_revision_id,
  previous_chain_sha256:$previous_chain_sha256,
  manifest_sha256:$manifest_sha256,
  source_work_id:$source_work_id, target_work_id:$target_work_id,
  observed_link_count:$observed_link_count,
  captured_at_unix:$captured_at_unix,
  recorded_at_unix:$recorded_at_unix,
  query_template_sha256:$query_template_sha256,
  chain_sha256:$chain_sha256
})
SET h.sequence=$sequence,
    h.latest_revision_id=$revision_id,
    h.chain_sha256=$chain_sha256
RETURN h.sequence, h.latest_revision_id, h.chain_sha256
""".strip()
HISTORY_READ = """
MATCH (r:AuditRevision {scope_id:$scope_id})
RETURN r.id, r.scope_id, r.sequence, r.previous_revision_id,
       r.previous_chain_sha256, r.manifest_sha256,
       r.source_work_id, r.target_work_id, r.observed_link_count,
       r.captured_at_unix, r.recorded_at_unix,
       r.query_template_sha256, r.chain_sha256
ORDER BY r.sequence
LIMIT $fetch_limit
""".strip()


class RevisionLedgerError(ValueError):
    """Invalid, stale or over-budget ledger action; never echo data values."""


def _hex(value: object) -> str:
    if type(value) is not str or not HEX.fullmatch(value):
        raise RevisionLedgerError("Invalid audit revision digest.")
    return value


def _work(value: object) -> str:
    try:
        if type(value) is not str:
            raise ValueError
        item = require_canonical_id(value)
        if not item.startswith("work:"):
            raise ValueError
        return item
    except (TypeError, ValueError):
        raise RevisionLedgerError("Invalid Work identifier.") from None


def scope_id(source: str, target: str) -> str:
    a, b = _work(source), _work(target)
    if a == b:
        raise RevisionLedgerError("Two distinct directed Works required.")
    digest = sha256(
        canonical_bytes({"source_work_id": a, "target_work_id": b})
    ).hexdigest()
    return "audit-scope:" + digest


def _verified_export(value: object, secret: str) -> tuple[dict, str]:
    # Independent v0.9.11 verification rejects forged scope, release
    # claims, digest, signature and source/target IDs *before any write*.
    try:
        verify_audit_export(value, secret=secret)
        manifest = value["manifest"]
        return manifest, scope_id(
            manifest["source_work_id"], manifest["target_work_id"])
    except (ValueError, TypeError, KeyError):
        raise RevisionLedgerError(
            "Signed bounded audit export verification failed."
        ) from None


def _head_row(row: object, scope: str, source: str, target: str) -> dict:
    if not isinstance(row, list) or len(row) != len(HEAD_FIELDS):
        raise RevisionLedgerError("Malformed audit revision head.")
    head = dict(zip(HEAD_FIELDS, row))
    if (head["id"] != scope or
            head["source_work_id"] != source or
            head["target_work_id"] != target or
            type(head["sequence"]) is not int or
            not 0 <= head["sequence"] <= MAX_REVISIONS or
            type(head["latest_revision_id"]) is not str or
            not (head["latest_revision_id"] == "" or
                 re.fullmatch(r"audit-rev:[0-9a-f]{64}",
                              head["latest_revision_id"]))):
        raise RevisionLedgerError("Invalid audit revision head scope.")
    _hex(head["chain_sha256"])
    if head["sequence"] == 0 and (
        head["latest_revision_id"] != "" or
        head["chain_sha256"] != ZERO_CHAIN
    ):
        raise RevisionLedgerError("Empty audit revision head corrupted.")
    if head["sequence"] > 0 and not head["latest_revision_id"]:
        raise RevisionLedgerError("Missing revision identity.")
    return head


def head_for(client, source: str, target: str) -> dict | None:
    a, b = _work(source), _work(target)
    scope = scope_id(a, b)
    rows = client.query(HEAD_READ, {"scope_id": scope})
    if not isinstance(rows, list) or len(rows) > 1:
        raise RevisionLedgerError("Ambiguous audit revision head.")
    return _head_row(rows[0], scope, a, b) if rows else None


def bootstrap_head(client, signed_export: dict, *, secret: str) -> dict:
    manifest, scope = _verified_export(signed_export, secret)
    a, b = manifest["source_work_id"], manifest["target_work_id"]
    rows = client.query(BOOTSTRAP, {
        "scope_id": scope, "source": a, "target": b, "zero": ZERO_CHAIN,
    })
    if not isinstance(rows, list) or len(rows) != 1:
        raise RevisionLedgerError("Could not initialize audit revision head.")
    return _head_row(rows[0], scope, a, b)


def _chain_sha(record: dict) -> str:
    return sha256(CHAIN_DOMAIN + canonical_bytes(record)).hexdigest()


def _record_from_export(manifest: dict, envelope: dict, *,
                        head: dict, recorded_at: int) -> dict:
    if type(recorded_at) is not int or not 0 <= recorded_at <= 4102444800:
        raise RevisionLedgerError("Invalid audit revision clock.")
    return {
        "scope_id": head["id"],
        "sequence": head["sequence"] + 1,
        "previous_revision_id": head["latest_revision_id"],
        "previous_chain_sha256": head["chain_sha256"],
        "manifest_sha256": envelope["manifest_sha256"],
        "source_work_id": manifest["source_work_id"],
        "target_work_id": manifest["target_work_id"],
        "observed_link_count": manifest["observed_link_count"],
        "captured_at_unix": manifest["captured_at_unix"],
        "recorded_at_unix": recorded_at,
        "query_template_sha256": manifest["query_template_sha256"],
    }


def append_revision(client, signed_export: dict, *, secret: str,
                    expected_sequence: int, expected_chain_sha256: str,
                    now: int | None = None) -> dict:
    manifest, scope = _verified_export(signed_export, secret)
    if (type(expected_sequence) is not int or
            not 0 <= expected_sequence < MAX_REVISIONS):
        raise RevisionLedgerError("Invalid expected revision sequence.")
    expected_chain = _hex(expected_chain_sha256)
    head = head_for(client, manifest["source_work_id"],
                    manifest["target_work_id"])
    if head is None or head["id"] != scope:
        raise RevisionLedgerError("Audit revision head not initialized.")
    if (head["sequence"] != expected_sequence or
            not hmac.compare_digest(head["chain_sha256"], expected_chain)):
        raise RevisionLedgerError("Stale audit revision head.")
    record = _record_from_export(
        manifest, signed_export, head=head,
        recorded_at=int(time.time()) if now is None else now,
    )
    digest = _chain_sha(record)
    revision_id = "audit-rev:" + digest
    params = {
        **record, "revision_id": revision_id, "chain_sha256": digest,
        "expected_sequence": expected_sequence,
        "expected_chain": expected_chain,
    }
    result = client.query(APPEND, params)
    if result != [[record["sequence"], revision_id, digest]]:
        # The DB statement has a per-scope write lock and rechecks all
        # expected head fields; a concurrent advance returns no row.
        raise RevisionLedgerError("Audit revision CAS refused or invalid.")
    return {
        "schema_version": VERSION,
        "scope_id": scope,
        "sequence": record["sequence"],
        "revision_id": revision_id,
        "chain_sha256": digest,
        "previous_chain_sha256": expected_chain,
        "manifest_sha256": record["manifest_sha256"],
        "source_text_persisted": False,
        "graph_snapshot_verified": False,
        "corpus_revision_immutable": False,
        "independent_source_rights_verified": False,
        "research_release_status": "HOLD",
    }


def verify_revision_chain(client, source: str, target: str) -> dict:
    a, b = _work(source), _work(target)
    head = head_for(client, a, b)
    if head is None:
        raise RevisionLedgerError("Audit revision scope not initialized.")
    rows = client.query(HISTORY_READ, {
        "scope_id": head["id"], "fetch_limit": MAX_REVISIONS + 1,
    })
    if (not isinstance(rows, list) or len(rows) != head["sequence"] or
            len(rows) > MAX_REVISIONS):
        raise RevisionLedgerError("Audit revision chain incomplete or oversized.")
    prior_sha, prior_id = ZERO_CHAIN, ""
    for index, row in enumerate(rows, 1):
        if not isinstance(row, list) or len(row) != len(RECORD_COLUMNS):
            raise RevisionLedgerError("Audit revision projection invalid.")
        item = dict(zip(RECORD_COLUMNS, row))
        record = {k: item[k] for k in RECORD_FIELDS}
        if (type(record["sequence"]) is not int or
                record["sequence"] != index or
                record["scope_id"] != head["id"] or
                record["previous_revision_id"] != prior_id or
                record["previous_chain_sha256"] != prior_sha or
                record["source_work_id"] != a or
                record["target_work_id"] != b or
                type(record["observed_link_count"]) is not int or
                not 0 <= record["observed_link_count"] <= 100 or
                type(record["captured_at_unix"]) is not int or
                type(record["recorded_at_unix"]) is not int or
                not 0 <= record["captured_at_unix"] <= 4102444800 or
                not 0 <= record["recorded_at_unix"] <= 4102444800):
            raise RevisionLedgerError("Audit revision history diverged.")
        _hex(record["manifest_sha256"])
        _hex(record["query_template_sha256"])
        expected_sha = _chain_sha(record)
        if (item["chain_sha256"] != expected_sha or
                item["id"] != "audit-rev:" + expected_sha):
            raise RevisionLedgerError("Audit revision content hash mismatch.")
        prior_sha, prior_id = expected_sha, item["id"]
    if (prior_sha != head["chain_sha256"] or
            prior_id != head["latest_revision_id"]):
        raise RevisionLedgerError("Audit revision head does not match history.")
    return {
        "schema_version": VERSION,
        "scope_id": head["id"],
        "verified_record_count": len(rows),
        "current_sequence": head["sequence"],
        "latest_revision_id": head["latest_revision_id"],
        "chain_sha256": head["chain_sha256"],
        "content_hashes_consistent_with_database": True,
        "append_only_enforced_for_cooperating_writer": True,
        "privileged_db_tampering_excluded": False,
        "work_graph_immutable": False,
        "graph_snapshot_verified": False,
        "source_rights_verified": False,
        "research_release_status": "HOLD",
    }
