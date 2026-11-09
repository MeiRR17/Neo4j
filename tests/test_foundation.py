"""Small dependency-free tests for the secure local foundation."""

import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bootstrap  # noqa: E402
import smoke  # noqa: E402


class SecretTests(unittest.TestCase):
    def test_create_secret_without_echo_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets" / "neo4j_auth.txt"
            self.assertTrue(bootstrap.create_secret(path))
            user, password = bootstrap.load_auth(path)
            self.assertEqual(user, "neo4j")
            self.assertGreaterEqual(len(password), 40)
            self.assertFalse(bootstrap.create_secret(path))
            self.assertEqual(bootstrap.load_auth(path)[1], password)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_existing_bad_secret_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "neo4j_auth.txt"
            path.write_text("neo4j/short\n", encoding="utf-8")
            if os.name != "nt":
                path.chmod(0o600)
            with self.assertRaises(ValueError):
                bootstrap.create_secret(path)

    @unittest.skipIf(os.name == "nt", "POSIX permission check")
    def test_group_access_to_credentials_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "neo4j_auth.txt"
            bootstrap.create_secret(path)
            path.chmod(0o640)
            with self.assertRaises(ValueError):
                bootstrap.load_auth(path)


class SmokeTests(unittest.TestCase):
    def test_reject_nonlocal_or_tricky_urls(self):
        bad = [
            "https://127.0.0.1:7474", "http://example.com:7474",
            "http://127.0.0.1:7475", "http://localhost@evil.test:7474",
            "http://127.0.0.1:7474/other", "http://127.0.0.1:7474/?x=1",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                smoke.query_url(value)
        self.assertEqual(
            smoke.query_url("http://localhost:7474"),
            "http://127.0.0.1:7474/db/neo4j/query/v2",
        )

    def test_authenticated_read_and_unauthorized_gate(self):
        with patch.object(smoke, "load_auth", return_value=("neo4j", "fake-not-real-password")), patch.object(
            smoke, "post_query", side_effect=[
                (401, {}),
                (202, {"data": {"fields": ["value"], "values": [[1]]}}),
            ]
        ) as post:
            self.assertTrue(smoke.run("http://127.0.0.1:7474", Path("unused"), 0))
            self.assertEqual(post.call_count, 2)

    def test_reject_disabled_auth(self):
        with patch.object(smoke, "load_auth", return_value=("neo4j", "fake-not-real-password")), patch.object(
            smoke, "post_query", return_value=(202, {}),
        ):
            with self.assertRaisesRegex(RuntimeError, "Unauthenticated"):
                smoke.run("http://127.0.0.1:7474", Path("unused"), 0)


class ComposePolicyTests(unittest.TestCase):
    def test_local_compose_enforces_security_shape(self):
        content = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("image: neo4j:2026.10.1", content)
        self.assertIn("127.0.0.1:7474:7474", content)
        self.assertIn("127.0.0.1:7687:7687", content)
        self.assertIn("NEO4J_AUTH_FILE:", content)
        self.assertIn("file: ./secrets/neo4j_auth.txt", content)
        self.assertIn("neo4j_data:/data", content)
        self.assertNotIn("neo4j:latest", content)
        self.assertNotIn("NEO4J_PLUGINS", content)
        self.assertNotIn("procedures_unrestricted", content)
        self.assertNotIn("NEO4J_AUTH=none", content)


if __name__ == "__main__":
    unittest.main()
