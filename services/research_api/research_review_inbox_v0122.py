"""v0.12.2: signed, bounded, offline research-tool review inbox.

Compose 2–6 independently verified v0.12.1 service-HMAC research runs into
one deterministic per-Evidence routing view. No graph reads, source text,
model calls, human decisions, graph mutations or DvirOS task persistence.
One Evidence in multiple runs is one review candidate, not multiple findings.
"""
from __future__ import annotations

from hashlib import sha256
import hmac

from services.research_api.audit_export_v0911 import canonical_bytes
from services.research_api.research_tool_receipt_v0121 import (
    verify_signed_research_tool_run,
)

VERSION = "0.12.2"
DOMAIN = b"dviros/neo/research-tool-review-inbox/v0.12.2\n"
MIN_RUNS = 2
MAX_RUNS = 6
MAX_OBSERVATIONS = MAX_RUNS * 12
MAX_INBOX_BYTES = 125_000
CARD_METADATA_FIELDS = (
    "edge_id", "source_passage_id", "target_passage_id", "source_ref",
    "version_id", "rights_tag", "evidence_review_status",
)


def _hash(value: object) -> tuple[str, bytes]:
    raw = canonical_bytes(value)
    if len(raw) > MAX_INBOX_BYTES:
        raise ValueError("Research review inbox exceeds private metadata budget.")
    return sha256(raw).hexdigest(), raw


def _secret_bytes(secret: object) -> bytes:
    if (
        type(secret) is not str or not 40 <= len(secret) <= 256
        or any(ch.isspace() for ch in secret)
    ):
        raise ValueError("Invalid research service key.")
    return secret.encode("utf-8")


def _variants(observations: list[dict], key: str) -> list[str]:
    return sorted({
        row[key] for row in observations if row[key] is not None
    })


def _evidence_group(evidence_id: str, observations: list[dict]) -> dict:
    """Classify observed metadata variants, never a scholarly disagreement."""
    versions = _variants(observations, "version_id")
    rights = _variants(observations, "rights_tag")
    source_refs = _variants(observations, "source_ref")
    statuses = _variants(observations, "evidence_review_status")
    edge_ids = _variants(observations, "edge_id")
    warnings = []
    if len(source_refs) > 1:
        warnings.append("SOURCE_REFERENCE_DIVERGENCE")
    if len(versions) > 1:
        warnings.append("VERSION_ID_DIVERGENCE")
    if len(rights) > 1:
        warnings.append("RIGHTS_TAG_DIVERGENCE")
    if len(statuses) > 1:
        warnings.append("OBSERVED_REVIEW_STATUS_DIVERGENCE")
    if len(edge_ids) > 1:
        warnings.append("EDGE_ANCHOR_DIVERGENCE")
    if any(row["version_id"] is None for row in observations):
        warnings.append("MISSING_VERSION_ID")
    if any(row["rights_tag"] is None for row in observations):
        warnings.append("MISSING_RIGHTS_TAG")
    if any(
        row["evidence_review_status"] in ("rejected", "disputed")
        for row in observations
    ):
        warnings.append("CONTESTED_REVIEW_LABEL_OBSERVED")
    return {
        "evidence_id": evidence_id,
        "observation_count": len(observations),
        "observed_in_run_indices": [
            row["run_index"] for row in observations
        ],
        "observations": observations,
        "source_ref_variants": source_refs,
        "version_id_variants": versions,
        "rights_tag_variants": rights,
        "review_status_variants": statuses,
        "triage_warnings": warnings,
        "has_metadata_warnings": bool(warnings),
        "human_review_required": True,
        "human_approval_recorded": False,
        "licensed_source_rights_verified": False,
        "scholarly_conflict_verified": False,
    }


