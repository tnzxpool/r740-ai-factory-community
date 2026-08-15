# SPDX-FileCopyrightText: 2026 R740 AI Factory contributors
# SPDX-License-Identifier: LGPL-3.0-or-later
"""Portable, fail-closed configuration for the Community portal."""

from __future__ import annotations

import ipaddress
import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit


APP_DIR = Path(__file__).resolve().parent


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise RuntimeError(f"{name} must be a boolean")


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def service_url(name: str) -> str:
    value = os.getenv(name, "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError(f"{name} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(f"{name} must not contain credentials, query or fragment")
    return value


def secret_value(env_name: str, file_env_name: str) -> str:
    """Read a secret file first; retain direct env support for compatibility."""
    file_name = os.getenv(file_env_name, "").strip()
    if file_name:
        path = Path(file_name)
        if not path.is_file():
            raise RuntimeError(f"{file_env_name} does not reference a regular file")
        value = path.read_text(encoding="utf-8").strip()
    else:
        value = os.getenv(env_name, "").strip()
    return value


def allowed_hosts() -> list[str]:
    raw = os.getenv("AI_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
    hosts = [item.strip() for item in raw.split(",") if item.strip()]
    if not hosts or "*" in hosts:
        raise RuntimeError("AI_ALLOWED_HOSTS must contain explicit hostnames")
    return hosts


def admin_network() -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    raw = os.getenv("AI_ADMIN_NETWORK", "127.0.0.0/8").strip()
    try:
        return ipaddress.ip_network(raw, strict=False)
    except ValueError as exc:
        raise RuntimeError("AI_ADMIN_NETWORK must be a valid CIDR") from exc


DB_PATH = Path(os.getenv("AI_PORTAL_DB", str(APP_DIR / "data" / "portal.db")))
CORE_URL = service_url("AI_CORE_URL")
PARSER_URL = service_url("AI_PARSER_URL")
TOOLS_URL = service_url("AI_TOOLS_URL")
SANDBOX_URL = service_url("AI_SANDBOX_URL")

PARSER_KEY_FILE = Path(os.getenv("AI_PARSER_KEY_FILE", str(APP_DIR / "secrets" / "parser.key")))
LOCAL_MCP_POLICY_KEY_FILE = Path(os.getenv(
    "AI_LOCAL_MCP_POLICY_KEY_FILE", str(APP_DIR / "secrets" / "local-mcp-policy-signing.key")
))
def setup_token_hash() -> str:
    token_file = os.getenv("AI_SETUP_TOKEN_FILE", "").strip()
    if token_file:
        path = Path(token_file)
        if not path.is_file():
            raise RuntimeError("AI_SETUP_TOKEN_FILE does not reference a regular file")
        token = path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise RuntimeError("AI_SETUP_TOKEN_FILE is too short")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
    value = os.getenv("AI_SETUP_TOKEN_HASH", "").strip()
    if value and (len(value) != 64 or any(character not in "0123456789abcdef" for character in value.lower())):
        raise RuntimeError("AI_SETUP_TOKEN_HASH must be a SHA-256 hex digest")
    return value.lower()


SETUP_TOKEN_HASH = setup_token_hash()
CORE_KEY = secret_value("AI_PORTAL_CORE_KEY", "AI_PORTAL_CORE_KEY_FILE")
TOOLS_TOKEN = secret_value("AI_TOOLS_TOKEN", "AI_TOOLS_TOKEN_FILE")
SANDBOX_TOKEN = secret_value("AI_SANDBOX_TOKEN", "AI_SANDBOX_TOKEN_FILE")

ALLOWED_HOSTS = allowed_hosts()
ADMIN_NETWORK = admin_network()
AUTOROUTING_UI_ENABLED = env_bool("AI_AUTOROUTING_UI_ENABLED", False)
SESSION_HOURS = env_int("AI_SESSION_HOURS", 8, 1, 168)

# Demo access is absent by default. Enabling it requires a local password file.
DEMO_GUEST_ENABLED = env_bool("AI_DEMO_GUEST_ENABLED", False)
DEMO_GUEST_USERNAME = os.getenv("AI_DEMO_GUEST_USERNAME", "guest").strip() or "guest"
DEMO_GUEST_PASSWORD_FILE = Path(os.getenv(
    "AI_DEMO_GUEST_PASSWORD_FILE", str(APP_DIR / "secrets" / "demo-guest-password")
))
