#!/usr/bin/env python3
"""v0.8.20: bounded S3 resource policy / IAM role-trust structural census.

Read-only. Compares bucket policy, each VPC-only bucket Access Point policy,
and the same-account caller role's AssumeRolePolicyDocument against the
v0.8.19 signed AWS source/role/Access Point chain. This yields *structural
indicators*, NOT a statement about actual cross-account authorization,
effective permissions, full resource-policy coverage or source rights.
"""
from __future__ import annotations

import argparse
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
    _access_points, _pages, _role, _call, _sha,
    MAX_ACCESS_POINTS, SAFE_AP,
)
from scripts.aws_policy_revision import (
    observe_revision, verify_revision, live_clients,
)
from scripts.aws_policy_documents import (
    MAX_DOCUMENT_BYTES, MAX_STATEMENTS, _unique_pairs,
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

SCHEMA = "0.8.20"
SCOPE = "signed_bounded_s3_bucket_accesspoint_and_role_trust_policy_shapes"
DOMAIN = b"neo4j-resource-trust-policy-v0.8.20\n"
MAX_REPORT_BYTES = 110_000
MAX_POLICY_ITEMS = MAX_ACCESS_POINTS + 2
HEX = re.compile(r"^[0-9a-f]{64}$")
ACCOUNT = re.compile(r"^[0-9]{12}$")
POLICY_TOP = frozenset({"Version", "Id", "Statement"})
POLICY_STMT = frozenset({
    "Sid", "Effect", "Action", "NotAction", "Resource",
    "NotResource", "Principal", "NotPrincipal", "Condition",
})
PRINCIPAL_KINDS = frozenset({"AWS", "Service", "Federated", "CanonicalUser"})
INDICATORS = frozenset({
    "allow_wildcard_principal_statements",
    "allow_explicit_foreign_account_principal_statements",
    "allow_nonaccount_or_unclassified_principal_statements",
    "allow_service_or_federated_principal_statements",
    "allow_with_conditions_statements",
    "allow_notprincipal_statements",
    "allow_notaction_or_notresource_statements",
    "explicit_deny_statements",
    "allow_assume_role_action_statements",
    "total_statements_examined",
})
FALSE_FIELDS = (
    "all_resource_policies_examined",
    "cross_account_access_proven",
    "effective_permission_decision_computed",
    "role_trust_conditions_evaluated",
    "aws_policy_snapshot_isolated",
    "license_or_research_release_authorized",
)
REPORT_FIELDS = frozenset({
    "schema_version", "scope", "parent_revision_report",
    "observed_at_utc", "resource_policy_count",
    "bucket_policy_count", "access_point_policy_count",
    "role_trust_policy_count", "two_policy_rounds_match",
    "resource_policy_projection_sha256", "policy_indicators",
    "scoped_bucket_access_point_and_role_metadata_rechecked",
    "unreviewed_resource_routes", *FALSE_FIELDS,
    "research_release_status", "report_hmac",
})
UNREVIEWED = [
    "cross_account_iam_and_session_policy_semantics",
    "vpc_endpoint_and_organization_rcp_policies",
    "multi_region_and_object_lambda_access_points",
    "s3_access_grants_and_external_resource_policies",
    "aws_global_authorization_and_service_context",
]


class ResourceTrustError(ValueError):
    """Never include raw AWS credentials, account, principal or policy."""


def _sign(body: dict, key: str) -> str:
    if not isinstance(key, str) or len(key) < 40:
        raise ResourceTrustError("Local HMAC signing key invalid.")
    return hmac.new(key.encode(), DOMAIN + encode(body),
                    hashlib.sha256).hexdigest()


def _strings(value: object, *, label: str) -> list[str]:
    items = [value] if isinstance(value, str) else value
    if (not isinstance(items, list) or not 1 <= len(items) <= 150 or
        any(not isinstance(v, str) or not v or len(v) > 1024 or
            any(ord(ch) < 32 or ord(ch) == 127 for ch in v)
            for v in items)):
        raise ResourceTrustError("Policy " + label + " is not bounded strings.")
    return items


def _principal(value: object) -> dict[str, list[str]]:
    if isinstance(value, str):
        if value != "*":
            raise ResourceTrustError("Unclassified string principal selector.")
        return {"AWS": ["*"]}
    if not isinstance(value, dict) or not 1 <= len(value) <= 4 or (
        not set(value).issubset(PRINCIPAL_KINDS)
    ):
        raise ResourceTrustError("Principal/NotPrincipal structure unsupported.")
    return {key: _strings(items, label="principal") for key, items in value.items()}


def _document(raw: object, *, kind: str) -> dict:
    if kind not in ("bucket", "access_point", "role_trust"):
        raise ResourceTrustError("Policy document source kind invalid.")
    if isinstance(raw, str):
        if not 0 < len(raw.encode("utf-8")) <= MAX_DOCUMENT_BYTES:
            raise ResourceTrustError("Policy document byte limit invalid.")
        try:
            raw = json.loads(unquote(raw), object_pairs_hook=_unique_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeError, TypeError):
            raise ResourceTrustError("Policy document JSON malformed.") from None
    if not isinstance(raw, dict) or not set(raw).issubset(POLICY_TOP) or (
        raw.get("Version") not in ("2012-10-17", "2008-10-17")
    ):
        raise ResourceTrustError("Policy document schema invalid.")
    statements = raw.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list) or not 1 <= len(statements) <= MAX_STATEMENTS:
        raise ResourceTrustError("Policy statement count invalid.")
    for statement in statements:
        if not isinstance(statement, dict) or not set(statement).issubset(POLICY_STMT) or (
            statement.get("Effect") not in ("Allow", "Deny") or
            ("Action" in statement) == ("NotAction" in statement) or
            ("Principal" in statement) == ("NotPrincipal" in statement) or
            ("Resource" in statement) and ("NotResource" in statement)
        ):
            raise ResourceTrustError("Policy statement shape invalid.")
        for key in ("Action", "NotAction", "Resource", "NotResource"):
            if key in statement:
                _strings(statement[key], label="action/resource")
        for key in ("Principal", "NotPrincipal"):
            if key in statement:
                _principal(statement[key])
        condition = statement.get("Condition")
        if condition is not None:
            if not isinstance(condition, dict) or not condition:
                raise ResourceTrustError("Policy condition object invalid.")
            # The conditions are NOT evaluated. Bound nested raw data and
            # validate its canonical JSON serializability/size below.
        if kind in ("bucket", "access_point") and (
            "Resource" not in statement and "NotResource" not in statement
        ):
            raise ResourceTrustError("S3 policy statement missing resource.")
    doc = {**raw, "Statement": statements}
    try:
        payload = encode(doc)
    except (TypeError, ValueError, UnicodeError):
        raise ResourceTrustError("Policy cannot be serialized canonically.") from None
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ResourceTrustError("Policy document exceeds safety cap.")
    return doc


