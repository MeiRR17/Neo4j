#!/usr/bin/env python3
"""v0.8.17: bounded IAM/Organizations/S3 Access Point inventory (read-only).

This collects *visible attachment and configuration metadata*, not evaluated
effective permissions. AWS resource policies, condition keys, SCP semantics,
Access Point aliases/other data sources, external accounts and unobserved
principals remain unverified. No claim of complete IAM safety is made.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import hmac
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.external_archive_attestation import (
    _strict_json, MAX_POLICY_BYTES, MAX_ARCHIVE_BYTES, MAX_ATTESTATION_BYTES,
)
from scripts.live_s3_version_verify import _identity, ACCOUNT
from scripts.s3_governance import (
    GovernanceError, _sign as gov_sign, _status, BLOCK_KEYS,
    observe_governance, verify_governance, live_clients,
)
from scripts.search_capture import digest, encode
from scripts.search_review_workflow import _write_private
from scripts.source_membership import MAX_WITNESS_BYTES
from scripts.source_receipts import (
    _load_json, MAX_CAPTURE_BYTES, MAX_RECORD_BYTES, MAX_RECEIPT_BYTES,
)
from services.research_api.config import load_token
from services.research_api.signature import signature_key_path

SCHEMA = "0.8.17"
DOMAIN = b"neo4j-aws-access-surface-v0.8.17\n"
MAX_REPORT_BYTES = 65536
MAX_ACCESS_POINTS = 100
MAX_IAM_POLICIES = 100
MAX_SCP_POLICIES = 100
MAX_ORG_DEPTH = 6
MAX_PAGES = 5
SAFE_ROLE = re.compile(r"^[A-Za-z0-9_+=,.@-]{1,64}$")
SAFE_AP = re.compile(r"^[a-z0-9][a-z0-9-]{1,49}$")
SAFE_VPC = re.compile(r"^vpc-[a-f0-9]{8,17}$")
SAFE_OU = re.compile(r"^ou-[a-z0-9]{4,32}-[a-z0-9]{8,32}$")
SAFE_ROOT = re.compile(r"^r-[a-z0-9]{4,32}$")
SAFE_POLICY = re.compile(r"^p-[A-Za-z0-9_]{8,128}$")
SAFE_MARKER = re.compile(r"^[A-Za-z0-9+/=_-]{1,1500}$")
HEX = re.compile(r"^[a-f0-9]{64}$")
SCOPE = "bounded_observed_iam_role_scp_ancestry_and_bucket_access_points"
FALSE_CLAIMS = (
    "effective_iam_permissions_verified",
    "scp_policy_semantics_verified",
    "cross_account_resource_policy_verified",
    "all_s3_access_routes_verified",
    "external_immutability_certified",
    "license_and_scholarly_release_approved",
)
SUMMARY_KEYS = frozenset({
    "schema_version", "scope", "prior_governance_observation",
    "observed_at_utc", "aws_region", "expected_bucket_owner_sha256",
    "sts_caller_arn_sha256", "account_public_access_block_confirmed",
    "bucket_access_point_count", "bucket_access_point_projection_sha256",
    "caller_role_arn_sha256", "caller_permissions_boundary_present",
    "caller_role_attachment_count", "caller_role_inline_count",
    "caller_role_inventory_sha256", "scp_targets_count",
    "scp_attachment_count", "scp_inventory_sha256",
    "effective_iam_permissions_verified",
    "scp_policy_semantics_verified", "cross_account_resource_policy_verified",
    "all_s3_access_routes_verified", "external_immutability_certified",
    "license_and_scholarly_release_approved", "release_status", "audit_hmac",
})


class AccessAuditError(ValueError):
    """Redacted error; never include bucket, principal, ARN or policy name."""


def _sha(value: object) -> bool:
    return isinstance(value, str) and HEX.fullmatch(value) is not None


def _sign(unsigned: dict, key: str) -> str:
    if not isinstance(key, str) or len(key) < 40:
        raise AccessAuditError("Local signing key invalid.")
    return hmac.new(key.encode(), DOMAIN + encode(unsigned),
                    hashlib.sha256).hexdigest()


def _call(client, method: str, **kwargs) -> dict:
    try:
        result = getattr(client, method)(**kwargs)
        _status(result)
        return result
    except Exception:
        raise AccessAuditError("Read-only AWS governance inventory unavailable.") from None


def _pages(client, name: str, list_key: str, *,
           args: dict, token_key: str, request_token: str,
           page_size: str, limit: int) -> list:
    output, seen = [], set()
    token = ""
    for _ in range(MAX_PAGES):
        params = {**args, page_size: min(limit, 50)}
        if token:
            params[request_token] = token
        response = _call(client, name, **params)
        entries = response.get(list_key)
        if not isinstance(entries, list) or len(entries) > params[page_size]:
            raise AccessAuditError("AWS inventory page shape invalid.")
        output.extend(entries)
        if len(output) > limit:
            raise AccessAuditError("AWS inventory exceeded safety cap.")
        nxt = response.get(token_key)
        # IAM uses IsTruncated + Marker; a truncated page without Marker
        # must never be mistaken for a complete role-policy inventory.
        truncated = response.get("IsTruncated")
        if truncated is not None and type(truncated) is not bool:
            raise AccessAuditError("AWS truncated-page flag malformed.")
        if truncated is True and not nxt:
            raise AccessAuditError("AWS inventory is truncated without cursor.")
        if truncated is False and nxt:
            raise AccessAuditError("AWS inventory cursor conflicts with completion.")
        if nxt is None or nxt == "":
            return output
        if (not isinstance(nxt, str) or not SAFE_MARKER.fullmatch(nxt) or
            nxt in seen):
            raise AccessAuditError("AWS inventory pagination token repeated.")
        seen.add(nxt)
        token = nxt
    raise AccessAuditError("AWS inventory pagination incomplete.")


def _pab(data: object) -> None:
    block = data.get("PublicAccessBlockConfiguration") if isinstance(data, dict) else None
    if (not isinstance(block, dict) or
        not BLOCK_KEYS.issubset(block) or
        any(block[k] is not True for k in BLOCK_KEYS)):
        raise AccessAuditError("Account public-access block is not complete.")


def _access_points(s3control, *, account: str, bucket: str,
                   include_names: bool = False) -> tuple:
    _pab(_call(s3control, "get_public_access_block", AccountId=account))
    points = _pages(
        s3control, "list_access_points", "AccessPointList",
        args={"AccountId": account, "Bucket": bucket},
        token_key="NextToken", request_token="NextToken",
        page_size="MaxResults", limit=MAX_ACCESS_POINTS)
    names, summaries = set(), []
    for item in points:
        if not isinstance(item, dict):
            raise AccessAuditError("Access Point metadata invalid.")
        name = item.get("Name")
        if (not isinstance(name, str) or not SAFE_AP.fullmatch(name) or
            name in names or item.get("Bucket") != bucket):
            raise AccessAuditError("Access Point identity is out of audit scope.")
        names.add(name)
        detail = _call(s3control, "get_access_point", AccountId=account, Name=name)
        policy = _call(s3control, "get_access_point_policy_status",
                       AccountId=account, Name=name)
        status = policy.get("PolicyStatus")
        if (not isinstance(status, dict) or
            status.get("IsPublic") is not False or
            detail.get("Bucket") != bucket or detail.get("Name") != name or
            detail.get("NetworkOrigin") != "VPC"):
            raise AccessAuditError("Access Point policy/network not restricted.")
        vpc = detail.get("VpcConfiguration")
        if (not isinstance(vpc, dict) or
            not isinstance(vpc.get("VpcId"), str) or
            not SAFE_VPC.fullmatch(vpc["VpcId"])):
            raise AccessAuditError("Access Point VPC identity invalid.")
        _pab({"PublicAccessBlockConfiguration":
              detail.get("PublicAccessBlockConfiguration")})
        summaries.append({
            "name_sha256": digest(name.encode()),
            "vpc_sha256": digest(vpc["VpcId"].encode()),
            "policy_nonpublic": True, "account_block_all_four": True,
        })
    summaries.sort(key=lambda x: x["name_sha256"])
    summary = (len(summaries), digest(encode(summaries)))
    # v0.8.20: return names ONLY to the in-memory policy scanner that
    # just authenticated their bounded S3Control metadata. Names are
    # NEVER written to the HMAC audit report.
    return (*summary, sorted(names)) if include_names else summary


def _role(iam, sts, *, account: str, include_entries: bool = False) -> tuple:
    identity = _call(sts, "get_caller_identity")
    arn = identity.get("Arn")
    prefix = "arn:aws:sts::" + account + ":assumed-role/"
    if (identity.get("Account") != account or
        not isinstance(arn, str) or not arn.startswith(prefix)):
        raise AccessAuditError("IAM audit requires same-account assumed role.")
    tokens = arn[len(prefix):].split("/")
    if len(tokens) != 2 or not SAFE_ROLE.fullmatch(tokens[0]) or not tokens[1]:
        raise AccessAuditError("STS assumed-role identity ambiguous.")
    role = tokens[0]
    detail = _call(iam, "get_role", RoleName=role).get("Role")
    if not isinstance(detail, dict):
        raise AccessAuditError("IAM role details unavailable.")
    role_arn = detail.get("Arn")
    if (not isinstance(role_arn, str) or not
        role_arn.startswith("arn:aws:iam::" + account + ":role/") or
        role_arn.rsplit("/", 1)[-1] != role):
        raise AccessAuditError("IAM role does not match STS caller.")
    boundary = detail.get("PermissionsBoundary")
    if boundary is not None and (
        not isinstance(boundary, dict) or
        boundary.get("PermissionsBoundaryType") != "Policy" or
        not isinstance(boundary.get("PermissionsBoundaryArn"), str)
    ):
        raise AccessAuditError("IAM permissions boundary invalid.")
    attached = _pages(
        iam, "list_attached_role_policies", "AttachedPolicies",
        args={"RoleName": role},
        token_key="Marker", request_token="Marker",
        page_size="MaxItems", limit=MAX_IAM_POLICIES)
    inline = _pages(
        iam, "list_role_policies", "PolicyNames",
        args={"RoleName": role},
        token_key="Marker", request_token="Marker",
        page_size="MaxItems", limit=MAX_IAM_POLICIES)
    if len(attached) + len(inline) > MAX_IAM_POLICIES:
        raise AccessAuditError("IAM attachment inventory too large.")
    managed_ids, inline_ids = [], []
    for p in attached:
        if (not isinstance(p, dict) or
            not isinstance(p.get("PolicyArn"), str) or
            not (p["PolicyArn"].startswith(
                "arn:aws:iam::" + account + ":policy/") or
                p["PolicyArn"].startswith("arn:aws:iam::aws:policy/"))):
            raise AccessAuditError("IAM attached policy reference invalid.")
        managed_ids.append(p["PolicyArn"])
    for p in inline:
        if not isinstance(p, str) or not SAFE_ROLE.fullmatch(p):
            raise AccessAuditError("IAM inline policy name invalid.")
        inline_ids.append(p)
    if len(set(managed_ids)) != len(managed_ids) or len(set(inline_ids)) != len(inline_ids):
        raise AccessAuditError("Duplicate IAM role policy entry.")
    fingerprint = digest(encode({
        "role_arn": role_arn,
        "permissions_boundary": boundary,
        "attached_policy_arns": sorted(managed_ids),
        "inline_policy_names": sorted(inline_ids),
    }))
    summary = (digest(arn.encode()), digest(role_arn.encode()),
               boundary is not None, len(attached), len(inline), fingerprint)
    if include_entries:
        # Returned to the in-process policy analyzer only; never part of the
        # signed metadata-only census/report.
        return (*summary, {
            "role_name": role, "role_arn": role_arn,
            "permission_boundary": boundary,
            "attached_policy_arns": sorted(managed_ids),
            "inline_policy_names": sorted(inline_ids),
        })
    return summary


def _scp(org, *, account: str, include_entries: bool = False) -> tuple:
    targets, target = [account], account
    for _ in range(MAX_ORG_DEPTH):
        result = _call(org, "list_parents", ChildId=target)
        parents = result.get("Parents")
        if (not isinstance(parents, list) or len(parents) != 1 or
            result.get("NextToken")):
            raise AccessAuditError("Organizations parent lineage incomplete.")
        parent = parents[0]
        if not isinstance(parent, dict):
            raise AccessAuditError("Organizations parent type invalid.")
        identity, typ = parent.get("Id"), parent.get("Type")
        if identity in targets:
            raise AccessAuditError("Organizations parent cycle.")
        if typ == "ROOT" and isinstance(identity, str) and SAFE_ROOT.fullmatch(identity):
            targets.append(identity)
            break
        if (typ != "ORGANIZATIONAL_UNIT" or
            not isinstance(identity, str) or not SAFE_OU.fullmatch(identity)):
            raise AccessAuditError("Unsupported Organizations parent boundary.")
        targets.append(identity)
        target = identity
    else:
        raise AccessAuditError("Organizations parent chain exceeded bound.")
    all_items = []
    for tgt in targets:
        policies = _pages(
            org, "list_policies_for_target", "Policies",
            args={"TargetId": tgt, "Filter": "SERVICE_CONTROL_POLICY"},
            token_key="NextToken", request_token="NextToken",
            page_size="MaxResults", limit=MAX_SCP_POLICIES)
        ids = []
        for policy in policies:
            if (not isinstance(policy, dict) or
                policy.get("Type") != "SERVICE_CONTROL_POLICY" or
                not isinstance(policy.get("Id"), str) or
                not SAFE_POLICY.fullmatch(policy["Id"])):
                raise AccessAuditError("SCP attachment entry invalid.")
            ids.append(policy["Id"])
        if len(set(ids)) != len(ids):
            raise AccessAuditError("Duplicate attached SCP policy.")
        all_items.append({"target": tgt, "attached_scp_ids": sorted(ids)})
    count = sum(len(x["attached_scp_ids"]) for x in all_items)
    if count > MAX_SCP_POLICIES:
        raise AccessAuditError("Total inherited SCP inventory too large.")
    summary = (len(targets), count, digest(encode(all_items)))
    if include_entries:
        return (*summary, all_items)
    return summary


def observe_access_surface(
    s3, sts, s3control, iam, org, *,
    policy: dict, report: dict, statement: dict,
    record: dict, receipt: dict, witness: dict, capture: dict,
    source_file: Path, local_key: str, account: str, region: str,
    observed_at: datetime | None = None,
) -> dict:
    """All AWS metadata reads are read-only; source chain checked first."""
    common = dict(
        policy=policy, report=report, statement=statement, record=record,
        receipt=receipt, witness=witness, capture=capture,
        source_file=source_file, local_key=local_key,
        account=account, region=region)
    try:
        prior = observe_governance(s3, sts, **common, observed_at=observed_at)
        count, points_sha = _access_points(
            s3control, account=account, bucket=report["bucket"])
        arn_sha, role_arn_sha, boundary, attached, inline, role_sha = _role(
            iam, sts, account=account)
        targets, policies, scp_sha = _scp(org, account=account)
    except (ValueError, TypeError, KeyError, OSError):
        raise AccessAuditError("Bounded AWS access inventory incomplete.") from None
    unsigned = {
        "schema_version": SCHEMA, "scope": SCOPE,
        "prior_governance_observation": prior,
        "observed_at_utc": prior["observed_at_utc"],
        "aws_region": region,
        "expected_bucket_owner_sha256": digest(account.encode()),
        "sts_caller_arn_sha256": arn_sha,
        "account_public_access_block_confirmed": True,
        "bucket_access_point_count": count,
        "bucket_access_point_projection_sha256": points_sha,
        "caller_role_arn_sha256": role_arn_sha,
        "caller_permissions_boundary_present": boundary,
        "caller_role_attachment_count": attached,
        "caller_role_inline_count": inline,
        "caller_role_inventory_sha256": role_sha,
        "scp_targets_count": targets,
        "scp_attachment_count": policies,
        "scp_inventory_sha256": scp_sha,
        **{key: False for key in FALSE_CLAIMS},
        "release_status": "HOLD",
    }
    return {**unsigned, "audit_hmac": _sign(unsigned, local_key)}


def verify_access_surface(
    result: object, *, policy: dict, report: dict, statement: dict,
    record: dict, receipt: dict, witness: dict, capture: dict,
    source_file: Path, local_key: str, account: str, region: str,
) -> None:
    if not isinstance(result, dict) or set(result) != SUMMARY_KEYS:
        raise AccessAuditError("Access inventory schema invalid.")
    if (result["schema_version"] != SCHEMA or result["scope"] != SCOPE or
        result["release_status"] != "HOLD" or
        result["account_public_access_block_confirmed"] is not True or
        any(result[k] is not False for k in FALSE_CLAIMS) or
        result["aws_region"] != region or
        result["expected_bucket_owner_sha256"] != digest(account.encode())):
        raise AccessAuditError("Access inventory trust status invalid.")
    for key in (
        "bucket_access_point_projection_sha256", "caller_role_arn_sha256",
        "caller_role_inventory_sha256", "scp_inventory_sha256",
        "sts_caller_arn_sha256",
    ):
        if not _sha(result[key]):
            raise AccessAuditError("Access inventory fingerprint invalid.")
    for k, maxval in (
        ("bucket_access_point_count", MAX_ACCESS_POINTS),
        ("caller_role_attachment_count", MAX_IAM_POLICIES),
        ("caller_role_inline_count", MAX_IAM_POLICIES),
        ("scp_attachment_count", MAX_SCP_POLICIES),
    ):
        if type(result[k]) is not int or not 0 <= result[k] <= maxval:
            raise AccessAuditError("Access inventory count invalid.")
    if (type(result["scp_targets_count"]) is not int or
        not 2 <= result["scp_targets_count"] <= MAX_ORG_DEPTH + 1 or
        type(result["caller_permissions_boundary_present"]) is not bool):
        raise AccessAuditError("Role/SCP inventory shape invalid.")
    common = dict(
        policy=policy, report=report, statement=statement, record=record,
        receipt=receipt, witness=witness, capture=capture,
        source_file=source_file, local_key=local_key, account=account,
        region=region)
    try:
        verify_governance(result["prior_governance_observation"], **common)
    except (ValueError, TypeError, KeyError, OSError):
        raise AccessAuditError("Nested S3 governance proof invalid.") from None
    if result["observed_at_utc"] != result["prior_governance_observation"]["observed_at_utc"]:
        raise AccessAuditError("Access inventory timestamp differs.")
    unsigned = {k: v for k, v in result.items() if k != "audit_hmac"}
    if (not _sha(result["audit_hmac"]) or
        not hmac.compare_digest(result["audit_hmac"], _sign(unsigned, local_key))):
        raise AccessAuditError("Access inventory local signature invalid.")


def live_clients(*, profile: str, region: str, account: str):
    """Explicit named AWS account; no injected endpoints or implicit profiles."""
    try:
        _identity(profile, region, account)
        import boto3
        from botocore.config import Config
        session = boto3.Session(profile_name=profile, region_name=region)
        config = Config(
            retries={"max_attempts": 1, "mode": "standard"},
            connect_timeout=5, read_timeout=10)
        s3, sts = __import__("scripts.s3_governance", fromlist=["live_clients"]).live_clients(
            profile=profile, region=region, account=account)
        control = session.client(
            "s3control", region_name=region,
            endpoint_url="https://s3-control." + region + ".amazonaws.com",
            config=config)
        iam = session.client(
            "iam", region_name="us-east-1",
            endpoint_url="https://iam.amazonaws.com", config=config)
        org = session.client(
            "organizations", region_name="us-east-1",
            endpoint_url="https://organizations.us-east-1.amazonaws.com",
            config=config)
        return s3, sts, control, iam, org
    except Exception:
        raise AccessAuditError("Pinned AWS inventory clients unavailable.") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("inspect", "verify"):
        p = sub.add_parser(mode)
        for name in (
            "source-file", "source-record", "receipt", "witness",
            "capture-manifest", "trusted-policy", "archive-report",
            "signed-statement",
        ):
            p.add_argument("--" + name, type=Path, required=True)
        p.add_argument("--aws-region", required=True)
        p.add_argument("--expected-bucket-owner", required=True)
        p.add_argument("--local-key-file", type=Path)
        if mode == "inspect":
            p.add_argument("--aws-profile", required=True)
            p.add_argument("--ack-read-only-aws-policy-inventory",
                           action="store_true")
            p.add_argument("--output", type=Path, required=True)
        else:
            p.add_argument("--observation", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.mode == "inspect" and not args.ack_read_only_aws_policy_inventory:
        print("[BLOCKED] Explicit authorized AWS inventory acknowledgment required.")
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
        if args.mode == "inspect":
            # No remote client until original local trust chain is validated.
            from scripts.live_s3_version_verify import _chain
            _chain(common["policy"], common["report"], common["statement"],
                   common["record"], common["receipt"], common["witness"],
                   common["capture"], common["source_file"], key)
            clients = live_clients(
                profile=args.aws_profile, region=args.aws_region,
                account=args.expected_bucket_owner)
            outcome = observe_access_surface(*clients, **common)
            _write_private(args.output, outcome)
        else:
            verify_access_surface(
                _strict_json(args.observation, MAX_REPORT_BYTES), **common)
        print("[OK] Bounded read-only access inventory captured; "
              "effective policy unverified; research HOLD.")
        return 0
    except (ValueError, TypeError, KeyError, OSError):
        print("[FAIL] AWS access-surface inventory unavailable or invalid.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
