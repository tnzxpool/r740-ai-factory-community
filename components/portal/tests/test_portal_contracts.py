# SPDX-FileCopyrightText: 2026 R740 AI Factory contributors
# SPDX-License-Identifier: LGPL-3.0-or-later

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for name in (
    "AI_CORE_URL", "AI_PORTAL_CORE_KEY", "AI_PORTAL_CORE_KEY_FILE",
    "AI_TOOLS_URL", "AI_TOOLS_TOKEN", "AI_TOOLS_TOKEN_FILE",
    "AI_SANDBOX_URL", "AI_SANDBOX_TOKEN", "AI_SANDBOX_TOKEN_FILE",
):
    os.environ[name] = ""
os.environ["AI_ALLOWED_HOSTS"] = "localhost,127.0.0.1,testserver"
os.environ["AI_DEMO_GUEST_ENABLED"] = "0"

from r740_portal import portal  # noqa: E402


def request() -> Request:
    return Request({
        "type": "http", "method": "GET", "scheme": "https", "path": "/",
        "headers": [], "query_string": b"", "server": ("testserver", 443),
        "client": ("127.0.0.1", 50000),
    })


def control_payload() -> dict:
    return {
        "models": {
            "general": {"available": True, "installed": True, "kind": "chat", "capabilities": ["text"]},
            "vision": {"available": True, "installed": True, "kind": "chat", "capabilities": ["text", "vision"]},
            "uncensored": {"available": True, "installed": True, "kind": "chat", "capabilities": ["text"]},
            "missing": {"available": True, "installed": False, "kind": "chat", "capabilities": ["text"]},
            "gated": {"available": True, "installed": True, "kind": "chat", "capabilities": ["text"]},
            "graphics": {"available": True, "installed": True, "kind": "graphics", "capabilities": ["image-generation"]},
        },
        "catalog": {
            "general": {"catalog_state": "qualified_local"},
            "vision": {"catalog_state": "qualified_local"},
            "uncensored": {"catalog_state": "qualified_local"},
            "missing": {"catalog_state": "qualified_local"},
            "gated": {"catalog_state": "runtime_gated"},
            "graphics": {"catalog_state": "qualified_local"},
        },
    }


def test_catalog_capabilities_and_fifo_are_preserved(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(portal, "DB_PATH", tmp_path / "portal.db")
    portal.init_db()
    with portal.db() as connection:
        connection.executemany(
            """INSERT INTO users(id,username,password_hash,role,active,must_change,created_at)
               VALUES(?,?,?,?,1,0,1)""",
            [(1, "guest", "unused", "tester-tool"), (2, "alice", "unused", "tester-base")],
        )
        connection.execute(
            "INSERT INTO user_models(user_id,model_id,enabled,updated_at) VALUES(2,'general',1,1)"
        )

    assert "sandbox" not in portal.configured_caps({"id": 1, "username": "guest", "role": "tester-tool"})
    assert "local-mcp" not in portal.configured_caps({"id": 1, "username": "guest", "role": "tester-tool"})

    async def fake_control(_path: str) -> dict:
        return control_payload()

    monkeypatch.setattr(portal, "core_admin_get", fake_control)
    _, guest_models = asyncio.run(portal.authorized_live_models({
        "id": 1, "username": "guest", "role": "tester-tool",
    }))
    _, user_models = asyncio.run(portal.authorized_live_models({
        "id": 2, "username": "alice", "role": "tester-base",
    }))
    assert set(guest_models) == {"general", "vision", "uncensored"}
    assert set(user_models) == {"general"}

    first = portal.enqueue_inference("chat", {"id": 1, "username": "guest"}, request(), "r1")
    second = portal.enqueue_inference("chat", {"id": 2, "username": "alice"}, request(), "r2")
    assert first["position"] == 1
    assert second["position"] == 2
    with pytest.raises(HTTPException) as duplicate:
        portal.enqueue_inference("vision", {"id": 2, "username": "alice"}, request(), "r3")
    assert duplicate.value.status_code == 409


def test_graphics_projection_and_compact_ui_contract() -> None:
    projected = portal.graphics_status_for_user({
        "engines": [
            {"id": "sdxl-1.0-fp16", "display_name": "SDXL", "qualified": True, "path": "/hidden"},
            {"id": "realvisxl-v5", "display_name": "RealVis", "qualified": True},
            {"id": "future", "display_name": "Future", "qualified": True},
            {"id": "broken", "display_name": "Broken", "qualified": False},
        ]
    }, {"role": "tester-base"})
    assert [item["id"] for item in projected["engines"]] == ["sdxl-1.0-fp16", "realvisxl-v5"]
    assert all("path" not in item for item in projected["engines"])

    html = (ROOT / "src" / "r740_portal" / "index.html").read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    assert 'id="userModelChoice"' in html
    assert 'id="graphicsEngine"' in html
    assert 'id="applyGraphicsEngine"' in html
    assert "UNCENSORED" in html and "uncensored-option" in html
    assert "position:sticky" in html and "position:fixed" in html
    assert "fetch('/api/graphics/engine'" in html
    assert "fetch('/api/models/load'" in html
    assert "location.href='/admin'" in html
    assert "innerHTML" not in html and "eval(" not in html and "new Function" not in html


def test_unconfigured_services_are_not_advertised() -> None:
    assert portal.CORE_CONFIGURED is False
    assert "chat" not in portal.AVAILABLE_FEATURES
    assert "image-generation" not in portal.AVAILABLE_FEATURES
    assert "web-search" not in portal.AVAILABLE_FEATURES
    assert "sandbox" not in portal.AVAILABLE_FEATURES


def test_initial_schema_migration_is_executable() -> None:
    sql = (ROOT / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(sql)
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        connection.close()
    assert {
        "users", "sessions", "user_capabilities", "user_models",
        "schema_migrations", "inference_lock", "inference_queue",
        "graphics_requests", "documents", "local_mcp_devices",
    } <= tables


@pytest.mark.parametrize("name", [
    "index.html", "admin.html", "login.html", "change-password.html", "setup.html",
])
def test_inline_javascript_parses(name: str, tmp_path: Path) -> None:
    html = (ROOT / "src" / "r740_portal" / name).read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE)
    assert scripts, name
    script = tmp_path / (name + ".js")
    script.write_text("\n".join(scripts), encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(script)], text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
