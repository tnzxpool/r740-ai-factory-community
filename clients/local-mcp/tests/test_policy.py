import json
import tempfile
import unittest
from pathlib import Path

from r740_local_mcp.policy import ConnectorConfig, PolicyError, require_non_guest, resolve_allowed_path


class PolicyTests(unittest.TestCase):
    def test_guest_is_hard_denied(self):
        for subject in ("guest", "GUEST", ""):
            with self.subTest(subject=subject), self.assertRaises(PolicyError):
                require_non_guest(subject)

    def test_path_stays_in_selected_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "allowed"
            root.mkdir()
            good = root / "note.txt"
            good.write_text("ok", encoding="utf-8")
            outside = Path(tmp) / "outside.txt"
            outside.write_text("no", encoding="utf-8")
            self.assertEqual(resolve_allowed_path((root.resolve(),), str(good.resolve()), must_file=True), good.resolve())
            with self.assertRaises(PolicyError):
                resolve_allowed_path((root.resolve(),), str(outside.resolve()), must_file=True)

    def test_only_exact_outbound_endpoint_and_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = {
                "endpoint": "wss://ai-factory.example.org:8448/api/local-mcp/connect",
                "tls_trust": "system",
                "consent": "every_call", "result_limit_bytes": 65536,
                "timeout_seconds": 20, "allowed_roots": [],
                "allowed_tools": {"local_files_list": "read", "local_files_read_text": "read"},
            }
            path = base / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(ConnectorConfig.load(path).endpoint, raw["endpoint"])
            for invalid in (
                "ws://127.0.0.1:1234",
                "wss://127.0.0.1:8448/api/local-mcp/connect",
                "wss://user:pass@example.org:8448/api/local-mcp/connect",
                "wss://example.org:9443/api/local-mcp/connect",
                "wss://example.org:8448/wrong",
            ):
                raw["endpoint"] = invalid
                path.write_text(json.dumps(raw), encoding="utf-8")
                with self.subTest(endpoint=invalid), self.assertRaises(PolicyError):
                    ConnectorConfig.load(path)

    def test_public_system_trust_is_required_and_pin_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            raw = {
                "endpoint": "wss://ai-factory.example.org:8448/api/local-mcp/connect",
                "tls_trust": "system", "consent": "every_call",
                "result_limit_bytes": 65536, "timeout_seconds": 20,
                "allowed_roots": [],
                "allowed_tools": {"local_files_list": "read", "local_files_read_text": "read"},
            }
            path.write_text(json.dumps(raw), encoding="utf-8")
            config = ConnectorConfig.load(path)
            self.assertIsNone(config.certificate_pin)
            raw["ca_file"] = "old-private-ca.crt"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(PolicyError):
                ConnectorConfig.load(path)
            raw.pop("ca_file")
            raw["server_certificate_sha256"] = "not-a-pin"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(PolicyError):
                ConnectorConfig.load(path)


if __name__ == "__main__":
    unittest.main()
