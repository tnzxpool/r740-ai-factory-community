#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/render-model-unit.py"
spec = importlib.util.spec_from_file_location("r740_model_renderer", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def base() -> dict[str, object]:
    return {
        "schema": 1, "model_id": "qwen3-8b", "unit_slug": "qwen3",
        "service_user": "r740-ai", "port": 41140,
        "runtime": "/opt/runtime/llama-server", "runtime_size": 100,
        "runtime_sha256": "a" * 64,
        "model": "/var/lib/r740/models/qwen.gguf", "model_size": 200,
        "model_sha256": "b" * 64, "ctx_size": 8192, "gpu_layers": 99,
        "parallel": 1, "jinja": True, "reasoning": "off",
        "flash_attn": "off", "fit": "off", "spec_type": "none",
    }


def main() -> None:
    def accepted(path: str, *_: object, **__: object) -> Path:
        return Path(path)

    with patch.object(module, "checked_file", side_effect=accepted):
        name, unit = module.render(base())
        assert name == "r740-model-qwen3.service"
        assert "--host 127.0.0.1 --port 41140" in unit
        assert "--spec-type none" in unit and "--fit off" in unit
        assert name not in unit.split("Conflicts=", 1)[1].splitlines()[0]
        assert "@" not in unit

        bad = base(); bad["host"] = "0.0.0.0"
        try:
            module.render(bad)
        except ValueError as error:
            assert "unsupported fields" in str(error)
        else:
            raise AssertionError("unsupported network override was accepted")

        bad = base(); bad["spec_type"] = "draft"
        try:
            module.render(bad)
        except ValueError as error:
            assert "spec_type" in str(error)
        else:
            raise AssertionError("unsafe speculative mode was accepted")

    print("PASS fail-closed model unit renderer")


if __name__ == "__main__":
    main()
