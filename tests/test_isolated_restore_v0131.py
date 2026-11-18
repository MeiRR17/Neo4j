"""v0.13.1 isolated restore drill preflight and fail-closed cleanup tests.

Tests use synthetic dump bytes and mocked Docker. They do NOT demonstrate
that Neo4j can load a real archive or that a restored DB is readable online.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.isolated_restore_drill_v0131 import main as drill_cli
from services.research_api.offline_backup_v0130 import (
    create_offline_dump_manifest, create_private_manifest_file,
)
from services.research_api.isolated_restore_v0131 import (
    ADMIN_IMAGE, VOLUME_PREFIX, _volume_args, execute_isolated_restore_drill,
    plan_isolated_restore_drill,
)


class IsolatedRestoreDrillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        if os.name != "nt":
            self.root.chmod(0o700)
        self.archive = self.root / "neo4j.dump"
        self.archive.write_bytes(b"synthetic-NOT-a-neo4j-archive" * 10)
        if os.name != "nt":
            self.archive.chmod(0o600)
        self.manifest = self.root / "manifest.json"
        create_private_manifest_file(
            self.manifest,
            create_offline_dump_manifest(
                self.archive, operator_stopped_database=True,
            ),
        )
        self.output = self.root / "drill.restore-drill.json"

    def test_preflight_is_read_only_and_does_not_call_docker(self):
        with patch(
            "services.research_api.isolated_restore_v0131._run_docker"
        ) as docker:
            plan = plan_isolated_restore_drill(self.archive, self.manifest)
        docker.assert_not_called()
        self.assertEqual(plan["schema_version"], "0.13.1")
        self.assertEqual(plan["offline_admin_image"], ADMIN_IMAGE)
        self.assertTrue(plan["archive_integrity_verified"])
        self.assertFalse(plan["execution_enabled"])
        self.assertFalse(plan["host_live_volume_mounted"])
        self.assertFalse(plan["isolated_load_and_consistency_checked"])
        self.assertFalse(plan["rpo_rto_demonstrated"])

    def test_generated_run_args_have_no_ports_network_or_live_mount(self):
        args = _volume_args(VOLUME_PREFIX + "a" * 24)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertEqual(args[args.index("--pull") + 1], "never")
        self.assertEqual(args[-1], ADMIN_IMAGE)
        self.assertNotIn("-p", args)
        self.assertNotIn("--publish", args)
        self.assertIn("volume-nocopy", args[args.index("--mount") + 1])
        for unsafe in ("neo4j_data", "type=bind", "docker.sock", "compose"):
            self.assertNotIn(unsafe, " ".join(args))
        with self.assertRaises(ValueError):
            _volume_args("neo4j_data")

    def _fake_docker(self, calls):
        def invoke(args, **kwargs):
            calls.append(list(args))
            if args[:2] == ["volume", "inspect"]:
                return subprocess.CompletedProcess(args, 1, stdout="")
            if args[:2] == ["volume", "create"]:
                return subprocess.CompletedProcess(
                    args, 0, stdout=args[-1] + "\n",
                )
            return subprocess.CompletedProcess(args, 0, stdout="")
        return invoke

    def test_execute_creates_checks_and_removes_private_volume(self):
        commands = []
        with (
            patch("services.research_api.isolated_restore_v0131._run_docker",
                  side_effect=self._fake_docker(commands)),
            patch("services.research_api.isolated_restore_v0131._load_dump") as load,
            patch("services.research_api.isolated_restore_v0131._check_restored_store") as check,
        ):
            result = execute_isolated_restore_drill(
                self.archive, self.manifest, self.output,
                acknowledged=True,
            )
        self.assertTrue(result["offline_load_and_consistency_passed"])
        self.assertTrue(result["isolated_volume_removed"])
        self.assertFalse(result["end_to_end_restore_drill_passed"])
        self.assertFalse(result["rpo_rto_demonstrated"])
        self.assertTrue(self.output.exists())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        record = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(record["report"]["research_release_status"], "HOLD")
        self.assertFalse(record["report_digitally_signed"])
        self.assertEqual(len(record["report_sha256"]), 64)
        self.assertEqual([cmd[:2] for cmd in commands], [
            ["volume", "inspect"], ["volume", "create"], ["volume", "rm"],
        ])
        volume = commands[1][-1]
        self.assertTrue(volume.startswith(VOLUME_PREFIX))
        self.assertEqual(commands[-1][-1], volume)
        load.assert_called_once_with(self.archive, volume)
        check.assert_called_once_with(volume)

    def test_load_failure_removes_volume_and_refuses_report(self):
        commands = []
        with (
            patch("services.research_api.isolated_restore_v0131._run_docker",
                  side_effect=self._fake_docker(commands)),
            patch("services.research_api.isolated_restore_v0131._load_dump",
                  side_effect=RuntimeError("fake restore failure")),
        ):
            with self.assertRaises(RuntimeError):
                execute_isolated_restore_drill(
                    self.archive, self.manifest, self.output,
                    acknowledged=True,
                )
        self.assertEqual(commands[-1][:2], ["volume", "rm"])
        self.assertFalse(self.output.exists())

    def test_mutated_archive_missing_ack_and_overwrite_all_rejected(self):
        with patch(
            "services.research_api.isolated_restore_v0131._run_docker"
        ) as docker:
            with self.assertRaises(ValueError):
                execute_isolated_restore_drill(
                    self.archive, self.manifest, self.output,
                    acknowledged=False,
                )
            self.archive.write_bytes(b"mutated-archive")
            with self.assertRaises(ValueError):
                plan_isolated_restore_drill(self.archive, self.manifest)
            with self.assertRaises(ValueError):
                execute_isolated_restore_drill(
                    self.archive, self.manifest, self.output,
                    acknowledged=True,
                )
        docker.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_plan_cli_and_disabled_execute_cli(self):
        self.assertEqual(drill_cli([
            "plan", "--archive", str(self.archive),
            "--manifest", str(self.manifest),
        ]), 0)
        # CLI must not be able to execute without a separate flag.
        with self.assertRaises(SystemExit):
            drill_cli([
                "execute", "--archive", str(self.archive),
                "--manifest", str(self.manifest),
                "--output", str(self.output),
            ])


if __name__ == "__main__":
    unittest.main()
