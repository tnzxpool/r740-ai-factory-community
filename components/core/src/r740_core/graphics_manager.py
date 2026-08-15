#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Single-P40 SDXL queue with warm-session reuse and automatic text-model restore."""

from __future__ import annotations

import fcntl
import gc
import grp
import hashlib
import json
import os
import queue
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import SETTINGS, env_path, env_service_map


INTERNAL_KEY = SETTINGS.internal_key
MODEL_DIR = env_path("AI_SDXL_MODEL_DIR", SETTINGS.models_dir / "stable-diffusion-xl-base-1.0")
SDXL_ENGINE = "sdxl-1.0-fp16"
REALVIS_ENGINE = "realvisxl-v5"
REALVIS_REVISION = "ac93e0dda1f6d448cae19bbfab8c5e720a5e48bc"
REALVIS_SHA256 = "6a35a7855770ae9820a3c931d4964c3817b6d9e3c6f9c4dabb5b3a94e5643b80"
REALVIS_BYTES = 6938065488
REALVIS_DIR = env_path("AI_REALVISXL_DIR", SETTINGS.downloads_dir / "realvisxl-v5.staging")
REALVIS_CHECKPOINT = REALVIS_DIR / "RealVisXL_V5.0_fp16.safetensors"
REALVIS_QUALIFICATION = env_path(
    "AI_REALVISXL_QUALIFICATION",
    SETTINGS.results_dir / "images" / "canary" / "realvisxl-v5" / "qualification.json",
)
REALVIS_TELEMETRY = REALVIS_QUALIFICATION.with_name("gpu-summary.json")
RESULTS_DIR = env_path("AI_GRAPHICS_RESULTS_DIR", SETTINGS.results_dir / "images")
STATE_PATH = SETTINGS.graphics_state_path
MODEL_STATE_PATH = SETTINGS.model_state_path
GPU_LOCK_PATH = SETTINGS.gpu_lock_path
ORCHESTRATOR_STATUS = f"{SETTINGS.orchestrator_url}/status"
SPACE_CHECK = str(env_path("AI_SPACE_CHECK", SETTINGS.libexec_dir / "space-check"))
WARM_TTL_SECONDS = SETTINGS.graphics_warm_ttl
MAX_QUEUE = SETTINGS.graphics_max_queue
MAX_OWNER_PENDING = 2
RESULT_RETENTION_SECONDS = 14 * 86400
RESULT_MAX_BYTES = 3 * 1024**3
RESULT_MAX_FILES = 200

MODEL_SERVICES = env_service_map("AI_MODEL_SERVICES_JSON", {
    "qwen3.6-35b-a3b-heretic-iq4xs": "r740-model-qwen36-heretic.service",
    "qwen3.6-35b-a3b-iq4xs": "r740-model-qwen36.service",
    "qwen3-8b": "r740-model-qwen3.service",
    "qwen3-vl-8b": "r740-model-qwen3vl.service",
    "glm-4.7-flash": "r740-model-glm47.service",
    "glm-ocr-q8": "r740-model-glm-ocr.service",
})
TEXT_MODELS = {
    "qwen3.6-35b-a3b-heretic-iq4xs": {
        "service": MODEL_SERVICES["qwen3.6-35b-a3b-heretic-iq4xs"],
        "health": f"{SETTINGS.model_endpoints['qwen3.6-35b-a3b-heretic-iq4xs']}/health",
        "endpoint": SETTINGS.model_endpoints["qwen3.6-35b-a3b-heretic-iq4xs"],
    },
    "qwen3.6-35b-a3b-iq4xs": {
        "service": MODEL_SERVICES["qwen3.6-35b-a3b-iq4xs"],
        "health": f"{SETTINGS.model_endpoints['qwen3.6-35b-a3b-iq4xs']}/health",
        "endpoint": SETTINGS.model_endpoints["qwen3.6-35b-a3b-iq4xs"],
    },
    "qwen3-8b": {
        "service": MODEL_SERVICES["qwen3-8b"],
        "health": f"{SETTINGS.model_endpoints['qwen3-8b']}/health",
        "endpoint": SETTINGS.model_endpoints["qwen3-8b"],
    },
    "qwen3-vl-8b": {
        "service": MODEL_SERVICES["qwen3-vl-8b"],
        "health": f"{SETTINGS.model_endpoints['qwen3-vl-8b']}/health",
        "endpoint": SETTINGS.model_endpoints["qwen3-vl-8b"],
    },
    "glm-4.7-flash": {
        "service": MODEL_SERVICES["glm-4.7-flash"],
        "health": f"{SETTINGS.model_endpoints['glm-4.7-flash']}/health",
        "endpoint": SETTINGS.model_endpoints["glm-4.7-flash"],
    },
}

