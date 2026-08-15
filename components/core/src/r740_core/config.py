# SPDX-License-Identifier: LGPL-3.0-or-later
"""Typed, fail-closed environment configuration for the community core."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


class ConfigError(RuntimeError):
    """Raised before service startup when configuration is unsafe or malformed."""


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


def env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


def env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name, default.as_posix())
    value = Path(raw)
    # POSIX deployment paths remain testable from a Windows source workstation.
    is_absolute = value.is_absolute() or raw.startswith("/")
    if not is_absolute or ".." in value.parts:
        raise ConfigError(f"{name} must be an absolute normalized path")
    return value


def env_loopback_url(name: str, default: str) -> str:
    value = os.getenv(name, default).rstrip("/")
    parsed = urlsplit(value)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
    except ValueError as exc:
        raise ConfigError(f"{name} must use a literal loopback address") from exc
    if parsed.scheme != "http" or str(address) != "127.0.0.1" or parsed.username or parsed.password:
        raise ConfigError(f"{name} must use unauthenticated HTTP on 127.0.0.1")
    if parsed.path or parsed.query or parsed.fragment or parsed.port is None:
        raise ConfigError(f"{name} must contain only scheme, loopback host and port")
    return value


def env_ip_set(name: str, default: str) -> frozenset[str]:
    values = [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]
    if not values:
        raise ConfigError(f"{name} cannot be empty")
    try:
        return frozenset(str(ipaddress.ip_address(item)) for item in values)
    except ValueError as exc:
        raise ConfigError(f"{name} must contain only literal IP addresses") from exc


def env_hosts(name: str, default: str) -> tuple[str, ...]:
    values = tuple(item.strip().lower() for item in os.getenv(name, default).split(",") if item.strip())
    if not values or any(not re.fullmatch(r"[a-z0-9.:-]+", item) for item in values):
        raise ConfigError(f"{name} contains an invalid host")
    return values


def env_group(name: str = "AI_RUNTIME_GROUP", default: str = "r740-ai") -> str:
    value = os.getenv(name, default)
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value):
        raise ConfigError(f"{name} is not a portable system group")
    return value


def env_json_object(name: str, default: dict[str, str]) -> dict[str, str]:
    raw = os.getenv(name)
    if raw is None:
        return dict(default)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{name} must be a JSON object") from exc
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ConfigError(f"{name} must map strings to strings")
    return value


def secret_value(env_name: str, file_env_name: str) -> str:
    file_name = os.getenv(file_env_name, "").strip()
    if file_name:
        path = Path(file_name)
        if not path.is_file() or path.is_symlink():
            raise ConfigError(f"{file_env_name} must reference a regular non-symlink file")
        value = path.read_text(encoding="utf-8").strip()
    else:
        value = os.getenv(env_name, "").strip()
    if value and len(value) < 32:
        raise ConfigError(f"{env_name} must contain at least 32 characters")
    return value


def env_service_map(name: str, default: dict[str, str]) -> dict[str, str]:
    value = env_json_object(name, default)
    if set(value) != set(default):
        raise ConfigError(f"{name} must define exactly the supported model ids")
    if any(not re.fullmatch(r"[A-Za-z0-9_.@-]+\.service", unit) for unit in value.values()):
        raise ConfigError(f"{name} contains an invalid systemd unit")
    return value


@dataclass(frozen=True)
class CoreSettings:
    state_dir: Path
    runtime_dir: Path
    models_dir: Path
    downloads_dir: Path
    results_dir: Path
    metrics_dir: Path
    libexec_dir: Path
    registry_path: Path
    model_state_path: Path
    graphics_state_path: Path
    gpu_lock_path: Path
    workflow_lock_path: Path
    internal_key: str
    backend_key: str
    portal_key: str
    runtime_group: str
    execution_enabled: bool
    graphics_warm_ttl: int
    graphics_max_queue: int
    allowed_clients: frozenset[str]
    trusted_hosts: tuple[str, ...]
    backend_url: str
    embedding_url: str
    model_manager_url: str
    orchestrator_url: str
    graphics_manager_url: str
    autorouting_url: str
    model_endpoints: dict[str, str]

    @classmethod
    def from_env(cls) -> "CoreSettings":
        state = env_path("AI_STATE_DIR", Path("/var/lib/r740-ai-factory"))
        runtime = env_path("AI_RUNTIME_DIR", Path("/run/r740-ai-factory"))
        models = env_path("AI_MODELS_DIR", state / "models")
        downloads = env_path("AI_DOWNLOADS_DIR", state / "downloads")
        results = env_path("AI_RESULTS_DIR", state / "results")
        metrics = env_path("AI_METRICS_DIR", state / "metrics")
        libexec = env_path("AI_LIBEXEC_DIR", Path("/usr/libexec/r740-ai-factory"))
        backend = env_loopback_url("AI_BACKEND_URL", "http://127.0.0.1:41140")
        endpoints = {
            "qwen3-8b": backend,
            "qwen3.6-35b-a3b-iq4xs": env_loopback_url("AI_QWEN36_URL", "http://127.0.0.1:41151"),
            "qwen3.6-35b-a3b-heretic-iq4xs": env_loopback_url("AI_QWEN36_HERETIC_URL", "http://127.0.0.1:41154"),
            "qwen3-vl-8b": env_loopback_url("AI_QWEN3VL_URL", "http://127.0.0.1:41147"),
            "glm-4.7-flash": env_loopback_url("AI_GLM47_URL", "http://127.0.0.1:41150"),
            "glm-ocr-q8": env_loopback_url("AI_GLM_OCR_URL", "http://127.0.0.1:41153"),
        }
        return cls(
            state_dir=state,
            runtime_dir=runtime,
            models_dir=models,
            downloads_dir=downloads,
            results_dir=results,
            metrics_dir=metrics,
            libexec_dir=libexec,
            registry_path=env_path("AI_CAPABILITIES_FILE", state / "registry" / "capabilities.json"),
            model_state_path=env_path("AI_MODEL_STATE_FILE", state / "registry" / "model_state.json"),
            graphics_state_path=env_path("AI_GRAPHICS_STATE_FILE", state / "registry" / "graphics_state.json"),
            gpu_lock_path=env_path("AI_GPU_LOCK_FILE", runtime / "gpu.lock"),
            workflow_lock_path=env_path("AI_WORKFLOW_LOCK_FILE", runtime / "workflow.lock"),
            internal_key=secret_value("AI_ORCHESTRATOR_KEY", "AI_ORCHESTRATOR_KEY_FILE"),
            backend_key=secret_value("AI_BACKEND_KEY", "AI_BACKEND_KEY_FILE"),
            portal_key=secret_value("AI_PORTAL_CORE_KEY", "AI_PORTAL_CORE_KEY_FILE"),
            runtime_group=env_group(),
            execution_enabled=env_bool("AI_AUTOROUTING_LIVE_ENABLED", False),
            graphics_warm_ttl=env_int("AI_GRAPHICS_WARM_TTL", 600, minimum=60, maximum=86400),
            graphics_max_queue=env_int("AI_GRAPHICS_MAX_QUEUE", 8, minimum=1, maximum=128),
            allowed_clients=env_ip_set("AI_GATEWAY_ALLOWED_CLIENTS", "127.0.0.1,::1"),
            trusted_hosts=env_hosts("AI_GATEWAY_TRUSTED_HOSTS", "127.0.0.1,localhost,ai-core"),
            backend_url=backend,
            embedding_url=env_loopback_url("AI_EMBEDDING_URL", "http://127.0.0.1:41143"),
            model_manager_url=env_loopback_url("AI_MODEL_MANAGER_URL", "http://127.0.0.1:41146"),
            orchestrator_url=env_loopback_url("AI_ORCHESTRATOR_URL", "http://127.0.0.1:41139"),
            graphics_manager_url=env_loopback_url("AI_GRAPHICS_MANAGER_URL", "http://127.0.0.1:41148"),
            autorouting_url=env_loopback_url("AI_AUTOROUTING_URL", "http://127.0.0.1:41155"),
            model_endpoints=endpoints,
        )


SETTINGS = CoreSettings.from_env()
