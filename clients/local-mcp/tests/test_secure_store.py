import os
import tempfile
import unittest
from pathlib import Path

from r740_local_mcp.secure_store import DeviceStore


@unittest.skipUnless(os.name == "nt", "DPAPI richiede Windows")
class SecureStoreTests(unittest.TestCase):
    def test_dpapi_roundtrip_is_not_plaintext(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "device.dpapi"
            store = DeviceStore(path)
            store.save({"device_token": "secret-test-token"})
            self.assertEqual(store.load()["device_token"], "secret-test-token")
            self.assertNotIn(b"secret-test-token", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
