# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
from pathlib import Path
import secrets

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import SETTINGS


ORCHESTRATOR_URL = SETTINGS.orchestrator_url
AUTOROUTING_URL = SETTINGS.autorouting_url
GRAPHICS_MANAGER_URL = SETTINGS.graphics_manager_url
INTERNAL_KEY = SETTINGS.internal_key
PORTAL_KEY = SETTINGS.portal_key
ALLOWED_CLIENTS = SETTINGS.allowed_clients
UI_FILE = Path(__file__).with_name("index.html")
MAX_REQUEST_BYTES = 1024 * 1024
MAX_OCR_REQUEST_BYTES = 900 * 1024

app = FastAPI(title="R740 AI Factory", version="1.0.0", docs_url=None, redoc_url=None)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=list(SETTINGS.trusted_hosts),
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    peer = request.client.host if request.client else ""
    if peer not in ALLOWED_CLIENTS:
        return JSONResponse({"detail": "gateway disponibile solo tramite il portale protetto"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
    )
    return response


def internal_headers() -> dict[str, str]:
    return {"X-Internal-Key": INTERNAL_KEY}


def require_portal_key(value: str | None) -> None:
    if not PORTAL_KEY or value is None or not secrets.compare_digest(value, PORTAL_KEY):
        raise HTTPException(status_code=401, detail="accesso portale non autorizzato")


@app.get("/")
async def home() -> FileResponse:
    return FileResponse(UI_FILE, media_type="text/html")


@app.get("/health")
async def health() -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            response = await client.get(f"{ORCHESTRATOR_URL}/health")
        payload = response.json()
        return JSONResponse(
            {"status": "ok" if response.status_code == 200 else "degraded", "orchestrator": payload},
            status_code=200 if response.status_code == 200 else 503,
        )
    except (httpx.HTTPError, ValueError):
        return JSONResponse({"status": "degraded", "orchestrator": {"ready": False}}, status_code=503)


@app.get("/api/status")
async def status() -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(f"{ORCHESTRATOR_URL}/status", headers=internal_headers())
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="orchestratore non disponibile")


@app.get("/v1/models")
async def models() -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{ORCHESTRATOR_URL}/v1/models", headers=internal_headers())
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="orchestratore non disponibile")


@app.post("/internal/v1/embeddings")
async def embeddings(request: Request, x_portal_key: str | None = Header(default=None)) -> JSONResponse:
    require_portal_key(x_portal_key)
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="richiesta troppo grande")
    try:
        async with httpx.AsyncClient(timeout=95.0) as client:
            response = await client.post(
                f"{ORCHESTRATOR_URL}/v1/embeddings",
                content=body,
                headers={**internal_headers(), "Content-Type": "application/json"},
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="embedding non disponibile")


@app.post("/internal/v1/ocr/extract")
async def ocr_extract(request: Request, x_portal_key: str | None = Header(default=None)) -> JSONResponse:
    require_portal_key(x_portal_key)
    body = await request.body()
    if len(body) > MAX_OCR_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="richiesta OCR oltre il limite")
    try:
        async with httpx.AsyncClient(timeout=1230.0) as client:
            response = await client.post(
                f"{ORCHESTRATOR_URL}/internal/v1/ocr/extract",
                content=body,
                headers={**internal_headers(), "Content-Type": "application/json"},
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="OCR interno non disponibile")


@app.get("/internal/admin/models")
async def admin_models(x_portal_key: str | None = Header(default=None)) -> JSONResponse:
    require_portal_key(x_portal_key)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{ORCHESTRATOR_URL}/internal/admin/models", headers=internal_headers()
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="controller modelli non disponibile")


@app.post("/internal/admin/models/switch")
async def admin_model_switch(
    request: Request, x_portal_key: str | None = Header(default=None)
) -> JSONResponse:
    require_portal_key(x_portal_key)
    body = await request.body()
    if len(body) > 4096:
        raise HTTPException(status_code=413, detail="richiesta troppo grande")
    try:
        async with httpx.AsyncClient(timeout=310.0) as client:
            response = await client.post(
                f"{ORCHESTRATOR_URL}/internal/admin/models/switch",
                content=body,
                headers={**internal_headers(), "Content-Type": "application/json"},
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="cambio modello non disponibile")


@app.post("/internal/admin/routing/simulate")
async def admin_routing_simulate(
    request: Request, x_portal_key: str | None = Header(default=None)
) -> JSONResponse:
    require_portal_key(x_portal_key)
    body = await request.body()
    if len(body) > 32768:
        raise HTTPException(status_code=413, detail="richiesta routing troppo grande")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{ORCHESTRATOR_URL}/internal/admin/routing/simulate",
                content=body,
                headers={**internal_headers(), "Content-Type": "application/json"},
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="simulazione routing non disponibile")


