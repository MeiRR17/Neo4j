"""v0.13.0 offline Neo4j dump integrity / privacy tests (synthetic bytes).

All fixtures are ordinary bytes, NOT valid Neo4j dumps. These tests certify
hashing and fail-closed handling only; a real isolated restore drill remains
a separate production release gate.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from scripts.offline_backup_v0130 import main as backup_cli
from services.research_api.offline_backup_v0130 import (
    PINNED_IMAGE, create_offline_dump_manifest,
    create_private_manifest_file, read_private_manifest,
    verify_offline_dump_manifest,
)


class OfflineDumpIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        if os.name != "nt":
            self.root.chmod(0o700)
        self.archive = self.root / "neo4j-test.dump"
        self.archive.write_bytes(b"SYNTHETIC_NOT_A_NEO4J_DUMP\n" * 13)
        if os.name != "nt":
            self.archive.chmod(0o600)

    def manifest(self):
        return create_offline_dump_manifest(
            self.archive, operator_stopped_database=True,
        )

    def test_build_verify_preserves_offline_only_honest_flags(self):
        manifest = self.manifest()
        payload = manifest["manifest"]
        self.assertEqual(payload["schema_version"], "0.13.0")
        self.assertEqual(payload["database"], "neo4j")
        self.assertEqual(payload["neo4j_image"], PINNED_IMAGE)
        self.assertEqual(payload["archive_filename"], "neo4j-test.dump")
        self.assertEqual(payload["archive_bytes"], self.archive.stat().st_size)
        self.assertEqual(len(payload["archive_sha256"]), 64)
        self.assertTrue(payload["offline_stop_operator_attested"])
        for field in (
            "database_stop_independently_verified", "dump_format_verified",
            "isolated_restore_drill_passed", "rpo_rto_demonstrated",
            "immutable_graph_snapshot_verified", "source_rights_verified",
        ):
            self.assertFalse(payload[field])
        result = verify_offline_dump_manifest(manifest, self.archive)
        self.assertTrue(result["integrity_sha256_verified"])
        self.assertFalse(result["neo4j_dump_format_verified"])
        self.assertFalse(result["ready_for_production_restore"])
        self.assertEqual(result["research_release_status"], "HOLD")

    def test_byte_change_and_file_truncation_detected(self):
        original = self.manifest()
        self.archive.write_bytes(b"MUTATED_NOT_A_NEO4J_DUMP\n" * 13)
        with self.assertRaises(ValueError):
            verify_offline_dump_manifest(original, self.archive)
        self.archive.write_bytes(b"")
        with self.assertRaises(ValueError):
            verify_offline_dump_manifest(original, self.archive)

    def test_manifest_forged_flags_and_image_mismatch_refused(self):
        valid = self.manifest()
        bads = []
        for key, value in (
            ("isolated_restore_drill_passed", True),
            ("dump_format_verified", True),
            ("database_stop_independently_verified", True),
            ("source_rights_verified", True),
            ("neo4j_image", "neo4j:latest"),
            ("archive_bytes", True),
        ):
            wrong = deepcopy(valid)
            wrong["manifest"][key] = value
            bads.append(wrong)
        for bad in bads:
            with self.assertRaises(ValueError):
                verify_offline_dump_manifest(bad, self.archive)
        with self.assertRaises(ValueError):
            verify_offline_dump_manifest(
                valid, self.archive, expected_image="neo4j:latest",
            )
        with self.assertRaises(ValueError):
            create_offline_dump_manifest(
                self.archive, operator_stopped_database=False,
            )

    def test_filename_symlinks_hardlinks_and_weak_permissions_fail(self):
        original = self.manifest()
        renamed = self.root / "neo4j-moved.dump"
        self.archive.rename(renamed)
        with self.assertRaises(ValueError):
            verify_offline_dump_manifest(original, renamed)
        renamed.rename(self.archive)

        with self.assertRaises(ValueError):
            create_offline_dump_manifest(
                self.root / "file.txt", operator_stopped_database=True,
            )
        if os.name == "nt":
            return
        soft = self.root / "symlink.dump"
        soft.symlink_to(self.archive)
        with self.assertRaises((ValueError, OSError)):
            create_offline_dump_manifest(
                soft, operator_stopped_database=True,
            )
        hard = self.root / "hardlink.dump"
        os.link(self.archive, hard)
        with self.assertRaises(ValueError):
            self.manifest()
        hard.unlink()
        self.archive.chmod(0o644)
        with self.assertRaises(ValueError):
            self.manifest()

    def test_manifest_is_canonical_private_create_once(self):
        value = self.manifest()
        path = self.root / "manifest.json"
        create_private_manifest_file(path, value)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(read_private_manifest(path), value)
        with self.assertRaises(FileExistsError):
            create_private_manifest_file(path, value)
        tampered = self.root / "tampered.json"
        tampered.write_text(
            json.dumps({"manifest": value["manifest"],
                        "manifest_sha256": value["manifest_sha256"],
                        "manifest_sha256": "0" * 64}),
            encoding="utf-8",
        )
        if os.name != "nt":
            tampered.chmod(0o600)
        with self.assertRaises(ValueError):
            read_private_manifest(tampered)
        # An apparently harmless noncanonical JSON reformat must fail too.
        tampered.write_text(json.dumps(value, indent=2), encoding="utf-8")
        with self.assertRaises(ValueError):
            read_private_manifest(tampered)

    def test_cli_build_verify_and_no_database_access(self):
        report = self.root / "private-manifest.json"
        self.assertEqual(backup_cli([
            "manifest", "--archive", str(self.archive),
            "--output", str(report), "--operator-stopped-db",
        ]), 0)
        self.assertEqual(backup_cli([
            "verify", "--archive", str(self.archive),
            "--manifest", str(report), "--expected-image", PINNED_IMAGE,
        ]), 0)
        self.assertEqual(backup_cli([
            "manifest", "--archive", str(self.archive),
            "--output", str(report), "--operator-stopped-db",
        ]), 1)
        self.assertEqual(backup_cli([
            "verify", "--archive", str(self.archive),
            "--manifest", str(report), "--expected-image", "neo4j:latest",
        ]), 1)
        self.assertFalse((self.root / "secrets").exists())


if __name__ == "__main__":
    unittest.main()