def _aws_principal_account(value: str) -> str | None:
    if ACCOUNT.fullmatch(value):
        return value
    match = re.fullmatch(
        r"arn:aws:(?:iam|sts)::([0-9]{12}):[A-Za-z0-9_+=,.@*/-]{1,350}",
        value,
    )
    return match.group(1) if match else None


def _indicators(doc: dict, *, owner: str) -> dict[str, int]:
    if not ACCOUNT.fullmatch(owner):
        raise ResourceTrustError("Expected account identity invalid.")
    counts = {name: 0 for name in INDICATORS}
    for statement in doc["Statement"]:
        counts["total_statements_examined"] += 1
        if statement["Effect"] == "Deny":
            counts["explicit_deny_statements"] += 1
            continue
        if "Condition" in statement:
            counts["allow_with_conditions_statements"] += 1
        if "NotPrincipal" in statement:
            counts["allow_notprincipal_statements"] += 1
            continue
        if "NotAction" in statement or "NotResource" in statement:
            counts["allow_notaction_or_notresource_statements"] += 1
        selectors = _principal(statement["Principal"])
        all_values = [v for vs in selectors.values() for v in vs]
        if "*" in all_values:
            counts["allow_wildcard_principal_statements"] += 1
        foreign = False
        unclassified = False
        service = any(k in selectors for k in ("Service", "Federated", "CanonicalUser"))
        for principal in selectors.get("AWS", []):
            if principal == "*":
                continue
            acct = _aws_principal_account(principal)
            if acct is None:
                unclassified = True
            elif acct != owner:
                foreign = True
        if foreign:
            counts["allow_explicit_foreign_account_principal_statements"] += 1
        if unclassified:
            counts["allow_nonaccount_or_unclassified_principal_statements"] += 1
        if service:
            counts["allow_service_or_federated_principal_statements"] += 1
        actions = _strings(
            statement.get("Action", ["NOT_ACTION_COMPLEMENT"]),
            label="action",
        )
        if any(a.casefold() in (
            "sts:assumerole", "sts:assumerolewithwebidentity", "sts:*", "*"
        ) for a in actions):
            counts["allow_assume_role_action_statements"] += 1
    return counts


