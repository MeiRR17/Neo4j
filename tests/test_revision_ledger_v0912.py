"""v0.9.12 metadata-only revision ledger CAS, integrity and write guards."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.audit_revision_ledger_v0912 import main as cli_main
from services.research_api.audit_export_v0911 import export_work_link_audit
from services.research_api.config import bootstrap_token, load_token
from services.research_api.revision_ledger_v0912 import (
    APPEND, BOOTSTRAP, HEAD_READ, HISTORY_READ, MAX_REVISIONS,
    RECORD_COLUMNS, RECORD_FIELDS, ZERO_CHAIN, RevisionLedgerError,
    append_revision, bootstrap_head, head_for, scope_id,
    verify_revision_chain,
)
from tests.test_work_link_audit_v099 import AuditStore
from tests.test_work_comparison import LEFT, RIGHT


class FakeClient:
    def __init__(self):
        self.heads = {}
        self.records = {}
        self.calls = []
        self.simulate_concurrent_advance = False

    def query(self, statement, params):
        self.calls.append((statement, deepcopy(params)))
        key = params["scope_id"]
        if statement == HEAD_READ:
            h = self.heads.get(key)
            return [[h[k] for k in (
                "id", "source_work_id", "target_work_id",
                "sequence", "latest_revision_id", "chain_sha256",
            )]] if h is not None else []
        if statement == BOOTSTRAP:
            h = self.heads.setdefault(key, {
                "id": key, "source_work_id": params["source"],
                "target_work_id": params["target"], "sequence": 0,
                "latest_revision_id": "", "chain_sha256": ZERO_CHAIN,
            })
            return [[h[k] for k in (
                "id", "source_work_id", "target_work_id",
                "sequence", "latest_revision_id", "chain_sha256",
            )]]
        if statement == APPEND:
            h = self.heads[key]
            if self.simulate_concurrent_advance:
                return []
            if (h["sequence"] != params["expected_sequence"] or
                    h["chain_sha256"] != params["expected_chain"] or
                    h["latest_revision_id"] != params["previous_revision_id"]):
                return []
            record = {k:params[k] for k in RECORD_FIELDS}
            record.update(id=params["revision_id"],
                          chain_sha256=params["chain_sha256"])
            self.records.setdefault(key, []).append(record)
            h["sequence"] = params["sequence"]
            h["latest_revision_id"] = params["revision_id"]
            h["chain_sha256"] = params["chain_sha256"]
            return [[h["sequence"], h["latest_revision_id"], h["chain_sha256"]]]
        if statement == HISTORY_READ:
            return [
                [r[k] for k in RECORD_COLUMNS]
                for r in self.records.get(key, [])
            ][:params["fetch_limit"]]
        raise AssertionError("Unexpected graph statement in fixed registry")


class RevisionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.secret = "x" * 48
        self.export = export_work_link_audit(
            AuditStore(), source_work_id=LEFT,
            target_work_id=RIGHT, secret=self.secret, now=1234567890,
        )

    def bootstrap(self):
        return bootstrap_head(self.client, self.export, secret=self.secret)

    def append(self, seq=0, previous=ZERO_CHAIN, now=1234567891):
        return append_revision(
            self.client, self.export, secret=self.secret,
            expected_sequence=seq, expected_chain_sha256=previous,
            now=now,
        )

    def test_scope_is_directional_and_is_not_a_work_node(self):
        self.assertEqual(scope_id(LEFT, RIGHT), scope_id(LEFT, RIGHT))
        self.assertNotEqual(scope_id(LEFT, RIGHT), scope_id(RIGHT, LEFT))
        self.assertTrue(scope_id(LEFT, RIGHT).startswith("audit-scope:"))
        with self.assertRaises(RevisionLedgerError):
            scope_id(LEFT, LEFT)

    def test_bootstrap_is_idempotent_and_never_resets_history(self):
        h = self.bootstrap()
        self.assertEqual(h["sequence"], 0)
        self.assertEqual(h["chain_sha256"], ZERO_CHAIN)
        first = self.append()
        self.assertEqual(self.bootstrap()["sequence"], 1)
        self.assertEqual(head_for(self.client, LEFT, RIGHT)["chain_sha256"],
                         first["chain_sha256"])

    def test_two_appends_produce_monotonic_tamper_evident_chain(self):
        self.bootstrap()
        first = self.append(now=1234567891)
        second = self.append(
            seq=1, previous=first["chain_sha256"], now=1234567892)
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(second["previous_chain_sha256"],
                         first["chain_sha256"])
        self.assertNotEqual(first["revision_id"], second["revision_id"])
        chain = verify_revision_chain(self.client, LEFT, RIGHT)
        self.assertEqual(chain["verified_record_count"], 2)
        self.assertEqual(chain["latest_revision_id"], second["revision_id"])
        self.assertTrue(chain["append_only_enforced_for_cooperating_writer"])
        self.assertFalse(chain["privileged_db_tampering_excluded"])
        self.assertFalse(chain["work_graph_immutable"])
        self.assertEqual(chain["research_release_status"], "HOLD")

    def test_stale_expected_head_rejected_without_second_write(self):
        self.bootstrap()
        first = self.append()
        with self.assertRaises(RevisionLedgerError):
            self.append()
        self.assertEqual(len(self.client.records[scope_id(LEFT, RIGHT)]), 1)
        self.assertEqual(head_for(self.client, LEFT, RIGHT)["sequence"], 1)
        self.client.simulate_concurrent_advance = True
        with self.assertRaises(RevisionLedgerError):
            self.append(seq=1, previous=first["chain_sha256"])

    def test_missing_head_and_bad_expected_values_fail_closed(self):
        with self.assertRaises(RevisionLedgerError):
            self.append()
        self.assertEqual(self.client.records, {})
        self.bootstrap()
        for sequence, chain in (
            (True, ZERO_CHAIN), (-1, ZERO_CHAIN), (33, ZERO_CHAIN),
            (0, "not-a-digest"), (0, True),
        ):
            with self.subTest(sequence=sequence, chain=chain):
                with self.assertRaises(RevisionLedgerError):
                    self.append(seq=sequence, previous=chain)
        self.assertEqual(self.client.records, {})

    def test_bad_export_hmac_or_rights_claim_is_denied_before_write(self):
        for change in ("wrong_hmac", "rights", "extra"):
            bad = deepcopy(self.export)
            if change == "wrong_hmac":
                bad["receipt_hmac_sha256"] = "0" * 64
            if change == "rights":
                bad["manifest"]["independently_licensed_sources_verified"] = True
            if change == "extra":
                bad["manifest"]["source_text"] = "UNLICENSED"
            self.client.calls.clear()
            with self.subTest(change=change), self.assertRaises(RevisionLedgerError):
                bootstrap_head(self.client, bad, secret=self.secret)
            self.assertEqual(self.client.calls, [])

    def test_history_tampering_and_missing_record_are_detected(self):
        self.bootstrap()
        self.append()
        key = scope_id(LEFT, RIGHT)
        self.client.records[key][0]["observed_link_count"] = 99
        with self.assertRaises(RevisionLedgerError):
            verify_revision_chain(self.client, LEFT, RIGHT)
        del self.client.records[key][:]
        with self.assertRaises(RevisionLedgerError):
            verify_revision_chain(self.client, LEFT, RIGHT)

    def test_head_mismatched_scope_fails_closed(self):
        self.bootstrap()
        key = scope_id(LEFT, RIGHT)
        self.client.heads[key]["target_work_id"] = LEFT
        with self.assertRaises(RevisionLedgerError):
            head_for(self.client, LEFT, RIGHT)

    def test_empty_bootstrap_chain_has_valid_zero_head(self):
        self.bootstrap()
        report = verify_revision_chain(self.client, LEFT, RIGHT)
        self.assertEqual(report["verified_record_count"], 0)
        self.assertEqual(report["chain_sha256"], ZERO_CHAIN)

    def test_finite_chain_rejects_append_past_max_revisions(self):
        self.bootstrap()
        previous = ZERO_CHAIN
        for i in range(MAX_REVISIONS):
            nxt = self.append(seq=i, previous=previous, now=1234567891+i)
            previous = nxt["chain_sha256"]
        self.assertEqual(verify_revision_chain(self.client, LEFT, RIGHT)
                         ["verified_record_count"], MAX_REVISIONS)
        with self.assertRaises(RevisionLedgerError):
            self.append(seq=MAX_REVISIONS, previous=previous)

    def test_cli_plan_is_read_only_and_write_needs_explicit_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"signed.json"
            key=Path(tmp)/"token"
            bootstrap_token(key)
            token=load_token(key)
            signed=export_work_link_audit(
                AuditStore(), source_work_id=LEFT,
                target_work_id=RIGHT, secret=token, now=1234567890,
            )
            p.write_text(json.dumps(signed), encoding="utf-8")
            cli=["--input",str(p),"--token-path",str(key)]
            with patch.dict(os.environ,{
                    "CI":"false","DVIROS_AUDIT_REVISION_WRITE_ENABLE":"0"}):
                self.assertEqual(cli_main(["plan",*cli]),0)
                self.assertEqual(cli_main(["bootstrap",*cli]),2)
                self.assertEqual(cli_main([
                    "bootstrap",*cli,"--ack-metadata-write"]),2)
                self.assertEqual(cli_main([
                    "bootstrap",*cli,"--ack-metadata-write",
                    "--ack-disposable-fixture"]),2)
            sym=Path(tmp)/"link.json"
            sym.symlink_to(p)
            self.assertEqual(cli_main(["plan","--input",str(sym),
                                       "--token-path",str(key)]),1)

    def test_cli_ci_fixture_mode_can_bootstrap_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"signed.json"
            key=Path(tmp)/"token"
            bootstrap_token(key)
            signed=export_work_link_audit(
                AuditStore(),source_work_id=LEFT,target_work_id=RIGHT,
                secret=load_token(key),now=1234567890,
            )
            p.write_text(json.dumps(signed), encoding="utf-8")
            args=["--input",str(p),"--token-path",str(key)]
            with patch.dict(os.environ,{"CI":"true"}), \
                 patch("scripts.audit_revision_ledger_v0912.LocalQueryClient",
                       return_value=self.client):
                self.assertEqual(cli_main([
                    "bootstrap",*args,"--ack-metadata-write",
                    "--ack-disposable-fixture"]),0)
                self.assertEqual(cli_main([
                    "append",*args,"--ack-metadata-write",
                    "--ack-disposable-fixture",
                    "--expected-sequence","0",
                    "--expected-chain",ZERO_CHAIN]),0)
                self.assertEqual(cli_main(["verify",*args]),0)


if __name__=="__main__":
    unittest.main()
