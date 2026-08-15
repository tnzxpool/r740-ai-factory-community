import tempfile
import unittest
from pathlib import Path

from r740_local_mcp.builtin_files import BuiltinFilesMcp
from r740_local_mcp.policy import PolicyError


class ToolTests(unittest.TestCase):
    def test_read_only_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            note = root / "note.txt"
            note.write_text("ciao", encoding="utf-8")
            tools = BuiltinFilesMcp((root,), 65536)
            listed = tools.call("local_files_list", {"path": str(root)})
            read = tools.call("local_files_read_text", {"path": str(note)})
            self.assertIn("note.txt", listed["content"][0]["text"])
            self.assertEqual(read["content"][0]["text"], "ciao")
            rpc = tools.handle_jsonrpc({"jsonrpc": "2.0", "id": 7, "method": "tools/list", "params": {}})
            self.assertEqual(rpc["id"], 7)
            self.assertEqual(len(rpc["result"]["tools"]), 2)
            with self.assertRaises(PolicyError):
                tools.call("shell", {"path": str(note)})

    def test_binary_and_oversize_are_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            binary = root / "bad.bin"
            binary.write_bytes(b"a\x00b")
            large = root / "large.txt"
            large.write_bytes(b"x" * 129)
            tools = BuiltinFilesMcp((root,), 128)
            for path in (binary, large):
                with self.subTest(path=path), self.assertRaises(PolicyError):
                    tools.call("local_files_read_text", {"path": str(path)})


if __name__ == "__main__":
    unittest.main()