def build_research_review_inbox(runs: object, *, secret: str) -> dict:
    """Verify each signed run then route at most 72 observed Evidence cards.

    Input order is deliberately immaterial: runs are sorted by their already
    HMAC-authenticated receipt SHA256 before assigning provenance run_index.
    Duplicate signed runs are refused, not counted as independent support.
    """
    key = _secret_bytes(secret)
    if type(runs) is not list or not MIN_RUNS <= len(runs) <= MAX_RUNS:
        raise ValueError("Require two to six distinct signed research runs.")

    signed = []
    digests = set()
    for run in runs:
        # Exact v0.12.1 typed plan/result, 12-card bound and local HMAC
        # are all replayed offline. No graph reads are performed.
        verify_signed_research_tool_run(run, secret=secret)
        receipt = run["signed_receipt"]
        digest = receipt["receipt_sha256"]
        if digest in digests:
            raise ValueError("Duplicate research run receipt in inbox.")
        digests.add(digest)
        signed.append((digest, run))
    signed.sort(key=lambda item: item[0])

    run_summaries = []
    grouped: dict[str, list[dict]] = {}
    total_observations = 0
    for index, (digest, run) in enumerate(signed):
        plan = run["plan"]
        execution = run["execution"]
        original = run["signed_receipt"]["receipt"]
        if (
            original["tool_operation"] != execution["tool_operation"]
            or original["request_checkpoint_sha256"] !=
            plan["request_checkpoint_sha256"]
            or original["returned_card_count"] != len(execution["evidence_cards"])
        ):
            raise ValueError("Inconsistent signed run receipt summary.")
        cards = execution["evidence_cards"]
        if len({card["evidence_id"] for card in cards}) != len(cards):
            raise ValueError("Duplicate Evidence in one signed tool output.")
        run_summaries.append({
            "run_index": index,
            "signed_receipt_sha256": digest,
            "tool_operation": execution["tool_operation"],
            "request_checkpoint_sha256": plan["request_checkpoint_sha256"],
            "execution_sha256": original["execution_sha256"],
            "passage_ids": plan["parameters"]["passage_ids"],
            "query_sha256": plan["parameters"]["query_sha256"],
            "scheduled_graph_reads": execution["scheduled_graph_reads"],
            "observed_evidence_card_count": len(cards),
        })
        for card in cards:
            eid = card["evidence_id"]
            row = {
                "run_index": index,
                "signed_receipt_sha256": digest,
                "tool_operation": execution["tool_operation"],
                **{name: card[name] for name in CARD_METADATA_FIELDS},
            }
            grouped.setdefault(eid, []).append(row)
            total_observations += 1
    if total_observations > MAX_OBSERVATIONS:
        raise ValueError("Research inbox observation count exceeded.")

    evidence = [
        _evidence_group(eid, grouped[eid])
        for eid in sorted(grouped)
    ]
    inbox = {
        "schema_version": VERSION,
        "contract_kind": "dviros.neo.signed_research_tool_review_inbox",
        "run_count": len(signed),
        "run_summaries": run_summaries,
        "observed_card_count": total_observations,
        "distinct_evidence_count": len(evidence),
        "repeated_evidence_count": sum(
            item["observation_count"] > 1 for item in evidence
        ),
        "metadata_warning_evidence_count": sum(
            item["has_metadata_warnings"] for item in evidence
        ),
        "evidence": evidence,
        "source_run_receipts_hmac_verified": True,
        "inbox_hmac_verified_by_local_service_secret": True,
        "reviewer_identity_verified": False,
        "historical_graph_changes_proven": False,
        "immutable_graph_snapshot_verified": False,
        "source_rights_verified": False,
        "human_review_decisions_recorded": False,
        "dviros_workspace_authorization_verified": False,
        "source_text_exported": False,
        "graph_reads_during_inbox_assembly": 0,
        "research_release_status": "HOLD",
        "note": (
            "Offline routing of service-HMAC-verified metadata observations; "
            "cross-run differences are review prompts, not independent "
            "source/edition, temporal, licensing or scholarly proofs."
        ),
    }
    digest, _ = _hash(inbox)
    mac = hmac.new(key, DOMAIN + digest.encode("ascii"), sha256).hexdigest()
    return {
        "inbox": inbox,
        "inbox_sha256": digest,
        "inbox_hmac_sha256": mac,
    }


def verify_research_review_inbox(
    value: object, runs: object, *, secret: str,
) -> dict:
    """Rebuild exact original signed inputs and HMAC; offline, no Neo4j."""
    if type(value) is not dict or set(value) != {
        "inbox", "inbox_sha256", "inbox_hmac_sha256",
    }:
        raise ValueError("Malformed signed research review inbox.")
    expected = build_research_review_inbox(runs, secret=secret)
    if (
        type(value["inbox_sha256"]) is not str
        or type(value["inbox_hmac_sha256"]) is not str
        or len(value["inbox_sha256"]) != 64
        or len(value["inbox_hmac_sha256"]) != 64
        or value["inbox"] != expected["inbox"]
        or not hmac.compare_digest(
            value["inbox_sha256"], expected["inbox_sha256"]
        )
        or not hmac.compare_digest(
            value["inbox_hmac_sha256"], expected["inbox_hmac_sha256"]
        )
    ):
        raise ValueError("Research review inbox replay verification failed.")
    inbox = expected["inbox"]
    return {
        "schema_version": VERSION,
        "source_run_receipts_hmac_verified": True,
        "review_inbox_hmac_verified": True,
        "run_count": inbox["run_count"],
        "observed_card_count": inbox["observed_card_count"],
        "distinct_evidence_count": inbox["distinct_evidence_count"],
        "metadata_warning_evidence_count": inbox[
            "metadata_warning_evidence_count"
        ],
        "graph_reads_during_verification": 0,
        "human_review_decisions_recorded": False,
        "research_release_status": "HOLD",
    }
