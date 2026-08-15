import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from r740_local_mcp.audit import MetadataAudit
from r740_local_mcp.connector import OutboundConnector
from r740_local_mcp.policy import ConnectorConfig, PolicyError
from r740_local_mcp.protocol import new_device_key


class MemoryStore:
    def __init__(self, record): self.record = record
    def load(self): return dict(self.record)
    def save(self, record): self.record = dict(record)


class FakeWebSocket:
    subprotocol = "r740-local-mcp-v1"
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = False
    async def recv(self): return json.dumps(self.incoming.pop(0))
    async def send(self, message): self.sent.append(json.loads(message))
    async def close(self): self.closed = True
    def __aiter__(self): return self
    async def __anext__(self):
        if not self.incoming: raise StopAsyncIteration
        return json.dumps(self.incoming.pop(0))


class TestConnector(OutboundConnector):
    def __init__(self, *args, websocket, **kwargs):
        super().__init__(*args, **kwargs)
        self.websocket = websocket
    async def _open(self): return self.websocket


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_read_call_has_consent_and_no_secret_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            note = root / "note.txt"
            note.write_text("dato locale", encoding="utf-8")
            private, public = new_device_key()
            secret = "server-only-device-token-1234567890"
            record = {"device_id": "dev-1", "subject": "alice", "private_key": private, "public_key": public, "device_token": secret}
            config = ConnectorConfig("wss://ai-factory.example.org:8448/api/local-mcp/connect", None, "every_call", 65536, 20, (root,), {"local_files_list": "read", "local_files_read_text": "read"})
            websocket = FakeWebSocket([
                {"type": "auth.challenge", "nonce": "nonce-long-enough-123"},
                {"type": "auth.accepted", "subject": "alice"},
                {"type": "tool.call", "call_id": "call-12345", "subject": "alice", "tool": "local_files_read_text", "class": "read", "arguments": {"path": str(note)}},
            ])
            audit_path = root / "audit.jsonl"
            connector = TestConnector(config, MemoryStore(record), MetadataAudit(audit_path), websocket=websocket)
            with patch("r740_local_mcp.connector.ask_local_consent", return_value=True):
                await connector.connect_once()
            result = next(item for item in websocket.sent if item.get("type") == "tool.result")
            self.assertEqual(websocket.sent[0], {"type": "connect.hello", "protocol": "r740-local-mcp-v1", "mode": "auth", "device_id": "dev-1"})
            self.assertTrue(result["untrusted_tool_content"])
            self.assertIn("dato locale", json.dumps(result))
            exposed = json.dumps([item for item in websocket.sent if item.get("type") != "auth.response"]) + audit_path.read_text(encoding="utf-8")
            self.assertNotIn(secret, exposed)

    async def test_pair_protocol_starts_with_explicit_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = MemoryStore({})
            config = ConnectorConfig("wss://ai-factory.example.org:8448/api/local-mcp/connect", None, "every_call", 65536, 20, (), {"local_files_list": "read", "local_files_read_text": "read"})
            websocket = FakeWebSocket([
                {"type": "pair.ready"},
                {"type": "pair.accepted", "subject": "alice", "device_token": "x" * 48},
            ])
            connector = TestConnector(config, store, MetadataAudit(root / "audit.jsonl"), websocket=websocket)
            result = await connector.pair("ABCD-EFGH-JKLM-NPQR", "PC Alice")
            self.assertEqual(result["subject"], "alice")
            self.assertEqual(websocket.sent[0], {"type": "connect.hello", "protocol": "r740-local-mcp-v1", "mode": "pair"})
            self.assertEqual(websocket.sent[1]["type"], "pair.start")

    async def test_guest_record_is_denied_before_connection(self):
        private, public = new_device_key()
        config = ConnectorConfig("wss://ai-factory.example.org:8448/api/local-mcp/connect", None, "every_call", 65536, 20, (), {"local_files_list": "read", "local_files_read_text": "read"})
        connector = OutboundConnector(config, MemoryStore({"subject": "guest", "private_key": private, "public_key": public}), MetadataAudit(Path("unused")))
        with self.assertRaises(PolicyError):
            await connector.connect_once()


if __name__ == "__main__":
    unittest.main()
