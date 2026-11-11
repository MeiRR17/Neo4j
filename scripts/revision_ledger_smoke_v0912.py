#!/usr/bin/env python3
"""Real disposable Neo4j smoke for synthetic v0.9.12 revision-ledger CAS.

Signed v0.9.11 input is generated from a synthetic in-memory Work graph.
Only the new metadata-only ledger nodes are created in local CI Neo4j.
Both fixed-scope head and revisions are removed with exact-ID checks.
Never run this against a real research database.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from scripts.bootstrap import DEFAULT_SECRET_PATH
from scripts.migrate import LocalQueryClient
from services.research_api.audit_export_v0911 import export_work_link_audit
from services.research_api.config import load_token
from services.research_api.revision_ledger_v0912 import (
    ZERO_CHAIN, RevisionLedgerError, append_revision,
    bootstrap_head, head_for, scope_id, verify_revision_chain,
)
from tests.test_work_link_audit_v099 import AuditStore
from tests.test_work_comparison import LEFT, RIGHT


def run(*, url: str = "http://127.0.0.1:7474",
        secret_path: Path = DEFAULT_SECRET_PATH) -> dict:
    if os.getenv("CI") != "true":
        raise RevisionLedgerError("Disposable CI is required for revision smoke.")
    client = LocalQueryClient(url, secret_path)
    token = load_token()
    signed = export_work_link_audit(
        AuditStore(),source_work_id=LEFT,target_work_id=RIGHT,
        secret=token,now=1234567890,
    )
    scope = scope_id(LEFT, RIGHT)
    if head_for(client, LEFT, RIGHT) is not None:
        raise RevisionLedgerError("Refusing occupied ledger fixture scope.")
    bootstrapped = False
    first = second = None
    try:
        bootstrapped = True
        initial = bootstrap_head(client, signed, secret=token)
        if initial["sequence"] != 0 or initial["chain_sha256"] != ZERO_CHAIN:
            raise RevisionLedgerError("Unexpected initialized ledger head.")
        first = append_revision(
            client,signed,secret=token,expected_sequence=0,
            expected_chain_sha256=ZERO_CHAIN,now=1234567891,
        )
        try:
            append_revision(
                client,signed,secret=token,expected_sequence=0,
                expected_chain_sha256=ZERO_CHAIN,now=1234567892,
            )
        except RevisionLedgerError:
            pass
        else:
            raise RevisionLedgerError("Stale append was not denied.")
        if head_for(client,LEFT,RIGHT)["sequence"] != 1:
            raise RevisionLedgerError("Rejected stale append changed head.")
        second = append_revision(
            client,signed,secret=token,expected_sequence=1,
            expected_chain_sha256=first["chain_sha256"],now=1234567892,
        )
        report = verify_revision_chain(client, LEFT, RIGHT)
        if (report["verified_record_count"] != 2 or
                report["latest_revision_id"] != second["revision_id"] or
                report["chain_sha256"] != second["chain_sha256"] or
                report["work_graph_immutable"] is not False or
                report["research_release_status"] != "HOLD"):
            raise RevisionLedgerError("Synthetic revision chain not verified.")
        return {
            "schema_version": "0.9.12",
            "schema_revision_nodes_written": 2,
            "stale_cas_denied": True,
            "verified_chain_length": 2,
            "source_records_written": 0,
            "graph_snapshot_verified": False,
            "corpus_revision_immutable": False,
            "research_release_status": "HOLD",
        }
    finally:
        if bootstrapped:
            revs = client.query(
                "MATCH (r:AuditRevision {scope_id:$scope}) "
                "DETACH DELETE r RETURN count(r) AS removed",
                {"scope":scope},
            )
            head = client.query(
                "MATCH (h:AuditRevisionHead {id:$scope}) "
                "DETACH DELETE h RETURN count(h) AS removed",
                {"scope":scope},
            )
            if (revs != [[(1 if first is not None else 0) +
                           (1 if second is not None else 0)]] or
                    head != [[1]] or
                    head_for(client,LEFT,RIGHT) is not None):
                raise RevisionLedgerError("Synthetic ledger cleanup failed.")


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ack-disposable-fixture",action="store_true")
    parser.add_argument("--url",default="http://127.0.0.1:7474")
    parser.add_argument("--secret",type=Path,default=DEFAULT_SECRET_PATH)
    args=parser.parse_args(argv)
    if os.getenv("CI") != "true" or not args.ack_disposable_fixture:
        print("[BLOCKED] Explicit disposable CI approval required.")
        return 2
    try:
        outcome=run(url=args.url,secret_path=args.secret)
        print(json.dumps(outcome,sort_keys=True,separators=(",",":")))
        return 0
    except (ValueError,RuntimeError,OSError):
        print("[FAIL] Metadata-only ledger smoke failed or cleanup incomplete.")
        return 1


if __name__=="__main__":
    raise SystemExit(main())
