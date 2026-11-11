#!/usr/bin/env python3
"""v0.8.18: bounded IAM and SCP document risk indicators, not IAM evaluation.

Read-only AWS policy content reads are tied to v0.8.17 signed inventories.
No policy text, AWS ARN, principal name, source bytes or credentials are
exported. No permission simulation or 'effective access safe' verdict.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import hmac
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.aws_access_surface import (
    AccessAuditError, _role, _scp, observe_access_surface,
    verify_access_surface, live_clients, _call, _sha, SAFE_ROLE,
)
from scripts.external_archive_attestation import (
    _strict_json, MAX_ARCHIVE_BYTES, MAX_ATTESTATION_BYTES, MAX_POLICY_BYTES,
)
from scripts.search_capture import digest, encode
from scripts.search_review_workflow import _write_private
from scripts.source_membership import MAX_WITNESS_BYTES
from scripts.source_receipts import (
    MAX_CAPTURE_BYTES, MAX_RECORD_BYTES, MAX_RECEIPT_BYTES, _load_json,
)
from services.research_api.config import load_token
from services.research_api.signature import signature_key_path

SCHEMA = "0.8.18"
SCOPE = "attached_iam_and_inherited_scp_documents_bounded_risk_indicators"
DOMAIN = b"neo4j-iam-scp-doc-inspection-v0.8.18\n"
MAX_DOCUMENT_BYTES = 20_000
MAX_DOCUMENTS = 120
MAX_STATEMENTS = 70
MAX_AUDIT_BYTES = 70_000
VERSION = re.compile(r"^v[1-9][0-9]?$")
ALLOWED_TOP = frozenset({"Version", "Id", "Statement"})
ALLOWED_STMT = frozenset({
    "Sid", "Effect", "Action", "NotAction", "Resource",
    "NotResource", "Condition",
})
# Readable *indicators*, not a complete action universe or risk judgment.
STORAGE_MUTATION = (
    "s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion",
    "s3:PutBucketPolicy", "s3:PutBucketPublicAccessBlock",
    "s3:BypassGovernanceRetention", "s3:PutObjectRetention",
    "s3:PutLifecycleConfiguration", "s3:PutBucketVersioning",
)
IAM_ESCALATION = (
    "iam:PassRole", "iam:AttachRolePolicy", "iam:PutRolePolicy",
    "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion",
    "iam:UpdateAssumeRolePolicy", "iam:CreateAccessKey",
)
FINDING_FIELDS = frozenset({
    "iam_allow_wildcard_resource_statements",
    "iam_storage_mutation_allow_statements",
    "iam_iam_escalation_allow_statements",
    "iam_explicit_deny_statements",
    "scp_explicit_deny_statements",
    "scp_allow_statements",
    "conditioned_statements",
    "not_action_or_not_resource_statements",
    "total_statements_scanned",
})
REPORT_FIELDS = frozenset({
    "schema_version", "scope", "access_census",
    "observed_at_utc", "policy_count", "iam_managed_policy_count",
    "iam_inline_policy_count", "scp_policy_count",
    "policy_documents_projection_sha256", "policy_indicators",
    "doc_reads_bound_to_attachment_inventory",
    "iam_effective_permissions_calculated",
    "scp_effective_permissions_calculated",
    "policy_conditions_semantically_evaluated",
    "all_external_grants_and_trust_evaluated",
    "source_and_archive_rights_approved",
    "research_release_status", "report_hmac",
})


class PolicyAuditError(ValueError):
    """Never include source, policy content, AWS identity or bucket details."""


def _sign(payload: dict, key: str) -> str:
    if not isinstance(key, str) or len(key) < 40:
        raise PolicyAuditError("Policy audit signing key invalid.")
    return hmac.new(key.encode(), DOMAIN + encode(payload),
                    hashlib.sha256).hexdigest()


def _unique_pairs(pairs):
    found = {}
    for k, v in pairs:
        if k in found:
            raise ValueError("Duplicate JSON property.")
        found[k] = v
    return found


def _document(data: object) -> dict:
    if isinstance(data, str):
        if not 0 < len(data.encode("utf-8")) <= MAX_DOCUMENT_BYTES:
            raise PolicyAuditError("Policy document size invalid.")
        # IAM may URL-encode policy documents, depending on SDK version.
        decoded = unquote(data)
        try:
            data = json.loads(decoded, object_pairs_hook=_unique_pairs,
                              parse_constant=lambda x: (_ for _ in ()).throw(ValueError()))
        except (ValueError, TypeError, UnicodeError):
            raise PolicyAuditError("Encoded policy document malformed.") from None
    if not isinstance(data, dict):
        raise PolicyAuditError("Policy document must be JSON object.")
    try:
        raw = encode(data)
    except (TypeError, ValueError, UnicodeError):
        raise PolicyAuditError("Policy document not canonical JSON.") from None
    if len(raw) > MAX_DOCUMENT_BYTES or (
        not set(data).issubset(ALLOWED_TOP) or
        data.get("Version") not in ("2008-10-17", "2012-10-17")
    ):
        raise PolicyAuditError("Policy document scope/version invalid.")
    statements = data.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or not 1 <= len(statements) <= MAX_STATEMENTS:
        raise PolicyAuditError("Policy document statement count invalid.")
    for statement in statements:
        if not isinstance(statement, dict) or (
            not set(statement).issubset(ALLOWED_STMT) or
            statement.get("Effect") not in ("Allow", "Deny") or
            ("Action" in statement) == ("NotAction" in statement) or
            ("Resource" in statement) == ("NotResource" in statement)
        ):
            raise PolicyAuditError("Unsupported IAM/SCP statement structure.")
        for key in ("Action", "NotAction", "Resource", "NotResource"):
            if key in statement:
                value = statement[key]
                values = [value] if isinstance(value, str) else value
                if (not isinstance(values, list) or
                    not 1 <= len(values) <= 200 or
                    any(not isinstance(x, str) or not x or len(x) > 1024
                        for x in values)):
                    raise PolicyAuditError("Policy statement attribute invalid.")
        if ("Condition" in statement and
            (not isinstance(statement["Condition"], dict) or
             not statement["Condition"])):
            raise PolicyAuditError("Policy condition malformed.")
    return {**data, "Statement": statements}


def _patterns(statement: dict, key: str) -> list[str]:
    val = statement.get(key, [])
    return [val] if isinstance(val, str) else val


def _allows(patterns: list[str], examples: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(action.casefold(), pattern.casefold())
               for pattern in patterns for action in examples)


def _indicators(doc: dict, *, kind: str) -> dict:
    if kind not in ("iam", "scp"):
        raise PolicyAuditError("Policy source kind invalid.")
    result = {field: 0 for field in FINDING_FIELDS}
    for st in doc["Statement"]:
        result["total_statements_scanned"] += 1
        if st.get("Condition") is not None:
            result["conditioned_statements"] += 1
        if "NotAction" in st or "NotResource" in st:
            result["not_action_or_not_resource_statements"] += 1
        if kind == "scp":
            if st["Effect"] == "Deny":
                result["scp_explicit_deny_statements"] += 1
            else:
                result["scp_allow_statements"] += 1
            continue
        if st["Effect"] == "Deny":
            result["iam_explicit_deny_statements"] += 1
            continue
        if "NotAction" in st:
            # The complement of NotAction needs full IAM evaluation.
            continue
        actions = _patterns(st, "Action")
        resources = _patterns(st, "Resource")
        if "*" in resources and any(
            pattern.casefold() in ("*", "s3:*", "iam:*") for pattern in actions
        ):
            result["iam_allow_wildcard_resource_statements"] += 1
        if _allows(actions, STORAGE_MUTATION):
            result["iam_storage_mutation_allow_statements"] += 1
        if _allows(actions, IAM_ESCALATION):
            result["iam_iam_escalation_allow_statements"] += 1
    return result


def _iam_documents(iam, entries: dict) -> list[dict]:
    role = entries["role_name"]
    documents = []
    for arn in entries["attached_policy_arns"]:
        details = _call(iam, "get_policy", PolicyArn=arn).get("Policy")
        if not isinstance(details, dict) or details.get("Arn") != arn:
            raise PolicyAuditError("IAM managed-policy identity differs.")
        version = details.get("DefaultVersionId")
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            raise PolicyAuditError("IAM managed-policy version absent.")
        data = _call(iam, "get_policy_version",
                     PolicyArn=arn, VersionId=version).get("PolicyVersion")
        if (not isinstance(data, dict) or
            data.get("VersionId") != version or
            data.get("IsDefaultVersion") is not True):
            raise PolicyAuditError("IAM managed default version not confirmed.")
        doc = _document(data.get("Document"))
        documents.append({"kind": "iam_managed", "identifier_sha256": digest(arn.encode()),
                          "doc_sha256": digest(encode(doc)), "findings": _indicators(doc, kind="iam")})
    for name in entries["inline_policy_names"]:
        data = _call(iam, "get_role_policy",
                     RoleName=role, PolicyName=name)
        if data.get("RoleName") != role or data.get("PolicyName") != name:
            raise PolicyAuditError("IAM inline policy identity differs.")
        doc = _document(data.get("PolicyDocument"))
        documents.append({"kind": "iam_inline", "identifier_sha256": digest(name.encode()),
                          "doc_sha256": digest(encode(doc)), "findings": _indicators(doc, kind="iam")})
    return documents


def _scp_documents(org, lineage: list[dict]) -> list[dict]:
    found = {}
    for node in lineage:
        target = node["target"]
        for policy_id in node["attached_scp_ids"]:
            if policy_id in found:
                continue  # Same policy at multiple inheritance levels, count once.
            policy = _call(org, "describe_policy", PolicyId=policy_id).get("Policy")
            if not isinstance(policy, dict):
                raise PolicyAuditError("Organizations SCP document unavailable.")
            summary = policy.get("PolicySummary")
            if (not isinstance(summary, dict) or
                summary.get("Id") != policy_id or
                summary.get("Type") != "SERVICE_CONTROL_POLICY"):
                raise PolicyAuditError("SCP document identity/type differs.")
            doc = _document(policy.get("Content"))
            found[policy_id] = {
                "kind": "scp", "identifier_sha256": digest(policy_id.encode()),
                "doc_sha256": digest(encode(doc)), "findings": _indicators(doc, kind="scp")}
    return list(found.values())


def observe_policy_documents(s3, sts, s3control, iam, org, *,
                             policy: dict, report: dict, statement: dict,
                             record: dict, receipt: dict, witness: dict,
                             capture: dict, source_file: Path, local_key: str,
                             account: str, region: str,
                             observed_at=None) -> dict:
    common = dict(policy=policy, report=report, statement=statement,
                  record=record, receipt=receipt, witness=witness,
                  capture=capture, source_file=source_file,
                  local_key=local_key, account=account, region=region)
    try:
        census = observe_access_surface(s3, sts, s3control, iam, org,
                                        **common, observed_at=observed_at)
        start_role = _role(iam, sts, account=account, include_entries=True)
        start_scp = _scp(org, account=account, include_entries=True)
        if (start_role[0] != census["sts_caller_arn_sha256"] or
            start_role[1] != census["caller_role_arn_sha256"] or
            start_role[2] != census["caller_permissions_boundary_present"] or
            start_role[3] != census["caller_role_attachment_count"] or
            start_role[4] != census["caller_role_inline_count"] or
            start_role[5] != census["caller_role_inventory_sha256"] or
            start_scp[:3] != (census["scp_targets_count"],
                             census["scp_attachment_count"],
                             census["scp_inventory_sha256"])):
            raise PolicyAuditError("IAM/SCP list no longer matches signed census.")
        documents = (_iam_documents(iam, start_role[6]) +
                     _scp_documents(org, start_scp[3]))
        if len(documents) > MAX_DOCUMENTS:
            raise PolicyAuditError("Policy document budget exceeded.")
        # Reject a change to attachments/role/boundary/SCP inheritance during
        # document reads. Individual managed-policy version changed during
        # reads is not a full snapshot; repeat/get_policy default at end.
        end_role = _role(iam, sts, account=account)
        end_scp = _scp(org, account=account)
        if start_role[:6] != end_role or start_scp[:3] != end_scp:
            raise PolicyAuditError("Policy attachments or OU ancestry changed.")
        docs_sorted = sorted(documents, key=lambda d: (d["kind"], d["identifier_sha256"]))
        findings = {field: sum(d["findings"][field] for d in docs_sorted)
                    for field in FINDING_FIELDS}
    except (ValueError, TypeError, KeyError, OSError):
        raise PolicyAuditError("IAM/SCP document analysis incomplete.") from None
    unsigned = {
        "schema_version": SCHEMA, "scope": SCOPE, "access_census": census,
        "observed_at_utc": census["observed_at_utc"],
        "policy_count": len(docs_sorted),
        "iam_managed_policy_count": sum(d["kind"] == "iam_managed" for d in docs_sorted),
        "iam_inline_policy_count": sum(d["kind"] == "iam_inline" for d in docs_sorted),
        "scp_policy_count": sum(d["kind"] == "scp" for d in docs_sorted),
        "policy_documents_projection_sha256": digest(encode(docs_sorted)),
        "policy_indicators": findings,
        "doc_reads_bound_to_attachment_inventory": True,
        "iam_effective_permissions_calculated": False,
        "scp_effective_permissions_calculated": False,
        "policy_conditions_semantically_evaluated": False,
        "all_external_grants_and_trust_evaluated": False,
        "source_and_archive_rights_approved": False,
        "research_release_status": "HOLD",
    }
    return {**unsigned, "report_hmac": _sign(unsigned, local_key)}


def verify_policy_report(result: object, *, policy: dict, report: dict,
                         statement: dict, record: dict, receipt: dict,
                         witness: dict, capture: dict, source_file: Path,
                         local_key: str, account: str, region: str) -> None:
    if not isinstance(result, dict) or set(result) != REPORT_FIELDS:
        raise PolicyAuditError("Policy report schema invalid.")
    if (result["schema_version"] != SCHEMA or result["scope"] != SCOPE or
        result["research_release_status"] != "HOLD" or
        result["doc_reads_bound_to_attachment_inventory"] is not True or
        any(result[x] is not False for x in (
            "iam_effective_permissions_calculated",
            "scp_effective_permissions_calculated",
            "policy_conditions_semantically_evaluated",
            "all_external_grants_and_trust_evaluated",
            "source_and_archive_rights_approved"))
        or not _sha(result["policy_documents_projection_sha256"])):
        raise PolicyAuditError("Policy report trust status invalid.")
    for key in ("policy_count", "iam_managed_policy_count",
                "iam_inline_policy_count", "scp_policy_count"):
        if type(result[key]) is not int or not 0 <= result[key] <= MAX_DOCUMENTS:
            raise PolicyAuditError("Policy report count invalid.")
    if result["policy_count"] != (
        result["iam_managed_policy_count"] + result["iam_inline_policy_count"] +
        result["scp_policy_count"]
    ):
        raise PolicyAuditError("Policy report totals inconsistent.")
    findings = result["policy_indicators"]
    if (not isinstance(findings, dict) or set(findings) != FINDING_FIELDS or
        any(type(v) is not int or not 0 <= v <=
            result["policy_count"] * MAX_STATEMENTS for v in findings.values())):
        raise PolicyAuditError("Policy indicators invalid.")
    try:
        verify_access_surface(
            result["access_census"], policy=policy, report=report,
            statement=statement, record=record, receipt=receipt,
            witness=witness, capture=capture, source_file=source_file,
            local_key=local_key, account=account, region=region)
    except (ValueError, TypeError, KeyError, OSError):
        raise PolicyAuditError("Signed parent access census invalid.") from None
    if result["observed_at_utc"] != result["access_census"]["observed_at_utc"]:
        raise PolicyAuditError("Policy report observation time inconsistent.")
    unsigned = {k: v for k, v in result.items() if k != "report_hmac"}
    if (not _sha(result["report_hmac"]) or not hmac.compare_digest(
        result["report_hmac"], _sign(unsigned, local_key)
    )):
        raise PolicyAuditError("Policy report signature invalid.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "verify"):
        p = sub.add_parser(action)
        for item in ("source-file", "source-record", "receipt", "witness",
                     "capture-manifest", "trusted-policy", "archive-report",
                     "signed-statement"):
            p.add_argument("--" + item, type=Path, required=True)
        p.add_argument("--aws-region", required=True)
        p.add_argument("--expected-bucket-owner", required=True)
        p.add_argument("--local-key-file", type=Path)
        if action == "inspect":
            p.add_argument("--aws-profile", required=True)
            p.add_argument("--ack-read-only-policy-documents", action="store_true")
            p.add_argument("--output", type=Path, required=True)
        else:
            p.add_argument("--observation", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "inspect" and not args.ack_read_only_policy_documents:
        print("[BLOCKED] IAM/SCP policy document read authorization required.")
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
            clients = live_clients(profile=args.aws_profile, region=args.aws_region,
                                   account=args.expected_bucket_owner)
            result = observe_policy_documents(*clients, **common)
            _write_private(args.output, result)
        else:
            verify_policy_report(_strict_json(args.observation, MAX_AUDIT_BYTES),
                                 **common)
        print("[OK] Bounded IAM/SCP document indicators verified; "
              "effective permissions NOT evaluated; release HOLD.")
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        print("[FAIL] IAM/SCP policy document analysis rejected.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
