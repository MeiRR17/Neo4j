"""Migration parser, manifest and checksum drift checks, without a database."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts.migrate import (
    load_migrations, migrate, parse_statements,
)


class MemoryClient:
    def __init__(self):
        self.markers = {}
        self.schema_calls = []

    def query(self, statement, params=None):
        params = params or {}
        if statement.startswith("MATCH (m:SchemaMigration"):
            return [[self.markers[params["id"]]]] if params["id"] in self.markers else []
        if statement.startswith("MERGE (m:SchemaMigration"):
            self.markers.setdefault(params["id"], params["checksum"])
            return [[self.markers[params["id"]]]]
        self.schema_calls.append(statement)
        return []


class MigrationTests(unittest.TestCase):
    def test_manifest_has_four_ordered_migrations(self):
        items = load_migrations()
        self.assertEqual([m.id for m in items], ["001", "002", "003", "004"])
        self.assertEqual([len(m.statements) for m in items], [10, 9, 10, 4])
        self.assertTrue(all(len(m.checksum) == 64 for m in items))

    def test_idempotency_and_checksum_drift_fail_closed(self):
        items = load_migrations()
        client = MemoryClient()
        self.assertFalse(migrate(items, client, "check"))
        self.assertTrue(migrate(items, client, "apply"))
        n = len(client.schema_calls)
        self.assertEqual(n, 33)
        self.assertTrue(migrate(items, client, "apply"))
        self.assertEqual(len(client.schema_calls), n)
        self.assertTrue(migrate(items, client, "check"))
        modified = [replace(items[0], checksum="0" * 64), *items[1:]]
        with self.assertRaisesRegex(RuntimeError, "changed"):
            migrate(modified, client, "apply")

    def test_out_of_order_marker_is_rejected(self):
        items = load_migrations()
        client = MemoryClient()
        client.markers["002"] = items[1].checksum
        with self.assertRaisesRegex(RuntimeError, "Out-of-order"):
            migrate(items, client, "apply")

    def test_unsupported_ddl_is_rejected(self):
        for source in [
            "MATCH (n) DETACH DELETE n;",
            "CREATE (n:Work {id:'not-safe'});",
            "CREATE INDEX i FOR (n:Work) ON (n.id);",  # no IF NOT EXISTS
            "CREATE CONSTRAINT i IF NOT EXISTS FOR (n:Work) REQUIRE n.id IS UNIQUE",
        ]:
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_statements(source)
        self.assertEqual(len(parse_statements(
            "// comment\nCREATE INDEX fixture IF NOT EXISTS FOR (n:Work) ON (n.title);"
        )), 1)


if __name__ == "__main__":
    unittest.main()
