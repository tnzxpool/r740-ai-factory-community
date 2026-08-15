# SPDX-License-Identifier: LGPL-3.0-or-later
"""Loopback-only autorouting service. Execution defaults OFF."""

from __future__ import annotations

import json
import secrets
import threading
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .adapters import LoopbackJSONTransport, ModelControllerAdapter, RunnerDispatcher
from .autorouting import ExecutionError, RoutingError, execute_plan, plan_workflow
from .config import SETTINGS


INTERNAL_KEY = SETTINGS.internal_key
BACKEND_KEY = SETTINGS.backend_key
EXECUTION_ENABLED = SETTINGS.execution_enabled
REGISTRY_PATH = SETTINGS.registry_path
MAX_REQUEST_BYTES = 16 * 1024 * 1024
SERVICE_LOCK = threading.Lock()

app = FastAPI(title="R740 Local Autorouting", version="0.1.0", docs_url=None, redoc_url=None)


def require_key(value: str | None) -> None:
    if not INTERNAL_KEY or value is None or not secrets.compare_digest(value, INTERNAL_KEY):
        raise HTTPException(status_code=401, detail="autorouting non autorizzato")


def registry() -> dict[str, Any]:
    try:
        value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="registry autorouting non disponibile") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail="registry autorouting non valido")
    return value


async def body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="workflow oltre il limite")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="workflow JSON non valido") from exc
    if not isinstance(value, dict) or set(value) != {"profile", "tasks", "payloads"}:
        raise HTTPException(status_code=400, detail="campi workflow non validi")
    if not isinstance(value["payloads"], dict):
        raise HTTPException(status_code=400, detail="payload task non validi")
    return value


def components():
    transport = LoopbackJSONTransport()
    controller = ModelControllerAdapter(transport, INTERNAL_KEY)
    return transport, controller


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "execution_enabled": EXECUTION_ENABLED,
        "busy": SERVICE_LOCK.locked(),
        "privacy": "local_only",
    }


@app.post("/internal/routing/plan")
async def plan(request: Request, x_internal_key: str | None = Header(default=None)) -> JSONResponse:
    require_key(x_internal_key)
    value = await body(request)
    try:
        _, controller = components()
        result = plan_workflow(
            registry(), controller.status(), str(value["profile"]), value["tasks"],
            require_execution=False,
        )
    except (RoutingError, ExecutionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JSONResponse(result)


@app.post("/internal/routing/execute")
async def execute(request: Request, x_internal_key: str | None = Header(default=None)) -> JSONResponse:
    require_key(x_internal_key)
    if not EXECUTION_ENABLED:
        raise HTTPException(status_code=409, detail="autorouting live disabilitato")
    value = await body(request)
    if set(map(str, value["payloads"])) != {str(task.get("id", "")) for task in value["tasks"] if isinstance(task, dict)}:
        raise HTTPException(status_code=400, detail="ogni task deve avere un solo payload")
    if not SERVICE_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="motore occupato da un altro workflow")
    try:
        transport, controller = components()
        current = controller.status()
        route = plan_workflow(
            registry(), current, str(value["profile"]), value["tasks"],
            require_execution=True,
        )
        dispatcher = RunnerDispatcher(
            transport, INTERNAL_KEY, BACKEND_KEY, value["tasks"], value["payloads"]
        )
        result = execute_plan(route, controller, dispatcher)
        result["plan"] = {key: route[key] for key in ("profile", "groups", "switch_count", "privacy")}
        return JSONResponse(result)
    except (RoutingError, ExecutionError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        SERVICE_LOCK.release()