app = FastAPI(title="R740 Graphics Manager", version="1.0.0", docs_url=None, redoc_url=None)


class JobRequest(BaseModel):
    owner: str = Field(min_length=3, max_length=96)
    prompt: str = Field(min_length=3, max_length=1200)
    negative_prompt: str = Field(default="", max_length=600)
    width: int = 768
    height: int = 768
    steps: int = 20
    seed: int | None = None
    engine: str = SDXL_ENGINE


class EngineSelection(BaseModel):
    engine: str


def _trusted_regular_file(path: Path) -> bool:
    try:
        stat = path.lstat()
        return path.is_file() and not path.is_symlink() and stat.st_uid == 0 and not (stat.st_mode & 0o022)
    except OSError:
        return False


def _qualification_payload_valid(qualification: dict[str, Any], telemetry: dict[str, Any]) -> bool:
    expected_profiles = {"draft": (512, 512, 12), "balanced": (768, 768, 20), "quality": (1024, 1024, 30)}
    observed = {
        str(item.get("profile")): (int(item.get("width", 0)), int(item.get("height", 0)), int(item.get("steps", 0)))
        for item in qualification.get("profiles", []) if item.get("status") == "PASS"
    }
    fallback = qualification.get("sdxl_fallback") or {}
    return (
        qualification.get("status") == "PASS"
        and qualification.get("model") == REALVIS_ENGINE
        and qualification.get("revision") == REALVIS_REVISION
        and qualification.get("checkpoint_sha256") == REALVIS_SHA256
        and observed == expected_profiles
        and fallback.get("status") == "PASS"
        and fallback.get("engine") == SDXL_ENGINE
        and telemetry.get("status") == "PASS"
        and float(telemetry.get("max_temperature_c", 999)) <= 85
        and float(telemetry.get("max_memory_mib", 99999)) <= 22528
        and float(telemetry.get("max_power_w", 9999)) <= 262.5
    )


def realvis_qualified() -> bool:
    marker = REALVIS_DIR / ".PAYLOAD_VERIFIED"
    try:
        if not all(_trusted_regular_file(path) for path in (REALVIS_CHECKPOINT, marker, REALVIS_QUALIFICATION, REALVIS_TELEMETRY)):
            return False
        if REALVIS_CHECKPOINT.stat().st_size != REALVIS_BYTES:
            return False
        expected = (
            f"repo=SG161222/RealVisXL_V5.0 revision={REALVIS_REVISION} "
            f"file={REALVIS_CHECKPOINT.name} bytes={REALVIS_BYTES} sha256={REALVIS_SHA256}"
        )
        if marker.read_text(encoding="utf-8").strip() != expected:
            return False
        qualification = json.loads(REALVIS_QUALIFICATION.read_text(encoding="utf-8"))
        telemetry = json.loads(REALVIS_TELEMETRY.read_text(encoding="utf-8"))
        return _qualification_payload_valid(qualification, telemetry)
    except (OSError, ValueError, TypeError):
        return False