@app.post("/internal/routing/{action}")
async def autorouting_proxy(
    action: str, request: Request, x_portal_key: str | None = Header(default=None)
) -> JSONResponse:
    require_portal_key(x_portal_key)
    if action not in {"plan", "execute"}:
        raise HTTPException(status_code=404, detail="azione routing sconosciuta")
    body = await request.body()
    if not body or len(body) > 16 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="workflow oltre il limite")
    try:
        async with httpx.AsyncClient(timeout=1800.0) as client:
            response = await client.post(
                f"{AUTOROUTING_URL}/internal/routing/{action}", content=body,
                headers={"X-Internal-Key": INTERNAL_KEY, "Content-Type": "application/json"},
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="autorouting locale non disponibile")


@app.get("/internal/graphics/status")
async def graphics_status(
    x_portal_key: str | None = Header(default=None), admin: bool = False
) -> JSONResponse:
    require_portal_key(x_portal_key)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"{GRAPHICS_MANAGER_URL}/v1/graphics/status",
                params={"admin": str(admin).lower()},
                headers=internal_headers(),
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="servizio grafico non disponibile")


@app.post("/internal/graphics/jobs")
async def graphics_create_job(
    request: Request, x_portal_key: str | None = Header(default=None)
) -> JSONResponse:
    require_portal_key(x_portal_key)
    body = await request.body()
    if len(body) > 8192:
        raise HTTPException(status_code=413, detail="richiesta grafica troppo grande")
    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            response = await client.post(
                f"{GRAPHICS_MANAGER_URL}/v1/graphics/jobs",
                content=body,
                headers={**internal_headers(), "Content-Type": "application/json"},
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="coda grafica non disponibile")


@app.post("/internal/graphics/engine")
async def graphics_select_engine(
    request: Request, x_portal_key: str | None = Header(default=None)
) -> JSONResponse:
    require_portal_key(x_portal_key)
    body = await request.body()
    if len(body) > 512:
        raise HTTPException(status_code=413, detail="selezione grafica troppo grande")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{GRAPHICS_MANAGER_URL}/v1/graphics/engine",
                content=body,
                headers={**internal_headers(), "Content-Type": "application/json"},
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="selezione grafica non disponibile")


@app.get("/internal/graphics/jobs/{job_id}")
async def graphics_get_job(
    job_id: str,
    owner: str,
    admin: bool = False,
    x_portal_key: str | None = Header(default=None),
) -> JSONResponse:
    require_portal_key(x_portal_key)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"{GRAPHICS_MANAGER_URL}/v1/graphics/jobs/{job_id}",
                params={"owner": owner, "admin": str(admin).lower()},
                headers=internal_headers(),
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="stato immagine non disponibile")


@app.get("/internal/graphics/jobs/{job_id}/image")
async def graphics_get_image(
    job_id: str,
    owner: str,
    admin: bool = False,
    x_portal_key: str | None = Header(default=None),
):
    require_portal_key(x_portal_key)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{GRAPHICS_MANAGER_URL}/v1/graphics/jobs/{job_id}/image",
                params={"owner": owner, "admin": str(admin).lower()},
                headers=internal_headers(),
            )
        if response.status_code != 200:
            try:
                detail = response.json()
            except ValueError:
                detail = {"detail": "immagine non disponibile"}
            return JSONResponse(detail, status_code=response.status_code)
        return StreamingResponse(
            iter([response.content]),
            media_type="image/png",
            headers={
                "Content-Disposition": f'inline; filename="r740-{job_id[:12]}.png"',
                "Cache-Control": "private, max-age=3600",
            },
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="immagine non disponibile")


@app.post("/internal/graphics/release")
async def graphics_release(x_portal_key: str | None = Header(default=None)) -> JSONResponse:
    require_portal_key(x_portal_key)
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{GRAPHICS_MANAGER_URL}/v1/graphics/release", headers=internal_headers()
            )
        return JSONResponse(response.json(), status_code=response.status_code)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="rilascio GPU non disponibile")


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="richiesta troppo grande")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON non valido")

    headers = {**internal_headers(), "Content-Type": "application/json"}
    if payload.get("stream"):
        async def stream_orchestrator():
            try:
                async with httpx.AsyncClient(timeout=None) as client:
                    async with client.stream(
                        "POST", f"{ORCHESTRATOR_URL}/v1/chat/completions", content=body, headers=headers
                    ) as response:
                        async for chunk in response.aiter_bytes():
                            yield chunk
            except httpx.HTTPError:
                yield b'{"error":{"message":"orchestratore non disponibile"}}'

        return StreamingResponse(stream_orchestrator(), media_type="text/event-stream")

    try:
        async with httpx.AsyncClient(timeout=190.0) as client:
            response = await client.post(
                f"{ORCHESTRATOR_URL}/v1/chat/completions", content=body, headers=headers
            )
        try:
            content = response.json()
        except ValueError:
            content = {"error": {"message": "risposta orchestratore non valida"}}
        return JSONResponse(content, status_code=response.status_code)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="orchestratore non disponibile")

