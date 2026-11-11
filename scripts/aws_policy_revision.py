#!/usr/bin/env python3
"""v0.8.19: bounded policy-version drift and condition blind-spot observations.

This is a read-only *document consistency and structural risk* pass layered
on the v0.8.18 HMAC report. It does NOT evaluate effective IAM/SCP access.
No policy document, ARN, bucket name or source bytes is saved in the report.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.aws_access_surface import _role, _scp, _call, _sha
from scripts.aws_policy_documents import (
    PolicyAuditError, _document, _indicators, VERSION,
    MAX_DOCUMENTS, MAX_STATEMENTS, observe_policy_documents,
    verify_policy_report, live_clients,
)
from scripts.external_archive_attestation import (
    _strict_json, MAX_POLICY_BYTES, MAX_ARCHIVE_BYTES, MAX_ATTESTATION_BYTES,
)
from scripts.search_capture import digest, encode
from scripts.search_review_workflow import _write_private
from scripts.source_membership import MAX_WITNESS_BYTES
from scripts.source_receipts import (
    _load_json, MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, MAX_CAPTURE_BYTES,
)
from services.research_api.config import load_token
from services.research_api.signature import signature_key_path

SCHEMA = "0.8.19"
DOMAIN = b"neo4j-iam-scp-revision-observation-v0.8.19\n"
SCOPE = "two_bounded_policy_document_rounds_with_condition_blindspots"
MAX_REPORT_BYTES = 80_000
MAX_CONDITION_KEYS = 40
MAX_CONDITION_OPERATORS = 20
UNREVIEWED = (
    "access_point_policy_documents",
    "bucket_resource_policy_documents",
    "cross_account_resource_grants",
    "iam_permissions_boundary_documents",
    "iam_role_assume_role_trust",
    "iam_session_policies",
    "organizations_rcp_documents",
    "vpc_endpoint_policies",
)
RECOGNIZED_CONDITION_OPERATORS = frozenset({
    "StringEquals", "StringNotEquals", "StringLike", "StringNotLike",
    "StringEqualsIgnoreCase", "StringNotEqualsIgnoreCase",
    "ArnEquals", "ArnNotEquals", "ArnLike", "ArnNotLike",
    "IpAddress", "NotIpAddress",
    "Bool", "Null", "NumericEquals", "NumericNotEquals",
    "NumericLessThan", "NumericLessThanEquals",
    "NumericGreaterThan", "NumericGreaterThanEquals",
    "DateEquals", "DateNotEquals", "DateLessThan",
    "DateLessThanEquals", "DateGreaterThan", "DateGreaterThanEquals",
    "BinaryEquals",
})
CONDITION_FIELDS = frozenset({
    "statements_with_conditions",
    "statements_with_ifexists",
    "statements_with_set_qualifiers",
    "statements_with_null_tests",
    "statements_with_unrecognized_condition_operators",
    "statements_with_network_scoping_keys",
    "statements_with_principal_context_keys",
    "statements_with_aws_resource_scoping_keys",
    "unconditional_broad_iam_allow_statements",
    "statements_with_notaction_or_notresource",
    "condition_attributes_inspected",
})
RESULT_FIELDS = frozenset({
    "schema_version", "scope", "parent_policy_report",
    "observed_at_utc", "two_bounded_policy_rounds_match",
    "policy_document_count", "managed_default_version_count",
    "policy_document_projection_sha256",
    "managed_default_versions_sha256",
    "first_round_sha256", "second_round_sha256",
    "condition_indicators", "unreviewed_access_paths",
    "parent_attachment_and_scp_lineage_rechecked",
    "all_conditional_semantics_evaluated",
    "effective_iam_or_scp_permissions_computed",
    "permissions_boundary_or_role_trust_evaluated",
    "cross_account_access_or_s3_resource_policy_audited",
    "policy_version_transactional_snapshot_verified",
    "research_release_status", "report_hmac",
})


class RevisionAuditError(ValueError):
    """Do not disclose private policy content, source or principal names."""


def _sign(body: dict, key: str) -> str:
    if not isinstance(key, str) or len(key) < 40:
        raise RevisionAuditError("Local signing key invalid.")
    return hmac.new(key.encode(), DOMAIN + encode(body),
                    hashlib.sha256).hexdigest()


def _conditions(doc: dict, *, kind: str) -> dict:
    """Describe structural review needs; never infer a condition is 'safe'."""
    result = {field: 0 for field in CONDITION_FIELDS}
    for statement in doc["Statement"]:
        if "NotAction" in statement or "NotResource" in statement:
            result["statements_with_notaction_or_notresource"] += 1
        if (kind == "iam" and statement["Effect"] == "Allow" and
            "Condition" not in statement and
            any(x == "*" for x in _arr(statement.get("Resource", []))) and
            any(x.casefold() in ("*", "s3:*", "iam:*")
                for x in _arr(statement.get("Action", [])))):
            result["unconditional_broad_iam_allow_statements"] += 1
        cond = statement.get("Condition")
        if cond is None:
            continue
        if not isinstance(cond, dict) or not 1 <= len(cond) <= MAX_CONDITION_OPERATORS:
            raise RevisionAuditError("Policy condition structure invalid.")
        result["statements_with_conditions"] += 1
        categories = set()
        for operator, keys in cond.items():
            if (not isinstance(operator, str) or not 1 <= len(operator) <= 100 or
                any(ord(ch) < 32 or ord(ch) == 127 for ch in operator) or
                not isinstance(keys, dict) or
                not 1 <= len(keys) <= MAX_CONDITION_KEYS):
                raise RevisionAuditError("Policy condition operator/keys invalid.")
            if operator.endswith("IfExists"):
                categories.add("statements_with_ifexists")
                base = operator[:-8]
            else:
                base = operator
            if base.startswith(("ForAnyValue:", "ForAllValues:")):
                categories.add("statements_with_set_qualifiers")
                base = base.split(":", 1)[1]
            if base == "Null":
                categories.add("statements_with_null_tests")
            if base not in RECOGNIZED_CONDITION_OPERATORS:
                categories.add("statements_with_unrecognized_condition_operators")
            for key, value in keys.items():
                if (not isinstance(key, str) or not 1 <= len(key) <= 200 or
                    any(ord(ch) < 32 or ord(ch) == 127 for ch in key)):
                    raise RevisionAuditError("Policy condition context key invalid.")
                values = _arr(value)
                if (not isinstance(values, list) or
                    not 1 <= len(values) <= 200 or
                    any(type(x) not in (str, int, bool) or
                        (isinstance(x, str) and (
                            not x or len(x) > 1024 or
                            any(ord(ch) < 32 or ord(ch) == 127 for ch in x)
                        )) for x in values)):
                    raise RevisionAuditError("Policy condition operand invalid.")
                result["condition_attributes_inspected"] += 1
                lowered = key.casefold()
                if lowered in (
                    "aws:sourceip", "aws:sourcevpce", "aws:sourcevpc",
                    "aws:sourcevpcsourceip", "aws:viaawsservice",
                ):
                    categories.add("statements_with_network_scoping_keys")
                if lowered.startswith(("aws:principal", "aws:userid", "aws:multifactorauth")):
                    categories.add("statements_with_principal_context_keys")
                if lowered.startswith(("s3:resourceaccount", "s3:accesspoint",
                                       "s3:auth", "s3:requestobjecttag")):
                    categories.add("statements_with_aws_resource_scoping_keys")
        for category in categories:
            result[category] += 1
    return result


def _arr(value) -> list:
    return [value] if isinstance(value, str) else value


def _checked_census(role: tuple, scp: tuple, census: dict) -> None:
    if (role[0] != census["sts_caller_arn_sha256"] or
        role[1] != census["caller_role_arn_sha256"] or
        role[2] != census["caller_permissions_boundary_present"] or
        role[3] != census["caller_role_attachment_count"] or
        role[4] != census["caller_role_inline_count"] or
        role[5] != census["caller_role_inventory_sha256"] or
        scp[:3] != (census["scp_targets_count"],
                    census["scp_attachment_count"],
                    census["scp_inventory_sha256"])):
        raise RevisionAuditError("IAM/SCP inventory differs from signed census.")


def _managed_document(iam, arn: str) -> tuple[dict, str]:
    """Read default version, document, and default again to catch version flip."""
    before = _call(iam, "get_policy", PolicyArn=arn).get("Policy")
    if not isinstance(before, dict) or before.get("Arn") != arn:
        raise RevisionAuditError("IAM managed policy not canonical.")
    version = before.get("DefaultVersionId")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise RevisionAuditError("IAM default policy version invalid.")
    raw = _call(iam, "get_policy_version",
                PolicyArn=arn, VersionId=version).get("PolicyVersion")
    if (not isinstance(raw, dict) or raw.get("VersionId") != version or
        raw.get("IsDefaultVersion") is not True):
        raise RevisionAuditError("IAM retrieved policy is not the default.")
    doc = _document(raw.get("Document"))
    after = _call(iam, "get_policy", PolicyArn=arn).get("Policy")
    if (not isinstance(after, dict) or after.get("Arn") != arn or
        after.get("DefaultVersionId") != version):
        raise RevisionAuditError("IAM default version changed while reading.")
    return doc, version


def _round(iam, sts, org, *, account: str, census: dict) -> dict:
    """Bounded IAM+SCP read, with before/after attachment and default checks."""
    start_role = _role(iam, sts, account=account, include_entries=True)
    start_scp = _scp(org, account=account, include_entries=True)
    _checked_census(start_role, start_scp, census)
    docs, defaults = [], []
    entries = start_role[6]
    for arn in entries["attached_policy_arns"]:
        doc, version = _managed_document(iam, arn)
        docs.append(("iam_managed", arn, doc))
        defaults.append({
            "policy_identifier_sha256": digest(arn.encode("utf-8")),
            "version_sha256": digest(version.encode("utf-8")),
        })
    role = entries["role_name"]
    for name in entries["inline_policy_names"]:
        item = _call(iam, "get_role_policy", RoleName=role, PolicyName=name)
        if item.get("RoleName") != role or item.get("PolicyName") != name:
            raise RevisionAuditError("IAM inline policy identity mismatch.")
        docs.append(("iam_inline", name, _document(item.get("PolicyDocument"))))
    seen_scp = set()
    for ancestor in start_scp[3]:
        for ident in ancestor["attached_scp_ids"]:
            if ident in seen_scp:
                continue
            seen_scp.add(ident)
            item = _call(org, "describe_policy", PolicyId=ident).get("Policy")
            summary = item.get("PolicySummary") if isinstance(item, dict) else None
            if (not isinstance(summary, dict) or summary.get("Id") != ident or
                summary.get("Type") != "SERVICE_CONTROL_POLICY"):
                raise RevisionAuditError("Inherited SCP version/id mismatch.")
            docs.append(("scp", ident, _document(item.get("Content"))))
    if len(docs) > MAX_DOCUMENTS:
        raise RevisionAuditError("Policy documents exceed bounded pilot.")
    end_role = _role(iam, sts, account=account)
    end_scp = _scp(org, account=account)
    if start_role[:6] != end_role or start_scp[:3] != end_scp:
        raise RevisionAuditError("Policy attachment or SCP ancestry drifted.")
    framed, conditions = [], {k: 0 for k in CONDITION_FIELDS}
    for kind, ident, doc in docs:
        from scripts.aws_policy_documents import _indicators
        source_kind = "scp" if kind == "scp" else "iam"
        record = {
            "kind": kind, "identifier_sha256": digest(ident.encode("utf-8")),
            "doc_sha256": digest(encode(doc)),
            "findings": _indicators(doc, kind=source_kind),
        }
        framed.append(record)
        for name, count in _conditions(doc, kind=source_kind).items():
            conditions[name] += count
    framed.sort(key=lambda row: (row["kind"], row["identifier_sha256"]))
    defaults.sort(key=lambda row: row["policy_identifier_sha256"])
    return {
        "documents": framed,
        "defaults": defaults,
        "conditions": conditions,
    }


def observe_revision(
    s3, sts, s3control, iam, org, *, policy: dict, report: dict,
    statement: dict, record: dict, receipt: dict, witness: dict,
    capture: dict, source_file: Path, local_key: str, account: str,
    region: str, observed_at=None,
) -> dict:
    common = dict(
        policy=policy, report=report, statement=statement, record=record,
        receipt=receipt, witness=witness, capture=capture,
        source_file=source_file, local_key=local_key,
        account=account, region=region,
    )
    try:
        # All prior source, S3, IAM, SCP, and policy-document chain controls.
        previous = observe_policy_documents(
            s3, sts, s3control, iam, org, **common, observed_at=observed_at)
        census = previous["access_census"]
        first = _round(iam, sts, org, account=account, census=census)
        second = _round(iam, sts, org, account=account, census=census)
        first_docs = digest(encode(first["documents"]))
        second_docs = digest(encode(second["documents"]))
        if (first_docs != previous["policy_documents_projection_sha256"] or
            first_docs != second_docs or
            first["defaults"] != second["defaults"] or
            first["conditions"] != second["conditions"] or
            len(first["documents"]) != previous["policy_count"]):
            raise RevisionAuditError("IAM/SCP document or default version drifted.")
        counted = {kind: sum(d["kind"] == kind for d in first["documents"])
                   for kind in ("iam_managed", "iam_inline", "scp")}
        if (counted["iam_managed"] != previous["iam_managed_policy_count"] or
            counted["iam_inline"] != previous["iam_inline_policy_count"] or
            counted["scp"] != previous["scp_policy_count"]):
            raise RevisionAuditError("Policy document kind count drifted.")
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        raise RevisionAuditError("Bounded IAM/SCP version recheck incomplete.") from None
    unsigned = {
        "schema_version": SCHEMA,
        "scope": SCOPE,
        "parent_policy_report": previous,
        "observed_at_utc": previous["observed_at_utc"],
        "two_bounded_policy_rounds_match": True,
        "policy_document_count": len(first["documents"]),
        "managed_default_version_count": len(first["defaults"]),
        "policy_document_projection_sha256": first_docs,
        "managed_default_versions_sha256": digest(encode(first["defaults"])),
        "first_round_sha256": digest(encode({
            "doc": first["documents"], "defaults": first["defaults"],
            "conditions": first["conditions"],
        })),
        "second_round_sha256": digest(encode({
            "doc": second["documents"], "defaults": second["defaults"],
            "conditions": second["conditions"],
        })),
        "condition_indicators": first["conditions"],
        "unreviewed_access_paths": list(UNREVIEWED),
        "parent_attachment_and_scp_lineage_rechecked": True,
        "all_conditional_semantics_evaluated": False,
        "effective_iam_or_scp_permissions_computed": False,
        "permissions_boundary_or_role_trust_evaluated": False,
        "cross_account_access_or_s3_resource_policy_audited": False,
        "policy_version_transactional_snapshot_verified": False,
        "research_release_status": "HOLD",
    }
    return {**unsigned, "report_hmac": _sign(unsigned, local_key)}


def verify_revision(result: object, *, policy: dict, report: dict,
    statement: dict, record: dict, receipt: dict, witness: dict,
    capture: dict, source_file: Path, local_key: str, account: str,
    region: str,
) -> None:
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        raise RevisionAuditError("Policy revision report schema invalid.")
    if (result["schema_version"] != SCHEMA or result["scope"] != SCOPE or
        result["research_release_status"] != "HOLD" or
        result["two_bounded_policy_rounds_match"] is not True or
        result["parent_attachment_and_scp_lineage_rechecked"] is not True or
        result["unreviewed_access_paths"] != list(UNREVIEWED) or
        any(result[k] is not False for k in (
            "all_conditional_semantics_evaluated",
            "effective_iam_or_scp_permissions_computed",
            "permissions_boundary_or_role_trust_evaluated",
            "cross_account_access_or_s3_resource_policy_audited",
            "policy_version_transactional_snapshot_verified"))):
        raise RevisionAuditError("Policy revision trust claims invalid.")
    counts = result["condition_indicators"]
    if not isinstance(counts, dict) or set(counts) != CONDITION_FIELDS:
        raise RevisionAuditError("Policy condition indicators invalid.")
    for key in ("policy_document_count", "managed_default_version_count"):
        val = result[key]
        if type(val) is not int or not 0 <= val <= MAX_DOCUMENTS:
            raise RevisionAuditError("Policy revision count invalid.")
    for key, val in counts.items():
        if (type(val) is not int or
            not 0 <= val <= (
                result["policy_document_count"] * MAX_STATEMENTS *
                (MAX_CONDITION_KEYS if key == "condition_attributes_inspected" else 1)
            )):
            raise RevisionAuditError("Policy condition count invalid.")
    for key in ("managed_default_versions_sha256", "policy_document_projection_sha256",
                "first_round_sha256", "second_round_sha256"):
        if not _sha(result[key]):
            raise RevisionAuditError("Policy revision digest malformed.")
    if (result["first_round_sha256"] != result["second_round_sha256"] or
        result["policy_document_count"] !=
            result["parent_policy_report"]["policy_count"] or
        result["managed_default_version_count"] !=
            result["parent_policy_report"]["iam_managed_policy_count"] or
        result["policy_document_projection_sha256"] !=
            result["parent_policy_report"]["policy_documents_projection_sha256"]):
        raise RevisionAuditError("Policy revision record consistency invalid.")
    try:
        verify_policy_report(
            result["parent_policy_report"],
            policy=policy, report=report, statement=statement,
            record=record, receipt=receipt, witness=witness,
            capture=capture, source_file=source_file, local_key=local_key,
            account=account, region=region)
    except (ValueError, TypeError, KeyError, OSError):
        raise RevisionAuditError("Parent policy report invalid.") from None
    if result["observed_at_utc"] != result["parent_policy_report"]["observed_at_utc"]:
        raise RevisionAuditError("Policy revision timestamp mismatch.")
    unsigned = {k: v for k, v in result.items() if k != "report_hmac"}
    if (not _sha(result["report_hmac"]) or
        not hmac.compare_digest(result["report_hmac"], _sign(unsigned, local_key))):
        raise RevisionAuditError("Policy revision local HMAC invalid.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    for action in ("inspect", "verify"):
        q = sub.add_parser(action)
        for item in (
            "source-file", "source-record", "receipt", "witness",
            "capture-manifest", "trusted-policy", "archive-report",
            "signed-statement",
        ):
            q.add_argument("--" + item, type=Path, required=True)
        q.add_argument("--aws-region", required=True)
        q.add_argument("--expected-bucket-owner", required=True)
        q.add_argument("--local-key-file", type=Path)
        if action == "inspect":
            q.add_argument("--aws-profile", required=True)
            q.add_argument("--ack-read-only-policy-revision", action="store_true")
            q.add_argument("--output", type=Path, required=True)
        else:
            q.add_argument("--observation", type=Path, required=True)
    args = p.parse_args(argv)
    if args.action == "inspect" and not args.ack_read_only_policy_revision:
        print("[BLOCKED] Explicit authorization for AWS policy revision reads required.")
        return 2
    try:
        key = load_token(args.local_key_file or signature_key_path())
        common = dict(
            policy=_strict_json(args.trusted_policy, MAX_POLICY_BYTES),
            report=_strict_json(args.archive_report, MAX_ARCHIVE_BYTES),
            statement=_strict_json(args.signed_statement, MAX_ATTESTATION_BYTES),
            record=_load_json(args.source_record, MAX_RECORD_BYTES),
            receipt=_load_json(args.receipt, MAX_RECEIPT_BYTES),
            witness=_load_json(args.witness, MAX_WITNESS_BYTES),
            capture=_load_json(args.capture_manifest, MAX_CAPTURE_BYTES),
            source_file=args.source_file, local_key=key,
            account=args.expected_bucket_owner, region=args.aws_region)
        if args.action == "inspect":
            from scripts.live_s3_version_verify import _chain
            _chain(common["policy"], common["report"], common["statement"],
                   common["record"], common["receipt"], common["witness"],
                   common["capture"], common["source_file"], key)
            clients = live_clients(
                profile=args.aws_profile, region=args.aws_region,
                account=args.expected_bucket_owner)
            result = observe_revision(*clients, **common)
            _write_private(args.output, result)
        else:
            verify_revision(
                _strict_json(args.observation, MAX_REPORT_BYTES), **common)
        print("[OK] Bounded IAM/SCP version and condition indicators verified; "
              "effective access remains NOT EVALUATED; research HOLD.")
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        print("[FAIL] IAM/SCP revision observation invalid or unavailable.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