def engine_catalog() -> list[dict[str, Any]]:
    engines = [{
        "id": SDXL_ENGINE, "display_name": "SDXL 1.0", "qualified": True,
        "default": True, "fallback": True,
        "description": "Stabile, predefinito e fallback automatico.",
        "profiles": {"draft": {"size": 512, "steps": 12}, "balanced": {"size": 768, "steps": 20}, "quality": {"size": 1024, "steps": 28}},
    }]
    if realvis_qualified():
        engines.append({
            "id": REALVIS_ENGINE, "display_name": "RealVisXL V5.0", "qualified": True,
            "default": False, "fallback": False,
            "description": "Fotorealistico: carico 3,3 s; bozza 9,2 s; bilanciata 28,2 s; qualità 87,3 s.",
            "profiles": {"draft": {"size": 512, "steps": 12}, "balanced": {"size": 768, "steps": 20}, "quality": {"size": 1024, "steps": 30}},
        })
    return engines


class GraphicsManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.release_lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.pending: queue.Queue[str] = queue.Queue(maxsize=MAX_QUEUE)
        self.pipeline: Any = None
        self.loaded_engine: str | None = None
        self.selected_engine = SDXL_ENGINE
        self.gpu_lock_handle: Any = None
        self.active_job: str | None = None
        self.previous_model = "qwen3.6-35b-a3b-iq4xs"
        self.state = "cold"
        self.warm_until = 0.0
        self.last_error: str | None = None
        self.last_load_seconds: float | None = None
        self.last_generation_seconds: float | None = None
        self.last_seconds_per_step: float | None = None
        self.stop_event = threading.Event()
        self._load_persisted()
        self.worker = threading.Thread(target=self._worker_loop, name="graphics-worker", daemon=True)
        self.watchdog = threading.Thread(target=self._watchdog_loop, name="graphics-watchdog", daemon=True)

    def start(self) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        self._cleanup_results()
        active = any(
            subprocess.run(
                ["systemctl", "is-active", "--quiet", spec["service"]],
                check=False,
                timeout=10,
            ).returncode == 0
            for spec in TEXT_MODELS.values()
        )
        if not active:
            target = self._read_active_model()
            if not self._start_and_wait(target):
                self._start_and_wait("qwen3-8b")
        self.worker.start()
        self.watchdog.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.active_job is None:
            self._release_pipeline("service_stop")

    def require_owner(self, owner: str) -> str:
        value = owner.strip()
        if not value.startswith("user:") or not value[5:].isdigit():
            raise HTTPException(status_code=400, detail="identità proprietario non valida")
        return value

    def submit(self, request: JobRequest) -> dict[str, Any]:
        owner = self.require_owner(request.owner)
        prompt = " ".join(request.prompt.replace("\x00", " ").split()).strip()
        negative = " ".join(request.negative_prompt.replace("\x00", " ").split()).strip()
        if len(prompt) < 3:
            raise HTTPException(status_code=400, detail="descrizione troppo breve")
        catalog = {item["id"]: item for item in engine_catalog()}
        if request.engine not in catalog:
            raise HTTPException(status_code=400, detail="motore grafico non disponibile")
        with self.lock:
            if request.engine != self.selected_engine:
                raise HTTPException(status_code=409, detail="motore grafico non più selezionato")
        allowed_profiles = {
            (int(profile["size"]), int(profile["size"]), int(profile["steps"]))
            for profile in catalog[request.engine]["profiles"].values()
        }
        if (request.width, request.height, request.steps) not in allowed_profiles:
            raise HTTPException(status_code=400, detail="profilo grafico non consentito")
        if subprocess.run([SPACE_CHECK], check=False, capture_output=True, timeout=30).returncode != 0:
            raise HTTPException(status_code=409, detail="spazio protetto: nuova immagine non accettata")

        with self.lock:
            owner_pending = sum(
                1 for job in self.jobs.values()
                if job.get("owner") == owner and job.get("state") in {"queued", "waiting", "loading", "generating"}
            )
            if owner_pending >= MAX_OWNER_PENDING:
                raise HTTPException(status_code=429, detail="hai già due immagini in lavorazione")
            if self.pending.full():
                raise HTTPException(status_code=429, detail="coda grafica piena")
            job_id = uuid.uuid4().hex
            seed = request.seed if request.seed is not None else secrets.randbelow(2**31 - 1)
            now = int(time.time())
            self.jobs[job_id] = {
                "id": job_id,
                "owner": owner,
                "engine": request.engine,
                "state": "queued",
                "prompt": prompt,
                "negative_prompt": negative,
                "width": request.width,
                "height": request.height,
                "steps": request.steps,
                "seed": int(seed),
                "current_step": 0,
                "created_at": now,
                "updated_at": now,
                "result_path": None,
                "error": None,
                "load_seconds": None,
                "generation_seconds": None,
            }
            self.state = "queued" if self.pipeline is None else "warm"
            self.pending.put_nowait(job_id)
            self._persist()
            return self.public_job(job_id, owner)

    def public_job(self, job_id: str, owner: str | None = None, admin: bool = False) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise HTTPException(status_code=404, detail="lavoro grafico non trovato")
            if not admin and owner != job.get("owner"):
                raise HTTPException(status_code=404, detail="lavoro grafico non trovato")
            result_ready = bool(job.get("result_path") and Path(str(job["result_path"])).is_file())
            position = None
            if job["state"] == "queued":
                queued = [item for item in self.jobs.values() if item.get("state") == "queued"]
                queued.sort(key=lambda item: item["created_at"])
                position = next((i + 1 for i, item in enumerate(queued) if item["id"] == job_id), None)
            payload = {
                key: job.get(key) for key in (
                    "id", "state", "engine", "width", "height", "steps", "seed", "current_step",
                    "created_at", "updated_at", "error", "load_seconds", "generation_seconds",
                )
            } | {
                "display_name": next((item["display_name"] for item in engine_catalog() if item["id"] == job.get("engine")), "SDXL 1.0"),
                "result_ready": result_ready,
                "queue_position": position,
            }
            if not admin and payload.get("error"):
                payload["error"] = "generazione fallita; l'amministratore può consultare il dettaglio"
            return payload

    def result(self, job_id: str, owner: str | None, admin: bool = False) -> Path:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job or (not admin and owner != job.get("owner")):
                raise HTTPException(status_code=404, detail="immagine non trovata")
            path = Path(str(job.get("result_path") or ""))
            if job.get("state") != "ready" or not path.is_file() or RESULTS_DIR not in path.parents:
                raise HTTPException(status_code=409, detail="immagine non ancora pronta")
            return path

    def status_payload(self, admin: bool = False) -> dict[str, Any]:
        with self.lock:
            now = time.time()
            queued = sum(1 for job in self.jobs.values() if job.get("state") == "queued")
            payload: dict[str, Any] = {
                "engine": self.loaded_engine or self.selected_engine,
                "selected_engine": self.selected_engine,
                "display_name": "RealVisXL V5.0" if (self.loaded_engine or self.selected_engine) == REALVIS_ENGINE else "SDXL 1.0",
                "available": MODEL_DIR.joinpath("CODEX_SOURCE.json").is_file(),
                "engines": engine_catalog(),
                "state": self.state,
                "queue_depth": queued,
                "active_job": self.active_job if admin else bool(self.active_job),
                "warm": self.pipeline is not None,
                "warm_remaining_seconds": max(0, int(self.warm_until - now)) if self.pipeline is not None else 0,
                "warm_ttl_seconds": WARM_TTL_SECONDS,
                "last_load_seconds": self.last_load_seconds,
                "last_generation_seconds": self.last_generation_seconds,
                "last_seconds_per_step": self.last_seconds_per_step,
                "last_error": self.last_error if admin else ("errore recente" if self.last_error else None),
                "policy": {
                    "one_heavy_model": True,
                    "max_queue": MAX_QUEUE,
                    "max_owner_pending": MAX_OWNER_PENDING,
                    "result_retention_days": 14,
                    "profiles": {
                        "draft": {"size": 512, "steps": 12},
                        "balanced": {"size": 768, "steps": 20},
                        "quality": {"size": 1024, "steps": 28},
                    },
                },
            }
            return payload

    def select_engine(self, engine: str) -> dict[str, Any]:
        catalog = {item["id"]: item for item in engine_catalog()}
        if engine not in catalog:
            raise HTTPException(status_code=400, detail="motore grafico non disponibile o non qualificato")
        with self.lock:
            if self.active_job or not self.pending.empty() or self.pipeline is not None:
                raise HTTPException(status_code=409, detail="chiudi la sessione grafica prima di cambiare motore")
            self.selected_engine = engine
            self._persist()
        return self.status_payload(admin=True)

    def release_now(self) -> dict[str, Any]:
        with self.lock:
            if self.active_job or not self.pending.empty():
                raise HTTPException(status_code=409, detail="generazione o coda ancora attiva")
        self._release_pipeline("admin_release")
        return self.status_payload(admin=True)

    def _worker_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                job_id = self.pending.get(timeout=1)
            except queue.Empty:
                continue
            try:
                self._run_job(job_id)
            except Exception as exc:  # fail closed; details stay server-side
                with self.lock:
                    job = self.jobs.get(job_id)
                    if job:
                        job["state"] = "failed"
                        job["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
                        job["updated_at"] = int(time.time())
                    self.last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
                    self.active_job = None
                    self.state = "warm" if self.pipeline is not None else "error"
                    self._persist()
                if self.gpu_lock_handle is not None:
                    self._release_pipeline("job_failed")
            finally:
                self.pending.task_done()

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job["state"] = "waiting"
            job["updated_at"] = int(time.time())
            self.active_job = job_id
            self.state = "waiting"
            self._persist()
        requested_engine = str(job.get("engine") or SDXL_ENGINE)
        if self.pipeline is None:
            load_seconds = self._load_pipeline(requested_engine)
            with self.lock:
                job["load_seconds"] = round(load_seconds, 3)
        elif self.loaded_engine != requested_engine:
            load_seconds = self._switch_pipeline(requested_engine)
            with self.lock:
                job["load_seconds"] = round(load_seconds, 3)
        with self.lock:
            job["state"] = "generating"
            job["current_step"] = 0
            job["updated_at"] = int(time.time())
            self.state = "generating"
            self._persist()

        import torch

        generator = torch.Generator(device="cuda").manual_seed(int(job["seed"]))

        def progress(_pipe: Any, step_index: int, _timestep: Any, callback_kwargs: dict[str, Any]):
            with self.lock:
                job["current_step"] = int(step_index) + 1
                job["updated_at"] = int(time.time())
            return callback_kwargs

        started = time.perf_counter()
        with torch.inference_mode():
            image = self.pipeline(
                prompt=job["prompt"],
                negative_prompt=job["negative_prompt"] or None,
                width=int(job["width"]),
                height=int(job["height"]),
                num_inference_steps=int(job["steps"]),
                guidance_scale=5.0 if requested_engine == REALVIS_ENGINE else 6.0,
                generator=generator,
                callback_on_step_end=progress,
            ).images[0]
        torch.cuda.synchronize()
        generation_seconds = time.perf_counter() - started

        owner_hash = hashlib.sha256(job["owner"].encode()).hexdigest()[:16]
        target_dir = RESULTS_DIR / owner_hash
        target_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(target_dir, 0o750)
        final_path = target_dir / f"{job_id}.png"
        with tempfile.NamedTemporaryFile(suffix=".png", dir=target_dir, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            image.save(temporary, format="PNG", optimize=True)
            os.chmod(temporary, 0o640)
            os.replace(temporary, final_path)
        finally:
            temporary.unlink(missing_ok=True)

        with self.lock:
            job["state"] = "ready"
            job["result_path"] = str(final_path)
            job["generation_seconds"] = round(generation_seconds, 3)
            job["current_step"] = int(job["steps"])
            job["updated_at"] = int(time.time())
            self.last_generation_seconds = round(generation_seconds, 3)
            self.last_seconds_per_step = round(generation_seconds / int(job["steps"]), 3)
            self.active_job = None
            self.warm_until = time.time() + WARM_TTL_SECONDS
            self.state = "warm"
            self.last_error = None
            self._persist()
        self._cleanup_results()

    def _construct_pipeline(self, engine: str) -> tuple[Any, float]:
        import torch
        from diffusers import StableDiffusionXLPipeline

        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_math_sdp(True)
        torch.cuda.empty_cache()
        started = time.perf_counter()
        if engine == REALVIS_ENGINE:
            if not realvis_qualified():
                raise RuntimeError("RealVisXL non è più qualificato")
            pipeline = StableDiffusionXLPipeline.from_single_file(
                str(REALVIS_CHECKPOINT), config=str(MODEL_DIR), local_files_only=True,
                torch_dtype=torch.float16, use_safetensors=True, low_cpu_mem_usage=True,
            )
        elif engine == SDXL_ENGINE:
            pipeline = StableDiffusionXLPipeline.from_pretrained(
                str(MODEL_DIR), torch_dtype=torch.float16, variant="fp16",
                use_safetensors=True, local_files_only=True,
            )
        else:
            raise RuntimeError("motore grafico non riconosciuto")
        pipeline.to("cuda")
        pipeline.vae.enable_slicing()
        pipeline.vae.enable_tiling()
        torch.cuda.synchronize()
        return pipeline, time.perf_counter() - started

    def _load_pipeline(self, engine: str) -> float:
        self._acquire_gpu_lock()
        try:
            self._wait_for_text_inference()
            self.previous_model = self._read_active_model()
            with self.lock:
                self.state = "loading"
                if self.active_job:
                    self.jobs[self.active_job]["state"] = "loading"
                self._persist()
            self._stop_text_models()

            pipeline, duration = self._construct_pipeline(engine)
            with self.lock:
                self.pipeline = pipeline
                self.loaded_engine = engine
                self.last_load_seconds = round(duration, 3)
                self.warm_until = time.time() + WARM_TTL_SECONDS
                self._persist()
            return duration
        except Exception:
            self._release_pipeline("load_failed", force=True)
            raise

    def _switch_pipeline(self, engine: str) -> float:
        with self.lock:
            old_pipeline = self.pipeline
            self.pipeline = None
            self.loaded_engine = None
            self.state = "loading"
            if self.active_job:
                self.jobs[self.active_job]["state"] = "loading"
            self._persist()
        if old_pipeline is not None:
            del old_pipeline
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
            pipeline, duration = self._construct_pipeline(engine)
            with self.lock:
                self.pipeline = pipeline
                self.loaded_engine = engine
                self.last_load_seconds = round(duration, 3)
                self.warm_until = time.time() + WARM_TTL_SECONDS
                self._persist()
            return duration
        except Exception:
            self._release_pipeline("engine_switch_failed", force=True)
            raise

    def _release_pipeline(self, reason: str, force: bool = False) -> None:
        with self.release_lock:
            with self.lock:
                if self.active_job and not force:
                    return
                had_pipeline = self.pipeline is not None or self.gpu_lock_handle is not None
                self.state = "releasing" if had_pipeline else "cold"
                pipeline = self.pipeline
                self.pipeline = None
                self.loaded_engine = None
                self.warm_until = 0
            if pipeline is not None:
                del pipeline
            if had_pipeline:
                gc.collect()
                try:
                    import torch
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()
                except Exception:
                    pass
            if had_pipeline:
                self._restore_text_model(reason)
            self._release_gpu_lock()
            with self.lock:
                self.state = "cold"
                self._persist()

    def _watchdog_loop(self) -> None:
        while not self.stop_event.wait(2):
            with self.lock:
                should_release = (
                    self.pipeline is not None
                    and self.active_job is None
                    and self.pending.empty()
                    and self.warm_until > 0
                    and time.time() >= self.warm_until
                )
            if should_release:
                self._release_pipeline("warm_timeout")

    def _wait_for_text_inference(self) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            request = urllib.request.Request(
                ORCHESTRATOR_STATUS, headers={"X-Internal-Key": INTERNAL_KEY}
            )
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    payload = json.load(response)
                if not payload.get("inference_busy", False):
                    return
            except (OSError, ValueError, urllib.error.URLError):
                pass
            time.sleep(1)
        raise RuntimeError("chat ancora occupata dopo 180 secondi")

    def _stop_text_models(self) -> None:
        for spec in TEXT_MODELS.values():
            subprocess.run(["systemctl", "stop", spec["service"]], check=True, timeout=90)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            active = [
                spec["service"] for spec in TEXT_MODELS.values()
                if subprocess.run(
                    ["systemctl", "is-active", "--quiet", spec["service"]],
                    check=False, timeout=10,
                ).returncode == 0
            ]
            if not active:
                return
            time.sleep(1)
        raise RuntimeError(f"modelli testuali ancora attivi: {', '.join(active)}")

    def _acquire_gpu_lock(self) -> None:
        handle = GPU_LOCK_PATH.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError("GPU occupata da un cambio modello")
        self.gpu_lock_handle = handle

    def _release_gpu_lock(self) -> None:
        handle = self.gpu_lock_handle
        self.gpu_lock_handle = None
        if handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def _read_active_model(self) -> str:
        try:
            model = str(json.loads(MODEL_STATE_PATH.read_text(encoding="utf-8")).get("active_model"))
            return model if model in TEXT_MODELS else "qwen3.6-35b-a3b-iq4xs"
        except (OSError, ValueError):
            return "qwen3.6-35b-a3b-iq4xs"

    def _restore_text_model(self, reason: str) -> None:
        target = self.previous_model if self.previous_model in TEXT_MODELS else "qwen3-8b"
        if not self._start_and_wait(target):
            # A failed experimental restore always returns to the qualified official default first.
            target = "qwen3.6-35b-a3b-iq4xs"
            if not self._start_and_wait(target):
                target = "qwen3-8b"
                if not self._start_and_wait(target):
                    self.last_error = "ripristino Qwen fallito"
                    return
            self._write_model_state(target, "graphics_fallback", reason)

    def _start_and_wait(self, model: str) -> bool:
        spec = TEXT_MODELS[model]
        try:
            subprocess.run(["systemctl", "start", spec["service"]], check=True, timeout=90)
        except (OSError, subprocess.SubprocessError):
            return False
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(spec["health"], timeout=3) as response:
                    if response.status == 200:
                        return True
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(1)
        return False

    def _write_model_state(self, model: str, result: str, reason: str) -> None:
        try:
            existing = json.loads(MODEL_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            existing = {}
        default_model = str(existing.get("default_model") or "qwen3.6-35b-a3b-iq4xs")
        if default_model not in TEXT_MODELS:
            default_model = "qwen3.6-35b-a3b-iq4xs"
        payload = {
            "schema": 2,
            "active_model": model,
            "default_model": default_model,
            "endpoint": TEXT_MODELS[model]["endpoint"],
            "updated_at": int(time.time()),
            "last_switch": {"result": result, "reason": reason, "at": int(time.time())},
        }
        self._atomic_json(MODEL_STATE_PATH, payload)

    def _load_persisted(self) -> None:
        try:
            payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            selected = str(payload.get("selected_engine") or SDXL_ENGINE)
            self.selected_engine = selected if selected in {item["id"] for item in engine_catalog()} else SDXL_ENGINE
            self.last_load_seconds = payload.get("last_load_seconds")
            self.last_generation_seconds = payload.get("last_generation_seconds")
            self.last_seconds_per_step = payload.get("last_seconds_per_step")
            for item in payload.get("jobs", []):
                path = Path(str(item.get("result_path") or ""))
                if item.get("state") == "ready" and path.is_file() and RESULTS_DIR in path.parents:
                    self.jobs[str(item["id"])] = item
        except (OSError, ValueError, TypeError):
            try:
                canary = json.loads(
                    (RESULTS_DIR / "canary" / "sdxl-p40-canary.json").read_text(encoding="utf-8")
                )
                self.last_load_seconds = canary.get("load_seconds")
                self.last_generation_seconds = canary.get("generation_seconds")
                self.last_seconds_per_step = canary.get("seconds_per_step")
            except (OSError, ValueError, TypeError):
                pass

    def _persist(self) -> None:
        jobs = sorted(self.jobs.values(), key=lambda item: item.get("created_at", 0), reverse=True)[:100]
        payload = {
            "schema": 2,
            "state": self.state,
            "selected_engine": self.selected_engine,
            "last_load_seconds": self.last_load_seconds,
            "last_generation_seconds": self.last_generation_seconds,
            "last_seconds_per_step": self.last_seconds_per_step,
            "updated_at": int(time.time()),
            "jobs": jobs,
        }
        self._atomic_json(STATE_PATH, payload)

    def _atomic_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            temporary = Path(handle.name)
        os.chmod(temporary, 0o640)
        try:
            os.chown(temporary, 0, grp.getgrnam(SETTINGS.runtime_group).gr_gid)
        except (KeyError, PermissionError):
            pass
        os.replace(temporary, path)

    def _cleanup_results(self) -> None:
        if not RESULTS_DIR.exists():
            return
        cutoff = time.time() - RESULT_RETENTION_SECONDS
        files = [path for path in RESULTS_DIR.rglob("*.png") if path.is_file() and "canary" not in path.parts]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        total = sum(path.stat().st_size for path in files)
        for index, path in enumerate(files):
            stat = path.stat()
            if stat.st_mtime < cutoff or index >= RESULT_MAX_FILES or total > RESULT_MAX_BYTES:
                total -= stat.st_size
                path.unlink(missing_ok=True)
        for directory in sorted((path for path in RESULTS_DIR.iterdir() if path.is_dir()), reverse=True):
            if directory.name != "canary":
                try:
                    directory.rmdir()
                except OSError:
                    pass


manager = GraphicsManager()


def require_key(value: str | None) -> None:
    if not INTERNAL_KEY or value is None or not secrets.compare_digest(value, INTERNAL_KEY):
        raise HTTPException(status_code=401, detail="servizio grafico non autorizzato")


@app.on_event("startup")
def startup() -> None:
    manager.start()


@app.on_event("shutdown")
def shutdown() -> None:
    manager.stop()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", **manager.status_payload()}


@app.get("/v1/graphics/status")
def graphics_status(
    x_internal_key: str | None = Header(default=None), admin: bool = Query(default=False)
) -> dict[str, Any]:
    require_key(x_internal_key)
    return manager.status_payload(admin=admin)


@app.post("/v1/graphics/jobs")
def create_job(request: JobRequest, x_internal_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_internal_key)
    return manager.submit(request)


@app.post("/v1/graphics/engine")
def select_engine(request: EngineSelection, x_internal_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_internal_key)
    return manager.select_engine(request.engine)


@app.get("/v1/graphics/jobs/{job_id}")
def get_job(
    job_id: str,
    owner: str = Query(default=""),
    admin: bool = Query(default=False),
    x_internal_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_key(x_internal_key)
    clean_owner = None if admin else manager.require_owner(owner)
    return manager.public_job(job_id, clean_owner, admin=admin)


@app.get("/v1/graphics/jobs/{job_id}/image")
def get_image(
    job_id: str,
    owner: str = Query(default=""),
    admin: bool = Query(default=False),
    x_internal_key: str | None = Header(default=None),
) -> FileResponse:
    require_key(x_internal_key)
    clean_owner = None if admin else manager.require_owner(owner)
    path = manager.result(job_id, clean_owner, admin=admin)
    return FileResponse(path, media_type="image/png", filename=f"r740-{job_id[:12]}.png")


@app.post("/v1/graphics/release")
def release(x_internal_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_internal_key)
    return manager.release_now()
