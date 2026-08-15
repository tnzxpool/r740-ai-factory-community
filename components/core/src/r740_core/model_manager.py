#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Root-only loopback controller for one-heavy-model-at-a-time switching."""

from __future__ import annotations

import fcntl
import base64
import json
import grp
import hashlib
import stat
import os
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .config import SETTINGS, env_path, env_service_map


INTERNAL_KEY = SETTINGS.internal_key
STATE_PATH = SETTINGS.model_state_path
LOCK = threading.Lock()
GPU_LOCK_PATH = SETTINGS.gpu_lock_path
GLM_MODEL_PATH = env_path("AI_GLM47_MODEL_PATH", SETTINGS.models_dir / "glm-4.7-flash.gguf")
QWEN_MODEL_PATH = env_path("AI_QWEN3_MODEL_PATH", SETTINGS.models_dir / "qwen3-8b.gguf")
QWEN36_MODEL_PATH = env_path("AI_QWEN36_MODEL_PATH", SETTINGS.models_dir / "qwen3.6-35b-a3b.gguf")
QWEN36_RESULT = QWEN36_MODEL_PATH.parent / "TEXT_CANARY_RESULT.json"
QWEN36_PASS = QWEN36_MODEL_PATH.parent / "TEXT_CANARY_PASS"
QWEN36_QUALIFICATION = env_path(
    "AI_QWEN36_QUALIFICATION", SETTINGS.state_dir / "qualifications" / "qwen36.json"
)
QWEN36_MODEL_SHA256 = "649d7508507b84638732c4f52c24c8b15843c6dca2f3ff793ae07c14a67ebbb3"
QWEN36_MODEL_BYTES = 17730509792
QWEN36_HERETIC_STAGE = env_path(
    "AI_QWEN36_HERETIC_DIR", SETTINGS.downloads_dir / "qwen36-heretic.staging"
)
QWEN36_HERETIC_MODEL_PATH = QWEN36_HERETIC_STAGE / "Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved.IQ4_XS.gguf"
QWEN36_HERETIC_RESULT = QWEN36_HERETIC_STAGE / "TEXT_CANARY_RESULT.json"
QWEN36_HERETIC_PASS = QWEN36_HERETIC_STAGE / "TEXT_CANARY_PASS"
QWEN36_HERETIC_VISION_RESULT = QWEN36_HERETIC_STAGE / "VISION_CANARY_RESULT.json"
QWEN36_HERETIC_VISION_PASS = QWEN36_HERETIC_STAGE / "VISION_CANARY_PASS"
QWEN36_HERETIC_MMPROJ = QWEN36_HERETIC_STAGE / "Qwen3.6-35B-A3B-uncensored-heretic-Native-MTP-Preserved.mmproj-Q8_0.gguf"
QWEN36_HERETIC_QUALIFICATION = env_path(
    "AI_QWEN36_HERETIC_QUALIFICATION", SETTINGS.state_dir / "qualifications" / "qwen36-heretic.json"
)
QWEN36_HERETIC_SHA256 = "2cae3fac7eaa5acf2b1aedce4426ca73f2953832a862c20f340eb5952869c423"
QWEN36_HERETIC_BYTES = 19389008096
QWEN36_HERETIC_MMPROJ_BYTES = 614194816
QWEN36_HERETIC_REVISION = "bc01551122139dc0c4ad4ac7d3e549d531a719d7"
GLM_CANARY_RESULT = env_path(
    "AI_GLM47_QUALIFICATION", SETTINGS.state_dir / "qualifications" / "glm47.json"
)
GLM_MODEL_SHA256 = "42c0c1a30fe2f30097ffedd554a94c2d6abc5f95b8a35ce99cd523f78ef6711b"
GLMOCR_STAGE = env_path("AI_GLM_OCR_DIR", SETTINGS.downloads_dir / "glm-ocr-q8.staging")
GLMOCR_MODEL_PATH = GLMOCR_STAGE / "GLM-OCR-Q8_0.gguf"
GLMOCR_MMPROJ_PATH = GLMOCR_STAGE / "mmproj-GLM-OCR-Q8_0.gguf"
GLMOCR_RESULT = GLMOCR_STAGE / "OCR_CANARY_RESULT.json"
GLMOCR_PASS = GLMOCR_STAGE / "OCR_CANARY_PASS"
GLMOCR_MODEL_SHA256 = "45bc244a6446aff850521dc41f18bc8d7105ad5f0c2c8c28af04e7cc4f4d50b1"
GLMOCR_MMPROJ_SHA256 = "9c4b58e33e316ed142eb5dcb41abec3844d3e6e5dc361ffb782c3fa9d175141f"
GLMOCR_ENDPOINT = SETTINGS.model_endpoints["glm-ocr-q8"]
MODEL_SERVICES = env_service_map("AI_MODEL_SERVICES_JSON", {
    "qwen3.6-35b-a3b-heretic-iq4xs": "r740-model-qwen36-heretic.service",
    "qwen3.6-35b-a3b-iq4xs": "r740-model-qwen36.service",
    "qwen3-8b": "r740-model-qwen3.service",
    "qwen3-vl-8b": "r740-model-qwen3vl.service",
    "glm-4.7-flash": "r740-model-glm47.service",
    "glm-ocr-q8": "r740-model-glm-ocr.service",
})
GLMOCR_SERVICE = MODEL_SERVICES["glm-ocr-q8"]
GLMOCR_MAX_IMAGE_BYTES = 600 * 1024
QUALIFIED_DEFAULT_MODEL = "qwen3.6-35b-a3b-iq4xs"
SAFETY_FALLBACK_MODEL = "qwen3-8b"


