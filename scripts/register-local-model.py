#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Prepare or install one hash-pinned local llama.cpp model."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER_PATH = ROOT / "scripts" / "render-model-unit.py"
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{1,63}")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def regular(path: Path, *, executable: bool = False) -> Path:
    path = path.resolve(strict=True)
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"FAIL not a regular file: {path}")
    if executable and not os.access(path, os.X_OK):
        raise SystemExit(f"FAIL runtime is not executable: {path}")
    if any(character.isspace() for character in str(path)):
        raise SystemExit("FAIL runtime/model paths may not contain whitespace")
    return path


def atomic_text(path: Path, value: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.stat() if path.exists() else None
    handle, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, mode); os.replace(temporary, path)
        if previous is not None and hasattr(os, "chown"):
            os.chown(path, previous.st_uid, previous.st_gid)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def update_env(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []; found = False
    for line in lines:
        if line.startswith(key + "="):
            output.append(f"{key}={value}"); found = True
        else:
            output.append(line)
    if not found: output.append(f"{key}={value}")
    atomic_text(path, "\n".join(output) + "\n", 0o640)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True, help="existing GGUF under the R740 models directory")
    parser.add_argument("--runtime", type=Path, required=True, help="llama-server executable")
    parser.add_argument("--id", required=True, help="OpenAI model identifier")
    parser.add_argument("--display-name", default="Local GGUF model")
    parser.add_argument("--license", required=True, help="SPDX expression or upstream license label")
    parser.add_argument("--upstream-repo", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--port", type=int, default=41140)
    parser.add_argument("--ctx-size", type=int, default=8192)
    parser.add_argument("--gpu-layers", type=int, default=99)
    parser.add_argument("--mmproj", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("build/model-registration"))
    parser.add_argument("--install-systemd", action="store_true")
    parser.add_argument("--start", action="store_true", help="enable and start after installation")
    parser.add_argument("--config-dir", type=Path, default=Path("/etc/r740-ai-factory"))
    parser.add_argument("--install-dir", type=Path, default=Path("/opt/r740-ai-factory"))
    parser.add_argument("--state-dir", type=Path, default=Path("/var/lib/r740-ai-factory"))
    parser.add_argument("--service-user", default=os.getenv("R740_SERVICE_USER", "r740-ai"))
    args = parser.parse_args()
    if args.start and not args.install_systemd: parser.error("--start requires --install-systemd")
    if not SAFE_ID.fullmatch(args.id): parser.error("--id must be a safe 2-64 character lowercase identifier")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", args.service_user): parser.error("--service-user is invalid")

    model = regular(args.model); runtime = regular(args.runtime, executable=True)
    mmproj = regular(args.mmproj) if args.mmproj else None
    if args.install_systemd:
        if os.geteuid() != 0: raise SystemExit("FAIL --install-systemd must run as root")
        allowed = (args.state_dir / "models").resolve()
        if allowed not in model.parents:
            raise SystemExit(f"FAIL place the model under {allowed} before installation")
        if mmproj and allowed not in mmproj.parents:
            raise SystemExit(f"FAIL place the mmproj under {allowed} before installation")
        if Path("/home") in runtime.parents or Path("/root") in runtime.parents:
            raise SystemExit("FAIL install the runtime outside protected home directories")
        if not (args.config_dir / "runtime.env").is_file():
            raise SystemExit("FAIL install the Community control plane first")
        if not Path("/etc/systemd/system/r740-ai-factory.service").is_file():
            raise SystemExit("FAIL the Community control-plane systemd unit is absent")

    manifest: dict[str, object] = {
        "schema": 1, "model_id": args.id, "unit_slug": "community",
        "service_user": args.service_user, "port": args.port,
        "checksum_file": str(args.config_dir / "models.d" / f"{args.id}.sha256"),
        "runtime": str(runtime), "runtime_size": runtime.stat().st_size, "runtime_sha256": digest(runtime),
        "model": str(model), "model_size": model.stat().st_size, "model_sha256": digest(model),
        "ctx_size": args.ctx_size, "gpu_layers": args.gpu_layers, "parallel": 1,
        "jinja": True, "reasoning": "off", "flash_attn": "off", "fit": "off", "spec_type": "none",
    }
    if mmproj:
        manifest.update({"mmproj": str(mmproj), "mmproj_size": mmproj.stat().st_size, "mmproj_sha256": digest(mmproj), "image_min_tokens": 256})

    spec = importlib.util.spec_from_file_location("r740_model_renderer", RENDERER_PATH)
    assert spec and spec.loader
    renderer = importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)
    unit_name, unit, checksum_content = renderer.render(manifest)
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=True)
    atomic_text(output / "model.json", json.dumps(manifest, indent=2) + "\n", 0o600)
    atomic_text(output / unit_name, unit, 0o644)
    atomic_text(output / f"{args.id}.sha256", checksum_content, 0o644)
    catalog_entry = {
        "id": args.id, "display_name": args.display_name, "kind": "multimodal" if mmproj else "chat",
        "backend": "llama.cpp", "enabled": True, "upstream_repo": args.upstream_repo,
        "revision": args.revision, "artifact": model.name, "sha256": manifest["model_sha256"],
        "license": args.license, "minimum_ram_gib": None, "minimum_vram_gib": None,
        "notes": "Locally registered; exact runtime and artifact hashes are stored outside Git.",
    }
    atomic_text(output / "catalog-entry.json", json.dumps(catalog_entry, indent=2) + "\n", 0o600)
    print(f"PASS prepared {unit_name} in {output}")

    if not args.install_systemd: return
    for group in ("video", "render"):
        if subprocess.run(["getent", "group", group], stdout=subprocess.DEVNULL).returncode == 0:
            subprocess.run(["usermod", "-a", "-G", group, args.service_user], check=True)
    subprocess.run(["runuser", "-u", args.service_user, "--", "test", "-x", str(runtime)], check=True)
    subprocess.run(["runuser", "-u", args.service_user, "--", "test", "-r", str(model)], check=True)
    if mmproj: subprocess.run(["runuser", "-u", args.service_user, "--", "test", "-r", str(mmproj)], check=True)
    unit_target = Path("/etc/systemd/system") / unit_name
    manifest_target = args.config_dir / "models.d" / f"{args.id}.json"
    checksum_target = args.config_dir / "models.d" / f"{args.id}.sha256"
    catalog_target = args.install_dir / "model-manifests" / "catalog.json"
    env_target = args.config_dir / "runtime.env"
    for target in (unit_target, manifest_target, checksum_target, catalog_target, env_target):
        if target.exists(): shutil.copy2(target, target.with_name(target.name + f".bak-{int(time.time())}"))
    atomic_text(unit_target, unit, 0o644)
    atomic_text(manifest_target, json.dumps(manifest, indent=2) + "\n", 0o640)
    atomic_text(checksum_target, checksum_content, 0o644)
    catalog = json.loads(catalog_target.read_text(encoding="utf-8"))
    catalog["models"] = [item for item in catalog.get("models", []) if item.get("id") != args.id] + [catalog_entry]
    atomic_text(catalog_target, json.dumps(catalog, indent=2) + "\n", 0o644)
    update_env(env_target, "R740_INFERENCE_BASE_URL", f"http://127.0.0.1:{args.port}")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    if args.start:
        subprocess.run(["systemctl", "enable", "--now", unit_name], check=True)
        deadline = time.monotonic() + 480
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health", timeout=2) as response:
                    if response.status == 200: break
            except OSError: time.sleep(2)
        else: raise SystemExit(f"FAIL {unit_name} did not become healthy; inspect journalctl -u {unit_name}")
        subprocess.run(["systemctl", "restart", "r740-ai-factory.service"], check=False)
    print(f"PASS installed {unit_name}; backend URL is loopback-only")


if __name__ == "__main__":
    main()
