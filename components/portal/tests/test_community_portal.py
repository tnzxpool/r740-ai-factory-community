# SPDX-FileCopyrightText: 2026 R740 AI Factory contributors
# SPDX-License-Identifier: LGPL-3.0-or-later

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TEST_DEPS = os.environ.get("R740_TEST_DEPS", "")


def run_probe(code: str, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(extra_env)
    python_paths = [str(SRC)]
    if TEST_DEPS:
        python_paths.append(TEST_DEPS)
    if env.get("PYTHONPATH"):
        python_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(python_paths)
    for name in (
        "AI_CORE_URL", "AI_PORTAL_CORE_KEY", "AI_PORTAL_CORE_KEY_FILE",
        "AI_PARSER_URL", "AI_TOOLS_URL", "AI_TOOLS_TOKEN", "AI_TOOLS_TOKEN_FILE",
        "AI_SANDBOX_URL", "AI_SANDBOX_TOKEN", "AI_SANDBOX_TOKEN_FILE",
    ):
        if name not in extra_env:
            env[name] = ""
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        text=True, capture_output=True, timeout=90, check=False,
    )


def test_demo_disabled_and_backend_fail_closed(tmp_path: Path) -> None:
    code = r'''
from fastapi.testclient import TestClient
from r740_portal import portal
with TestClient(portal.app, base_url="https://testserver", client=("127.0.0.1", 50000)) as client:
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["backend_configured"] is False
    public = client.get("/api/public-config").json()["demo_access"]
    assert public == {"enabled": False, "username": None}
with portal.db() as connection:
    assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
print("PASS_DISABLED")
'''
    result = run_probe(code, {
        "AI_PORTAL_DB": str(tmp_path / "disabled.db"),
        "AI_ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
        "AI_ADMIN_NETWORK": "127.0.0.0/8",
        "AI_DEMO_GUEST_ENABLED": "0",
    })
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("PASS_DISABLED")


def test_demo_opt_in_hashes_password_and_records_migration(tmp_path: Path) -> None:
    password = secrets.token_urlsafe(24)
    password_file = tmp_path / "demo-password"
    password_file.write_text(password, encoding="utf-8")
    code = r'''
import os
from fastapi.testclient import TestClient
from argon2 import PasswordHasher
from r740_portal import portal
password = open(os.environ["AI_DEMO_GUEST_PASSWORD_FILE"], encoding="utf-8").read().strip()
with TestClient(portal.app, base_url="https://testserver", client=("127.0.0.1", 50000)) as client:
    public = client.get("/api/public-config").json()["demo_access"]
    assert public == {"enabled": True, "username": "guest"}
    response = client.post("/api/auth/login", json={"username": "guest", "password": password})
    assert response.status_code == 200
    backend_status = client.get("/api/status").status_code
    assert backend_status == 503, backend_status
with portal.db() as connection:
    row = connection.execute("SELECT password_hash FROM users WHERE username='guest'").fetchone()
    assert row is not None and row[0] != password
    assert PasswordHasher().verify(row[0], password)
    assert connection.execute(
        "SELECT 1 FROM schema_migrations WHERE name=?", (portal.COMMUNITY_DEMO_MIGRATION,)
    ).fetchone()
print("PASS_OPT_IN")
'''
    result = run_probe(code, {
        "AI_PORTAL_DB": str(tmp_path / "enabled.db"),
        "AI_ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
        "AI_ADMIN_NETWORK": "127.0.0.0/8",
        "AI_DEMO_GUEST_ENABLED": "1",
        "AI_DEMO_GUEST_USERNAME": "guest",
        "AI_DEMO_GUEST_PASSWORD_FILE": str(password_file),
    })
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("PASS_OPT_IN")
    assert password not in result.stdout + result.stderr


def test_setup_token_file_is_hashed_without_exposing_value(tmp_path: Path) -> None:
    token = secrets.token_urlsafe(48)
    token_file = tmp_path / "setup-token"
    token_file.write_text(token + "\n", encoding="utf-8")
    code = r'''
import hashlib
import os
from r740_portal import community_config
token = open(os.environ["AI_SETUP_TOKEN_FILE"], encoding="utf-8").read().strip()
assert community_config.SETUP_TOKEN_HASH == hashlib.sha256(token.encode()).hexdigest()
assert token not in repr(vars(community_config))
print("PASS_SETUP_FILE")
'''
    result = run_probe(code, {
        "AI_SETUP_TOKEN_FILE": str(token_file),
        "AI_SETUP_TOKEN_HASH": "",
        "AI_PORTAL_DB": str(tmp_path / "setup.db"),
    })
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("PASS_SETUP_FILE")
    assert token not in result.stdout + result.stderr


def test_configuration_rejects_wildcard_host(tmp_path: Path) -> None:
    result = run_probe("import r740_portal.community_config", {
        "AI_PORTAL_DB": str(tmp_path / "invalid.db"),
        "AI_ALLOWED_HOSTS": "*",
        "AI_DEMO_GUEST_ENABLED": "0",
    })
    assert result.returncode != 0
    assert "explicit hostnames" in result.stderr