def qwen36_qualified() -> bool:
    try:
        model_stat = QWEN36_MODEL_PATH.stat()
        qualification_stat = QWEN36_QUALIFICATION.stat()
        if not stat.S_ISREG(model_stat.st_mode) or model_stat.st_size != QWEN36_MODEL_BYTES:
            return False
        if not stat.S_ISREG(qualification_stat.st_mode) or qualification_stat.st_uid != 0:
            return False
        if qualification_stat.st_mode & 0o022:
            return False
        marker = QWEN36_PASS.read_text(encoding="ascii").strip()
        result_bytes = QWEN36_RESULT.read_bytes()
        if marker != hashlib.sha256(result_bytes).hexdigest():
            return False
        result = json.loads(result_bytes)
        qualification = json.loads(QWEN36_QUALIFICATION.read_text(encoding="utf-8"))
        return bool(
            result.get("status") == "PASS"
            and result.get("phase") == "text"
            and int(result.get("context", 0)) == 8192
            and int(result.get("restart_cycles", 0)) >= 2
            and result.get("rollback_qwen3_8b_healthy") is True
            and qualification.get("model_sha256") == QWEN36_MODEL_SHA256
            and qualification.get("result_sha256") == marker
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def qwen36_heretic_qualified() -> bool:
    """Invisible and non-startable until the pinned P40 canary is attested."""
    try:
        model_stat = QWEN36_HERETIC_MODEL_PATH.stat()
        qstat = QWEN36_HERETIC_QUALIFICATION.stat()
        if not stat.S_ISREG(model_stat.st_mode) or model_stat.st_size != QWEN36_HERETIC_BYTES:
            return False
        if not stat.S_ISREG(qstat.st_mode) or qstat.st_uid != 0 or qstat.st_mode & 0o022:
            return False
        result_bytes = QWEN36_HERETIC_RESULT.read_bytes()
        result_sha = hashlib.sha256(result_bytes).hexdigest()
        if QWEN36_HERETIC_PASS.read_text(encoding="ascii").strip() != result_sha:
            return False
        result = json.loads(result_bytes)
        vision_bytes = QWEN36_HERETIC_VISION_RESULT.read_bytes()
        vision_sha = hashlib.sha256(vision_bytes).hexdigest()
        vision = json.loads(vision_bytes)
        qualification = json.loads(QWEN36_HERETIC_QUALIFICATION.read_text(encoding="utf-8"))
        metrics = result.get("gpu_and_ram", {})
        return bool(
            result.get("status") == "PASS" and result.get("phase") == "text"
            and int(result.get("context", 0)) == 8192 and result.get("mtp_enabled") is False
            and result.get("mmproj_loaded") is False and int(result.get("restart_cycles", 0)) >= 3
            and result.get("restore_official_qwen36_healthy") is True
            and result.get("fallback_qwen3_8b_used") is False
            and int(metrics.get("minimum_observed_margin_mib", 0)) >= 1536
            and int(metrics.get("peak_temperature_c", 999)) <= 85
            and QWEN36_HERETIC_MMPROJ.is_file()
            and QWEN36_HERETIC_MMPROJ.stat().st_size == QWEN36_HERETIC_MMPROJ_BYTES
            and QWEN36_HERETIC_VISION_PASS.read_text(encoding="ascii").strip() == vision_sha
            and vision.get("status") == "PASS" and vision.get("mmproj_loaded") is True
            and vision.get("vision_marker") == "ORCHIDEA 7419"
            and int(vision.get("gpu_margin_mib", 0)) >= 1536
            and qualification.get("model_sha256") == QWEN36_HERETIC_SHA256
            and qualification.get("result_sha256") == result_sha
            and qualification.get("vision_result_sha256") == vision_sha
            and qualification.get("multimodal") is True
            and qualification.get("revision") == QWEN36_HERETIC_REVISION
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def glm_qualified() -> bool:
    """Fail closed until the isolated 8K canary proves every required capability."""
    if not GLM_MODEL_PATH.is_file():
        return False
    try:
        result = json.loads(GLM_CANARY_RESULT.read_text(encoding="utf-8"))
        passed_tests = {
            str(item.get("name"))
            for item in result.get("tests", [])
            if isinstance(item, dict) and item.get("ok") is True
        }
        return bool(
            result.get("passed") is True
            and result.get("model_sha256") == GLM_MODEL_SHA256
            and int(result.get("context_size", 0)) == 8192
            and {"italiano", "coding", "json", "tool"}.issubset(passed_tests)
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def glmocr_qualified() -> bool:
    """Fast fail-closed check of root-owned deployment attestation."""
    try:
        if GLMOCR_MODEL_PATH.stat().st_size != 950433408:
            return False
        if GLMOCR_MMPROJ_PATH.stat().st_size != 484403648:
            return False
        attestation_path = GLMOCR_STAGE / "OCR_RUNTIME_ATTESTATION.json"
        attestation_stat = attestation_path.stat()
        if attestation_stat.st_uid != 0 or attestation_stat.st_mode & 0o022:
            return False
        attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
        result_bytes = GLMOCR_RESULT.read_bytes()
        if GLMOCR_PASS.read_text(encoding="ascii").strip() != hashlib.sha256(result_bytes).hexdigest():
            return False
        result = json.loads(result_bytes)
        return bool(
            attestation.get("model_sha256") == GLMOCR_MODEL_SHA256
            and attestation.get("mmproj_sha256") == GLMOCR_MMPROJ_SHA256
            and int(attestation.get("model_bytes", 0)) == 950433408
            and int(attestation.get("mmproj_bytes", 0)) == 484403648
            and result.get("status") == "PASS"
            and result.get("model") == "glm-ocr-q8"
            and int(result.get("restart_cycles", 0)) >= 2
            and int(result.get("exact_ocr_cycles", 0)) >= 2
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False

CATALOG: dict[str, dict[str, Any]] = {
    "qwen3.6-35b-a3b-heretic-iq4xs": {
        "display_name": "Qwen3.6 35B-A3B · Heretic",
        "service": MODEL_SERVICES["qwen3.6-35b-a3b-heretic-iq4xs"],
        "endpoint": SETTINGS.model_endpoints["qwen3.6-35b-a3b-heretic-iq4xs"],
        "health": f"{SETTINGS.model_endpoints['qwen3.6-35b-a3b-heretic-iq4xs']}/health",
        "available": False,
        "experimental": True,
        "capabilities": ["text", "reasoning", "coding", "tools", "vision", "ocr-visual"],
        "usage_line": "Manuale: conversazione meno filtrata e analisi immagini; non è il modello predefinito.",
        "traits_line": "SPERIMENTALE · MULTIMODALE · 8K · derivato comunitario · una GPU.",
        "timeout_seconds": 420,
    },
    "qwen3.6-35b-a3b-iq4xs": {
        "display_name": "Qwen3.6 35B-A3B",
        "service": MODEL_SERVICES["qwen3.6-35b-a3b-iq4xs"],
        "endpoint": SETTINGS.model_endpoints["qwen3.6-35b-a3b-iq4xs"],
        "health": f"{SETTINGS.model_endpoints['qwen3.6-35b-a3b-iq4xs']}/health",
        "available": False,
        "experimental": False,
        "capabilities": ["text", "reasoning", "coding", "tools"],
        "usage_line": "Predefinito per chat, ragionamento, codice e output strutturato.",
        "traits_line": "PREDEFINITO · MoE 35B-A3B · testo · contesto 8K · P40.",
        "timeout_seconds": 420,
    },
    "qwen3-8b": {
        "display_name": "Qwen3 8B",
        "service": MODEL_SERVICES["qwen3-8b"],
        "endpoint": SETTINGS.model_endpoints["qwen3-8b"],
        "health": f"{SETTINGS.model_endpoints['qwen3-8b']}/health",
        "available": False,
        "experimental": False,
        "capabilities": ["text", "reasoning"],
        "usage_line": "Per chat, scrittura e ragionamento quotidiano.",
        "traits_line": "STABILE · solo testo · rapido · predefinito.",
        "timeout_seconds": 180,
    },
    "qwen3-vl-8b": {
        "display_name": "Qwen3-VL 8B",
        "service": MODEL_SERVICES["qwen3-vl-8b"],
        "endpoint": SETTINGS.model_endpoints["qwen3-vl-8b"],
        "health": f"{SETTINGS.model_endpoints['qwen3-vl-8b']}/health",
        "available": (
            env_path("AI_QWEN3VL_MODEL_PATH", SETTINGS.models_dir / "qwen3-vl-8b.gguf").is_file()
            and env_path("AI_QWEN3VL_MMPROJ_PATH", SETTINGS.models_dir / "qwen3-vl-8b-mmproj.gguf").is_file()
        ),
        "experimental": True,
        "capabilities": ["text", "vision", "ocr-visual"],
        "usage_line": "Per immagini, schermate, grafici e documenti visivi.",
        "traits_line": "MULTIMODALE · OCR visivo · Q4 · un solo modello in GPU.",
        "timeout_seconds": 240,
    },
    "glm-4.7-flash": {
        "display_name": "GLM-4.7-Flash · 30B-A3B",
        "service": MODEL_SERVICES["glm-4.7-flash"],
        "endpoint": SETTINGS.model_endpoints["glm-4.7-flash"],
        "health": f"{SETTINGS.model_endpoints['glm-4.7-flash']}/health",
        "available": False,
        "experimental": True,
        "capabilities": ["text", "reasoning", "coding", "tools"],
        "usage_line": "Per coding, JSON strutturato e flussi con strumenti; usalo quando Qwen non basta.",
        "traits_line": "SPERIMENTALE · solo testo · contesto 8K · primo carico lungo (fino a 7 min) · una sessione alla volta.",
        "timeout_seconds": 420,
    },
}

app = FastAPI(title="R740 Model Manager", version="1.0.0", docs_url=None, redoc_url=None)


class SwitchRequest(BaseModel):
    model_id: str
    set_default: bool = False


class RestoreRequest(BaseModel):
    reason: str = "autorouting recovery"


class OcrRequest(BaseModel):
    image_base64: str
    image_sha256: str


@app.on_event("startup")
def reconcile_boot_baseline() -> None:
    # Restore the persistent default first. Qwen3-8B remains the fail-safe fallback.
    # A manager crash or container reboot must never leave the private OCR helper
    # running beside a text model.  The unit is also PartOf this manager.
    subprocess.run(["systemctl", "stop", GLMOCR_SERVICE], check=False, timeout=60)
    configured_default = str(read_state()["default_model"])
    candidates = [(configured_default, "persistent default")]
    if configured_default != SAFETY_FALLBACK_MODEL:
        candidates.append((SAFETY_FALLBACK_MODEL, "safety fallback"))
    for model_id, reason in candidates:
        spec = CATALOG[model_id]
        # systemd considera il servizio avviato prima che llama-server abbia
        # completato il caricamento del modello. Attendere la readiness evita
        # un falso rollback al modello 8B durante il boot.
        if model_available(model_id) and not service_active(str(spec["service"])):
            subprocess.run(["systemctl", "start", str(spec["service"])], check=False, timeout=60)
        if service_active(str(spec["service"])) and wait_healthy(model_id):
            write_state(model_id, {"result": "boot_reconcile", "reason": reason, "at": int(time.time())})
            return
    failed = rollback("boot default unavailable")
    if not failed.get("healthy"):
        raise RuntimeError("nessun backend testuale avviabile al boot")


def require_key(value: str | None) -> None:
    if not INTERNAL_KEY or value is None or not secrets.compare_digest(value, INTERNAL_KEY):
        raise HTTPException(status_code=401, detail="controller non autorizzato")


def service_active(service: str) -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", service], check=False, timeout=10
    ).returncode == 0


def backend_healthy(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_healthy(model_id: str) -> bool:
    spec = CATALOG[model_id]
    deadline = time.monotonic() + int(spec["timeout_seconds"])
    while time.monotonic() < deadline:
        if service_active(str(spec["service"])) and backend_healthy(str(spec["health"])):
            return True
        time.sleep(1)
    return False


def model_available(model_id: str) -> bool:
    if model_id == "qwen3.6-35b-a3b-iq4xs":
        return qwen36_qualified()
    if model_id == "qwen3.6-35b-a3b-heretic-iq4xs":
        return qwen36_heretic_qualified()
    if model_id == "qwen3-8b":
        return QWEN_MODEL_PATH.is_file()
    if model_id == "glm-4.7-flash":
        return glm_qualified()
    return bool(CATALOG[model_id]["available"])


def read_state() -> dict[str, Any]:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        active_model = state.get("active_model")
        if active_model in CATALOG:
            default_model = state.get("default_model")
            if default_model not in CATALOG:
                default_model = QUALIFIED_DEFAULT_MODEL
            return {**state, "schema": 2, "active_model": active_model, "default_model": default_model}
    except (OSError, ValueError):
        pass
    return {
        "schema": 2,
        "active_model": SAFETY_FALLBACK_MODEL,
        "default_model": QUALIFIED_DEFAULT_MODEL,
        "updated_at": None,
        "last_switch": None,
    }


def write_state(
    active_model: str, detail: dict[str, Any], default_model: str | None = None
) -> None:
    if active_model not in CATALOG:
        raise ValueError("active model outside catalog")
    persistent_default = default_model or str(read_state()["default_model"])
    if persistent_default not in CATALOG:
        raise ValueError("default model outside catalog")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 2,
        "active_model": active_model,
        "default_model": persistent_default,
        "endpoint": CATALOG[active_model]["endpoint"],
        "updated_at": int(time.time()),
        "last_switch": detail,
    }
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=STATE_PATH.parent, prefix=".model-state-", delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.chmod(temporary, 0o640)
    os.chown(temporary, 0, grp.getgrnam(SETTINGS.runtime_group).gr_gid)
    os.replace(temporary, STATE_PATH)


def status_payload() -> dict[str, Any]:
    state = read_state()
    models: dict[str, Any] = {}
    for model_id, spec in CATALOG.items():
        models[model_id] = {
            key: value
            for key, value in spec.items()
            if key not in {"health", "timeout_seconds"}
        }
        models[model_id]["available"] = model_available(model_id)
        models[model_id]["service_active"] = service_active(str(spec["service"]))
        models[model_id]["healthy"] = backend_healthy(str(spec["health"]), timeout=1.0)
    active = str(state.get("active_model", "qwen3-8b"))
    return {
        "active_model": active,
        "default_model": str(state["default_model"]),
        "active_healthy": models.get(active, {}).get("healthy", False),
        "switch_in_progress": LOCK.locked(),
        "models": models,
        "state": state,
        "policy": {
            "one_heavy_model": True,
            "fallback_model": "qwen3-8b",
            "default_model": str(state["default_model"]),
            "admin_only": True,
        },
    }


def run_systemctl(action: str, service: str) -> None:
    subprocess.run(["systemctl", action, service], check=True, timeout=60)


def rollback(reason: str) -> dict[str, Any]:
    for model_id, spec in CATALOG.items():
        if model_id != "qwen3-8b":
            subprocess.run(["systemctl", "stop", str(spec["service"])], check=False, timeout=60)
    run_systemctl("start", str(CATALOG["qwen3-8b"]["service"]))
    healthy = wait_healthy("qwen3-8b")
    if healthy:
        write_state("qwen3-8b", {"result": "rollback", "reason": reason, "at": int(time.time())})
    return {"model_id": "qwen3-8b", "healthy": healthy, "reason": reason}


def restore_default(reason: str) -> dict[str, Any]:
    """Restore the persistent default; use Qwen3-8B only as safety fallback."""
    default_model = str(read_state()["default_model"])
    subprocess.run(["systemctl", "stop", GLMOCR_SERVICE], check=False, timeout=60)
    for model_id, spec in CATALOG.items():
        if model_id != default_model:
            subprocess.run(["systemctl", "stop", str(spec["service"])], check=False, timeout=60)
    if model_available(default_model):
        subprocess.run(["systemctl", "start", str(CATALOG[default_model]["service"])], check=False, timeout=60)
        if wait_healthy(default_model):
            write_state(default_model, {"result": "default_restore", "reason": reason, "at": int(time.time())})
            return {"model_id": default_model, "default_model": default_model, "healthy": True, "fallback": False}
    result = rollback(f"default restore failed for {default_model}: {reason}")
    result["fallback"] = True
    result["default_model"] = default_model
    return result


class OcrNoTextDecoded(Exception):
    """The OCR backend answered successfully but decoded no usable text."""


def glmocr_completion(image: bytes) -> tuple[str, dict[str, Any]]:
    payload = {
        "model": "glm-ocr-q8",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")}},
            {"type": "text", "text": "Text Recognition:"},
        ]}],
        "temperature": 0,
        "max_tokens": 4096,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{GLMOCR_ENDPOINT}/v1/chat/completions",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=210) as response:
        data = json.load(response)
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise ValueError("invalid OCR content type")
    text = content.replace("\x00", " ").strip()
    if not text:
        raise OcrNoTextDecoded("empty OCR output")
    if len(text) > 300000:
        raise ValueError("invalid OCR output")
    return text, {"usage": data.get("usage", {}), "timings": data.get("timings", {})}


@app.post("/v1/internal/ocr/extract")
def ocr_extract(
    request: OcrRequest, x_internal_key: str | None = Header(default=None)
) -> dict[str, Any]:
    """Private transactional OCR: stop text, OCR once, always restore default."""
    require_key(x_internal_key)
    if not glmocr_qualified():
        raise HTTPException(status_code=409, detail="GLM-OCR non qualificato")
    try:
        image = base64.b64decode(request.image_base64, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="immagine OCR non valida")
    if not image or len(image) > GLMOCR_MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="immagine OCR oltre il limite")
    if not secrets.compare_digest(hashlib.sha256(image).hexdigest(), request.image_sha256.lower()):
        raise HTTPException(status_code=400, detail="digest immagine OCR non valido")
    if not LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="motore occupato")
    gpu_lock = None
    restored: dict[str, Any] = {"healthy": False}
    transaction_started = False
    started = time.monotonic()
    try:
        gpu_lock = GPU_LOCK_PATH.open("a+")
        try:
            fcntl.flock(gpu_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(status_code=409, detail="GPU occupata")
        transaction_started = True
        for spec in CATALOG.values():
            subprocess.run(["systemctl", "stop", str(spec["service"])], check=False, timeout=90)
        run_systemctl("start", GLMOCR_SERVICE)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            if service_active(GLMOCR_SERVICE) and backend_healthy(f"{GLMOCR_ENDPOINT}/health"):
                break
            time.sleep(1)
        else:
            raise RuntimeError("GLM-OCR readiness timeout")
        text, metrics = glmocr_completion(image)
        return {
            "ok": True,
            "text": text,
            "characters": len(text),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "engine": "glm-ocr-q8",
            **metrics,
        }
    except OcrNoTextDecoded:
        raise HTTPException(status_code=422, detail={
            "code": "no_text_extracted",
            "message": "Anche l'OCR avanzato non ha trovato testo affidabile; usa Visione diretta.",
            "stored": False,
            "rag_added": False,
            "recommended_action": "direct_vision",
            "required_model": "qwen3-vl-8b",
            "vision_compatible": True,
        })
    except HTTPException:
        raise
    except (OSError, subprocess.SubprocessError, urllib.error.URLError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"OCR non disponibile: {type(exc).__name__}")
    finally:
        recovery_error: str | None = None
        try:
            if transaction_started:
                try:
                    restored = restore_default("GLM-OCR transaction complete")
                except (OSError, subprocess.SubprocessError) as exc:
                    recovery_error = type(exc).__name__
        finally:
            try:
                if gpu_lock is not None:
                    try:
                        fcntl.flock(gpu_lock.fileno(), fcntl.LOCK_UN)
                    finally:
                        gpu_lock.close()
            finally:
                LOCK.release()
        if transaction_started and (recovery_error or not restored.get("healthy")):
            # The request may already have produced output, but serving it while
            # no text baseline exists would hide a critical recovery failure.
            raise HTTPException(status_code=503, detail="OCR concluso ma ripristino modello fallito")


@app.get("/health")
def health() -> dict[str, Any]:
    payload = status_payload()
    return {"status": "ok" if payload["active_healthy"] else "degraded", **payload}


@app.get("/v1/models/status")
def models_status(x_internal_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_internal_key)
    return status_payload()


@app.get("/v1/autorouting/specialists")
def autorouting_specialists(x_internal_key: str | None = Header(default=None)) -> dict[str, bool]:
    require_key(x_internal_key)
    return {"glm-ocr-q8": glmocr_qualified()}


@app.post("/v1/models/restore-default")
def autorouting_restore_default(
    request: RestoreRequest, x_internal_key: str | None = Header(default=None)
) -> dict[str, Any]:
    require_key(x_internal_key)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="controller occupato")
    gpu_lock = None
    try:
        gpu_lock = GPU_LOCK_PATH.open("a+")
        try:
            fcntl.flock(gpu_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(status_code=409, detail="GPU occupata")
        default_model = str(read_state()["default_model"])
        for model_id, spec in CATALOG.items():
            if model_id != default_model:
                subprocess.run(["systemctl", "stop", str(spec["service"])], check=False, timeout=90)
        subprocess.run(["systemctl", "stop", GLMOCR_SERVICE], check=False, timeout=90)
        restored = restore_default(request.reason[:160])
        status = status_payload()
        active_heavy = sorted(
            model_id for model_id, spec in status["models"].items()
            if isinstance(spec, dict) and spec.get("service_active") is True
        )
        restored_model = str(restored.get("model_id") or "")
        one_heavy = restored.get("healthy") is True and active_heavy == [restored_model]
        return {
            **restored,
            "default_model": default_model,
            "one_heavy": one_heavy,
            "active_heavy": active_heavy,
        }
    finally:
        if gpu_lock is not None:
            try:
                fcntl.flock(gpu_lock.fileno(), fcntl.LOCK_UN)
            finally:
                gpu_lock.close()
        LOCK.release()


@app.post("/v1/models/switch")
def switch_model(
    request: SwitchRequest, x_internal_key: str | None = Header(default=None)
) -> dict[str, Any]:
    require_key(x_internal_key)
    target = request.model_id.strip()
    if target not in CATALOG:
        raise HTTPException(status_code=400, detail="modello sconosciuto")
    if not model_available(target):
        if target == "qwen3.6-35b-a3b-iq4xs":
            detail = "Qwen3.6 non qualificato: TEXT_CANARY_PASS o attestazione non validi"
        elif target == "qwen3.6-35b-a3b-heretic-iq4xs":
            detail = "Heretic invisibile: canary P40 o attestazione non validi"
        elif target == "glm-4.7-flash":
            detail = "GLM non qualificato: eseguire prima il canary 8K italiano/coding/JSON/tool"
        else:
            detail = "modello non installato"
        raise HTTPException(status_code=409, detail=detail)
    if not LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="cambio modello già in corso")
    gpu_lock = None
    try:
        gpu_lock = GPU_LOCK_PATH.open("a+")
        try:
            fcntl.flock(gpu_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(status_code=409, detail="sessione grafica attiva; rilascia prima la GPU")
        current_state = read_state()
        current = str(current_state.get("active_model", SAFETY_FALLBACK_MODEL))
        if target == current and backend_healthy(str(CATALOG[target]["health"])):
            default_changed = bool(request.set_default and current_state["default_model"] != target)
            if default_changed:
                write_state(
                    target,
                    {"result": "default_updated", "to": target, "at": int(time.time())},
                    default_model=target,
                )
            return {"ok": True, "changed": False, "default_changed": default_changed, **status_payload()}

        started = time.monotonic()
        for model_id, spec in CATALOG.items():
            if model_id != target:
                subprocess.run(["systemctl", "stop", str(spec["service"])], check=False, timeout=60)
        run_systemctl("start", str(CATALOG[target]["service"]))
        if not wait_healthy(target):
            failed = rollback(f"health check fallito per {target}")
            raise HTTPException(
                status_code=503,
                detail={"message": "modello non avviato; rollback eseguito", "rollback": failed},
            )
        write_state(
            target,
            {
                "result": "success",
                "from": current,
                "to": target,
                "duration_seconds": round(time.monotonic() - started, 3),
                "at": int(time.time()),
            },
            default_model=target if request.set_default else str(current_state["default_model"]),
        )
        return {"ok": True, "changed": True, **status_payload()}
    except HTTPException:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        failed = rollback(f"controller error {type(exc).__name__}")
        raise HTTPException(
            status_code=503,
            detail={"message": "errore controller; rollback eseguito", "rollback": failed},
        )
    finally:
        if gpu_lock is not None:
            try:
                fcntl.flock(gpu_lock.fileno(), fcntl.LOCK_UN)
            finally:
                gpu_lock.close()
        LOCK.release()