def _scan(s3, sts, control, iam, *, account: str, bucket: str,
          census: dict) -> list[dict]:
    role = _role(iam, sts, account=account, include_entries=True)
    if (role[0] != census["sts_caller_arn_sha256"] or
        role[1] != census["caller_role_arn_sha256"] or
        role[5] != census["caller_role_inventory_sha256"]):
        raise ResourceTrustError("Caller role differs from signed inventory.")
    before_count, before_hash = _access_points(
        control, account=account, bucket=bucket)
    if (before_count != census["bucket_access_point_count"] or
        before_hash != census["bucket_access_point_projection_sha256"]):
        raise ResourceTrustError("Access Point enumeration differs from signed census.")
    points = _pages(
        control, "list_access_points", "AccessPointList",
        args={"AccountId": account, "Bucket": bucket},
        token_key="NextToken", request_token="NextToken",
        page_size="MaxResults", limit=MAX_ACCESS_POINTS)
    names = [x.get("Name") if isinstance(x, dict) else None for x in points]
    if (len(names) != before_count or len(set(names)) != len(names) or
        any(not isinstance(n, str) or not SAFE_AP.fullmatch(n) for n in names)):
        raise ResourceTrustError("Access Point policy listing incomplete.")
    docs = []
    bucket_response = _call(
        s3, "get_bucket_policy", Bucket=bucket, ExpectedBucketOwner=account)
    docs.append(("bucket", bucket,
                 _document(bucket_response.get("Policy"), kind="bucket")))
    for name in sorted(names):
        response = _call(control, "get_access_point_policy",
                         AccountId=account, Name=name)
        docs.append(("access_point", name,
                     _document(response.get("Policy"), kind="access_point")))
    role_name = role[6]["role_name"]
    identity = _call(iam, "get_role", RoleName=role_name).get("Role")
    if (not isinstance(identity, dict) or
        identity.get("Arn") != role[6]["role_arn"]):
        raise ResourceTrustError("IAM trust policy role identity drifted.")
    docs.append(("role_trust", role_name,
                 _document(identity.get("AssumeRolePolicyDocument"),
                           kind="role_trust")))
    after_count, after_hash = _access_points(
        control, account=account, bucket=bucket)
    after_role = _role(iam, sts, account=account)
    if ((after_count, after_hash) != (before_count, before_hash) or
        after_role != role[:6]):
        raise ResourceTrustError("Access Point/role membership drifted.")
    return [{
        "kind": kind,
        "identifier_sha256": digest(identity.encode("utf-8")),
        "document_sha256": digest(encode(doc)),
        "indicators": _indicators(doc, owner=account),
    } for kind, identity, doc in sorted(docs, key=lambda x: (x[0], x[1]))]


def observe_resource_trust(
    s3, sts, s3control, iam, org, *, policy: dict, report: dict,
    statement: dict, record: dict, receipt: dict, witness: dict,
    capture: dict, source_file: Path, local_key: str, account: str,
    region: str, observed_at=None,
) -> dict:
    common = dict(
        policy=policy, report=report, statement=statement,
        record=record, receipt=receipt, witness=witness,
        capture=capture, source_file=source_file,
        local_key=local_key, account=account, region=region,
    )
    try:
        parent = observe_revision(
            s3, sts, s3control, iam, org, **common, observed_at=observed_at)
        census = parent["parent_policy_report"]["access_census"]
        rounds = [
            _scan(s3, sts, s3control, iam, account=account,
                  bucket=report["bucket"], census=census),
            _scan(s3, sts, s3control, iam, account=account,
                  bucket=report["bucket"], census=census),
        ]
        if rounds[0] != rounds[1]:
            raise ResourceTrustError("Bucket, Access Point or role trust policy drift.")
        rows = rounds[0]
        if len(rows) != census["bucket_access_point_count"] + 2:
            raise ResourceTrustError("Resource policy coverage count mismatch.")
        summary = {
            field: sum(x["indicators"][field] for x in rows)
            for field in INDICATORS
        }
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        raise ResourceTrustError("AWS resource/trust policy audit incomplete.") from None
    unsigned = {
        "schema_version": SCHEMA, "scope": SCOPE,
        "parent_revision_report": parent,
        "observed_at_utc": parent["observed_at_utc"],
        "resource_policy_count": len(rows),
        "bucket_policy_count": 1,
        "access_point_policy_count": len(rows) - 2,
        "role_trust_policy_count": 1,
        "two_policy_rounds_match": True,
        "resource_policy_projection_sha256": digest(encode(rows)),
        "policy_indicators": summary,
        "scoped_bucket_access_point_and_role_metadata_rechecked": True,
        "unreviewed_resource_routes": list(UNREVIEWED),
        **{name: False for name in FALSE_FIELDS},
        "research_release_status": "HOLD",
    }
    return {**unsigned, "report_hmac": _sign(unsigned, local_key)}


