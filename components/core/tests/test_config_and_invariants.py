# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import patch

from r740_core import autorouting
from r740_core.config import ConfigError, CoreSettings, env_bool, env_int, env_loopback_url


ROOT = Path(__file__).resolve().parents[1]


class TypedConfigTests(unittest.TestCase):
    def test_invalid_values_fail_closed(self) -> None:
        with patch.dict(os.environ, {"TEST_URL": "https://example.com:443"}, clear=False):
            with self.assertRaises(ConfigError):
                env_loopback_url("TEST_URL", "http://127.0.0.1:1")
        with patch.dict(os.environ, {"TEST_BOOL": "maybe"}, clear=False):
            with self.assertRaises(ConfigError):
                env_bool("TEST_BOOL")
        with patch.dict(os.environ, {"TEST_INT": "999"}, clear=False):
            with self.assertRaises(ConfigError):
                env_int("TEST_INT", 1, minimum=1, maximum=8)

    def test_defaults_ship_no_credentials_or_private_lan(self) -> None:
        names = [
            "AI_ORCHESTRATOR_KEY", "AI_BACKEND_KEY", "AI_PORTAL_CORE_KEY",
            "AI_GATEWAY_ALLOWED_CLIENTS", "AI_GATEWAY_TRUSTED_HOSTS",
        ]
        with patch.dict(os.environ, {name: "" for name in names}, clear=False):
            for name in names:
                os.environ.pop(name, None)
            settings = CoreSettings.from_env()
        self.assertEqual(settings.internal_key, "")
        self.assertEqual(settings.backend_key, "")
        self.assertEqual(settings.portal_key, "")
        self.assertEqual(settings.allowed_clients, frozenset({"127.0.0.1", "::1"}))


class RoutingInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = json.loads((ROOT / "config" / "model-registry.example.json").read_text(encoding="utf-8"))

    def test_preview_requires_single_job_and_one_heavy(self) -> None:
        autorouting._routing_config(self.registry, require_execution=False)
        for field in ("single_inference_job", "one_heavy_model_resident"):
            broken = copy.deepcopy(self.registry)
            broken["policy"][field] = False
            with self.assertRaises(autorouting.RoutingError):
                autorouting._routing_config(broken, require_execution=False)

    def test_remote_routes_are_rejected(self) -> None:
        broken = copy.deepcopy(self.registry)
        broken["routing"]["allow_remote"] = True
        with self.assertRaises(autorouting.RoutingError):
            autorouting._routing_config(broken, require_execution=False)

    def test_gpu_lock_is_exclusive(self) -> None:
        if autorouting.fcntl is None:
            self.skipTest("POSIX flock unavailable")
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "workflow.lock"
            with autorouting.exclusive_slot(lock):
                with self.assertRaises(autorouting.ExecutionError):
                    with autorouting.exclusive_slot(lock):
                        pass


class SourceSafetyTests(unittest.TestCase):
    def test_no_live_lan_or_legacy_ai_paths(self) -> None:
        source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src" / "r740_core").glob("*.py"))
        self.assertNotIn("192" + ".168.", source)
        self.assertNotIn('Path("/ai/', source)
        self.assertNotIn('"/run/ai-', source)

    def test_spdx_on_every_python_source(self) -> None:
        for path in (ROOT / "src" / "r740_core").glob("*.py"):
            self.assertIn("SPDX-License-Identifier: LGPL-3.0-or-later", path.read_text(encoding="utf-8")[:200])

    def test_graphics_uses_bounded_fifo(self) -> None:
        source = (ROOT / "src" / "r740_core" / "graphics_manager.py").read_text(encoding="utf-8")
        self.assertIn("queue.Queue(maxsize=MAX_QUEUE)", source)
        fifo: queue.Queue[str] = queue.Queue(maxsize=2)
        fifo.put_nowait("first")
        fifo.put_nowait("second")
        self.assertEqual([fifo.get_nowait(), fifo.get_nowait()], ["first", "second"])


if __name__ == "__main__":
    unittest.main()
