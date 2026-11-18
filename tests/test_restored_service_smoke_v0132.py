"""v0.13.2 isolated restored-service smoke tests (synthetic bytes + mocked Docker).

No real Neo4j dump or database is loaded in these tests. Success in CI
certifies control flow and refusal/cleanup, NOT actual recoverability.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.restored_service_smoke_v0132 import main as smoke_cli
from services.research_api.offline_backup_v0130 import (
    create_offline_dump_manifest, create_private_manifest_file,
)
from services.research_api.restored_service_smoke_v0132 import (
    _minimums, _scalar, _query, _start_isolated_service,
    execute_restored_service_smoke, plan_restored_service_smoke,
)


class RestoredServiceSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        if os.name != "nt":
            self.root.chmod(0o700)
        self.archive = self.root / "neo4j-fixture.dump"
        self.archive.write_bytes(b"TEST_BLOB_NOT_A_REAL_NEO4J_DUMP" * 5)
        if os.name != "nt":
            self.archive.chmod(0o600)
        self.manifest = self.root / "private-manifest.json"
        create_private_manifest_file(
            self.manifest,
            create_offline_dump_manifest(
                self.archive, operator_stopped_database=True,
            ),
        )
        self.output = self.root / "smoke.restore-drill.json"
        self.minima = {
            "nodes": 5, "relationships": 2, "passages": 3,
            "source_records": 0, "constraints": 1,
        }

    def test_preflight_has_no_docker_or_graph_reads(self):
        with patch(
            "services.research_api.restored_service_smoke_v0132._docker"
        ) as docker:
            data = plan_restored_service_smoke(
                self.archive, self.manifest, minimum_counts=self.minima,
            )
        docker.assert_not_called()
        self.assertTrue(data["archive_integrity_verified"])
        self.assertFalse(data["docker_operations_performed"])
        self.assertFalse(data["restored_service_authenticated"])
        self.assertFalse(data["rpo_rto_demonstrated"])
        self.assertEqual(data["operator_minimum_counts"]["nodes"], 5)
        self.assertEqual(len(data["fixed_read_queries"]), 6)

    def test_safe_fixed_read_query_and_password_only_environment(self):
        captured = []
        def docker(args, **kwargs):
            captured.append((args, kwargs))
            return subprocess.CompletedProcess(
                args, 0, stdout="result\n7\n", stderr="",
            )
        with patch(
            "services.research_api.restored_service_smoke_v0132._docker",
            side_effect=docker,
        ):
            _start_isolated_service(
                "dviros-neo-restore-drill-" + "a" * 24,
                "dviros-neo-restored-smoke-" + "a" * 24,
                "private-test-password",
            )
            count = _query(
                "dviros-neo-restored-smoke-" + "a" * 24,
                "private-test-password",
                "MATCH (n) RETURN count(n) AS result",
            )
        self.assertEqual(count, 7)
        start_args, start_kwargs = captured[0]
        self.assertIn("--network", start_args)
        self.assertEqual(start_args[start_args.index("--network") + 1], "none")
        self.assertNotIn("--publish", start_args)
        self.assertNotIn("-p", start_args)
        self.assertIn("NEO4J_AUTH", start_args)
        self.assertNotIn("private-test-password", repr(start_args))
        self.assertEqual(
            start_kwargs["env"]["NEO4J_AUTH"], "neo4j/private-test-password",
        )
        query_args, query_kwargs = captured[1]
        self.assertEqual(
            query_kwargs["env"]["NEO4J_PASSWORD"], "private-test-password",
        )
        self.assertNotIn("private-test-password", repr(query_args))
        self.assertIn("--access-mode", query_args)
        self.assertEqual(
            query_args[query_args.index("--access-mode") + 1], "read",
        )
        with self.assertRaises(ValueError):
            _query("safe", "private-test-password", "DELETE n")

    def test_scalar_and_minimums_fail_closed(self):
        self.assertEqual(_scalar("result\n100\n"), 100)
        for invalid in ("", "result\nhello\n", "1\n2", "-5", "1.2",
                        "result\n1\n2", "result\n18446744073709551616"):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                _scalar(invalid)
        with self.assertRaises(ValueError):
            _minimums({**self.minima, "nodes": True})
        with self.assertRaises(ValueError):
            _minimums({**self.minima, "cypher": 1})
        with self.assertRaises(ValueError):
            _minimums({key: 0 for key in self.minima})

    @staticmethod
    def fake_docker(args, **kwargs):
        if args[:2] in (["volume", "inspect"], ["container", "inspect"]):
            label = "volume" if args[0] == "volume" else "container"
            return subprocess.CompletedProcess(
                args, 1, stdout="", stderr="No such " + label,
            )
        if args[:2] == ["volume", "create"]:
            return subprocess.CompletedProcess(
                args, 0, stdout=args[-1] + "\n", stderr="",
            )
        if args[:2] == ["run", "--detach"]:
            return subprocess.CompletedProcess(
                args, 0, stdout="test-container-id", stderr="",
            )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def test_success_uses_only_isolated_resources_and_private_report(self):
        commands = []
        def docker(args, **kwargs):
            commands.append(args)
            return self.fake_docker(args, **kwargs)
        counts = {
            "nodes": 10, "relationships": 5, "passages": 7,
            "source_records": 2, "constraints": 3,
        }
        with (
            patch("services.research_api.restored_service_smoke_v0132._docker",
                  side_effect=docker),
            patch("services.research_api.restored_service_smoke_v0132._run_docker",
                  side_effect=docker),
            patch("services.research_api.restored_service_smoke_v0132._load_dump") as load,
            patch("services.research_api.restored_service_smoke_v0132._check_restored_store") as check,
            patch("services.research_api.restored_service_smoke_v0132._wait_until_ready"),
            patch("services.research_api.restored_service_smoke_v0132._query",
                  side_effect=lambda container, password, cypher:
                  next(counts[name] for name, query in
                       __import__("services.research_api.restored_service_smoke_v0132",
                                  fromlist=["QUERIES"]).QUERIES if query == cypher)),
        ):
            status = execute_restored_service_smoke(
                self.archive, self.manifest, self.output,
                minimum_counts=self.minima, acknowledged=True,
            )
        self.assertTrue(status["authenticated_restored_read_smoke_passed"])
        self.assertTrue(status["isolated_resources_removed"])
        self.assertFalse(status["rpo_rto_demonstrated"])
        self.assertEqual(status["observed_counts"], counts)
        self.assertEqual(
            [c[:2] for c in commands if c[:2] in
             (["volume", "inspect"], ["container", "inspect"],
              ["volume", "create"], ["container", "rm"],
              ["volume", "rm"])],
            [
                ["volume", "inspect"], ["container", "inspect"],
                ["volume", "create"], ["container", "rm"],
                ["volume", "rm"],
            ],
        )
        load.assert_called_once()
        check.assert_called_once()
        self.assertTrue(self.output.exists())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        receipt = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertTrue(receipt["report"]["restored_service_authenticated"])
        self.assertFalse(receipt["report_digitally_signed"])
        self.assertFalse(receipt["report"]["verified_against_trusted_live_baseline"])

    def test_threshold_violation_still_cleans_and_refuses_success(self):
        commands = []
        def docker(args, **kwargs):
            commands.append(args)
            return self.fake_docker(args, **kwargs)
        with (
            patch("services.research_api.restored_service_smoke_v0132._docker",
                  side_effect=docker),
            patch("services.research_api.restored_service_smoke_v0132._run_docker",
                  side_effect=docker),
            patch("services.research_api.restored_service_smoke_v0132._load_dump"),
            patch("services.research_api.restored_service_smoke_v0132._check_restored_store"),
            patch("services.research_api.restored_service_smoke_v0132._wait_until_ready"),
            patch("services.research_api.restored_service_smoke_v0132._query",
                  return_value=0),
        ):
            with self.assertRaises(RuntimeError):
                execute_restored_service_smoke(
                    self.archive, self.manifest, self.output,
                    minimum_counts=self.minima, acknowledged=True,
                )
        self.assertFalse(self.output.exists())
        self.assertIn(["volume", "rm"], [c[:2] for c in commands])
        self.assertIn(["container", "rm"], [c[:2] for c in commands])

    def test_wrong_image_or_modified_dump_never_reaches_docker(self):
        self.archive.write_bytes(b"changed-fixture-dump")
        with patch(
            "services.research_api.restored_service_smoke_v0132._docker"
        ) as docker:
            with self.assertRaises(ValueError):
                execute_restored_service_smoke(
                    self.archive, self.manifest, self.output,
                    minimum_counts=self.minima, acknowledged=True,
                )
        docker.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_cli_plan_and_explicit_execute_acknowledgment(self):
        self.assertEqual(smoke_cli([
            "plan", "--archive", str(self.archive),
            "--manifest", str(self.manifest),
        ]), 0)
        with self.assertRaises(SystemExit):
            smoke_cli([
                "execute", "--archive", str(self.archive),
                "--manifest", str(self.manifest),
                "--output", str(self.output),
            ])


if __name__ == "__main__":
    unittest.main()