def verify_resource_trust(
    result: object, *, policy: dict, report: dict, statement: dict,
    record: dict, receipt: dict, witness: dict, capture: dict,
    source_file: Path, local_key: str, account: str, region: str,
) -> None:
    if not isinstance(result, dict) or set(result) != REPORT_FIELDS:
        raise ResourceTrustError("Resource trust report schema invalid.")
    if (result["schema_version"] != SCHEMA or result["scope"] != SCOPE or
        result["research_release_status"] != "HOLD" or
        result["two_policy_rounds_match"] is not True or
        result["scoped_bucket_access_point_and_role_metadata_rechecked"] is not True or
        result["unreviewed_resource_routes"] != UNREVIEWED or
        any(result[key] is not False for key in FALSE_FIELDS)):
        raise ResourceTrustError("Resource trust approval/scope flags invalid.")
    count = result["resource_policy_count"]
    if (type(count) is not int or not 2 <= count <= MAX_POLICY_ITEMS or
        result["bucket_policy_count"] != 1 or
        result["role_trust_policy_count"] != 1 or
        type(result["access_point_policy_count"]) is not int or
        result["access_point_policy_count"] != count - 2 or
        not _sha(result["resource_policy_projection_sha256"])):
        raise ResourceTrustError("Resource trust report counts invalid.")
    indicators = result["policy_indicators"]
    if (not isinstance(indicators, dict) or set(indicators) != INDICATORS or
        any(type(v) is not int or not 0 <= v <= count * MAX_STATEMENTS
            for v in indicators.values())):
        raise ResourceTrustError("Resource policy indicator envelope invalid.")
    try:
        verify_revision(
            result["parent_revision_report"], policy=policy, report=report,
            statement=statement, record=record, receipt=receipt,
            witness=witness, capture=capture, source_file=source_file,
            local_key=local_key, account=account, region=region,
        )
    except (ValueError, TypeError, KeyError, OSError):
        raise ResourceTrustError("Parent policy revision chain invalid.") from None
    parent = result["parent_revision_report"]
    census = parent["parent_policy_report"]["access_census"]
    if (result["observed_at_utc"] != parent["observed_at_utc"] or
        result["access_point_policy_count"] != census["bucket_access_point_count"]):
        raise ResourceTrustError("Bounded Access Point count/capture mismatch.")
    unsigned = {k: v for k, v in result.items() if k != "report_hmac"}
    mac = result["report_hmac"]
    if (not _sha(mac) or
        not hmac.compare_digest(mac, _sign(unsigned, local_key))):
        raise ResourceTrustError("Resource trust report HMAC invalid.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "verify"):
        p = sub.add_parser(action)
        for item in (
            "source-file", "source-record", "receipt", "witness",
            "capture-manifest", "trusted-policy", "archive-report",
            "signed-statement",
        ):
            p.add_argument("--" + item, type=Path, required=True)
        p.add_argument("--aws-region", required=True)
        p.add_argument("--expected-bucket-owner", required=True)
        p.add_argument("--local-key-file", type=Path)
        if action == "inspect":
            p.add_argument("--aws-profile", required=True)
            p.add_argument("--ack-read-only-resource-policy-audit",
                           action="store_true")
            p.add_argument("--output", type=Path, required=True)
        else:
            p.add_argument("--observation", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "inspect" and not args.ack_read_only_resource_policy_audit:
        print("[BLOCKED] AWS resource-policy read consent required.")
        return 2
    try:
        secret = load_token(args.local_key_file or signature_key_path())
        common = dict(
            policy=_strict_json(args.trusted_policy, MAX_POLICY_BYTES),
            report=_strict_json(args.archive_report, MAX_ARCHIVE_BYTES),
            statement=_strict_json(args.signed_statement, MAX_ATTESTATION_BYTES),
            record=_load_json(args.source_record, MAX_RECORD_BYTES),
            receipt=_load_json(args.receipt, MAX_RECEIPT_BYTES),
            witness=_load_json(args.witness, MAX_WITNESS_BYTES),
            capture=_load_json(args.capture_manifest, MAX_CAPTURE_BYTES),
            source_file=args.source_file, local_key=secret,
            account=args.expected_bucket_owner, region=args.aws_region,
        )
        if args.action == "inspect":
            from scripts.live_s3_version_verify import _chain
            _chain(
                common["policy"], common["report"], common["statement"],
                common["record"], common["receipt"], common["witness"],
                common["capture"], common["source_file"], secret,
            )
            clients = live_clients(
                profile=args.aws_profile, region=args.aws_region,
                account=args.expected_bucket_owner)
            data = observe_resource_trust(*clients, **common)
            _write_private(args.output, data)
        else:
            verify_resource_trust(
                _strict_json(args.observation, MAX_REPORT_BYTES), **common)
        print("[OK] Bounded resource/trust policy shapes reviewed;"
              " effective cross-account access UNVERIFIED; research HOLD.")
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        print("[FAIL] S3 resource/trust policy audit rejected or incomplete.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
