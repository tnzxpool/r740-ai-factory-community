#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Render a disabled model unit only after exact local artifact verification."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "systemd" / "r740-model.service.in"
SAFE_PATH = re.compile(r"/[A-Za-z0-9._+/@=-]+(?:/[A-Za-z0-9._+@=-]+)*")
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def checked_file(raw: str, expected_size: int, expected_hash: str, *, executable: bool = False) -> Path:
    if not SAFE_PATH.fullmatch(raw):
        raise ValueError("artifact paths must be absolute and contain no whitespace")
    path = Path(raw)
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"not a regular non-symlink file: {raw}")
    if path.stat().st_size != expected_size or sha256(path) != expected_hash:
        raise ValueError(f"artifact verification failed: {raw}")
    if executable and not os.access(path, os.X_OK):
        raise ValueError(f"runtime is not executable: {raw}")
    return path


def bounded_int(config: dict[str, object], name: str, low: int, high: int) -> int:
    value = config.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def render(config: dict[str, object]) -> tuple[str, str]:
    required = {
        "schema", "model_id", "unit_slug", "service_user", "port", "runtime",
        "runtime_size", "runtime_sha256", "model", "model_size", "model_sha256",
        "ctx_size", "gpu_layers", "parallel", "jinja", "reasoning",
    }
    if set(config) - (required | {"mmproj", "mmproj_size", "mmproj_sha256", "image_min_tokens", "flash_attn", "fit", "spec_type"}):
        raise ValueError("manifest contains unsupported fields")
    if not required <= set(config) or config["schema"] != 1:
        raise ValueError("manifest is incomplete or has an unsupported schema")
    model_id = str(config["model_id"])
    slug = str(config["unit_slug"])
    user = str(config["service_user"])
    if not SAFE_ID.fullmatch(model_id) or not SAFE_ID.fullmatch(slug):
        raise ValueError("model_id and unit_slug must be safe identifiers")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        raise ValueError("service_user is invalid")
    port = bounded_int(config, "port", 1024, 65535)
    runtime = checked_file(str(config["runtime"]), int(config["runtime_size"]), str(config["runtime_sha256"]), executable=True)
    model = checked_file(str(config["model"]), int(config["model_size"]), str(config["model_sha256"]))
    command = [
        str(runtime), "--model", str(model), "--alias", model_id,
        "--host", "127.0.0.1", "--port", str(port),
        "--ctx-size", str(bounded_int(config, "ctx_size", 512, 32768)),
        "--n-gpu-layers", str(bounded_int(config, "gpu_layers", 0, 999)),
        "--parallel", str(bounded_int(config, "parallel", 1, 4)),
    ]
    if config["jinja"] is True:
        command.append("--jinja")
    elif config["jinja"] is not False:
        raise ValueError("jinja must be boolean")
    reasoning = str(config["reasoning"])
    if reasoning not in {"off", "on"}:
        raise ValueError("reasoning must be off or on")
    command.extend(["--reasoning", reasoning])
    mmproj_path = None
    if "mmproj" in config:
        if not {"mmproj_size", "mmproj_sha256"} <= set(config):
            raise ValueError("mmproj size and hash are required")
        mmproj_path = checked_file(str(config["mmproj"]), int(config["mmproj_size"]), str(config["mmproj_sha256"]))
        command.extend(["--mmproj", str(mmproj_path)])
    if "image_min_tokens" in config:
        command.extend(["--image-min-tokens", str(bounded_int(config, "image_min_tokens", 64, 8192))])
    for name, flag in (("flash_attn", "--flash-attn"), ("fit", "--fit")):
        if name in config:
            value = str(config[name])
            if value not in {"on", "off"}:
                raise ValueError(f"{name} must be on or off")
            command.extend([flag, value])
    if "spec_type" in config:
        if config["spec_type"] != "none":
            raise ValueError("only spec_type none is permitted")
        command.extend(["--spec-type", "none"])
    if any(re.search(r"\s", item) for item in command):
        raise ValueError("rendered arguments must not contain whitespace")

    unit_name = f"r740-model-{slug}.service"
    known_units = {
        "r740-model-qwen36.service", "r740-model-qwen36-heretic.service",
        "r740-model-qwen3.service", "r740-model-qwen3vl.service",
        "r740-model-glm47.service", "r740-model-glm-ocr.service",
    }
    conflicts = " ".join(sorted(known_units - {unit_name}))
    text = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "@MODEL_ID@": model_id,
        "@SERVICE_USER@": user,
        "@EXEC_START@": " ".join(command),
        "@RUNTIME@": str(runtime),
        "@MODEL@": str(model),
        "@MMPROJ_READONLY@": str(mmproj_path) if mmproj_path else str(model),
        "@CONFLICTS@": conflicts,
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    if "@" in text:
        raise ValueError("unit template contains unresolved placeholders")
    return unit_name, text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.manifest.read_text(encoding="utf-8"))
    unit_name, content = render(config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / unit_name
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing unit: {output}")
    output.write_text(content, encoding="utf-8", newline="\n")
    print(f"Rendered {unit_name}; it was not enabled or started.")


if __name__ == "__main__":
    main()
