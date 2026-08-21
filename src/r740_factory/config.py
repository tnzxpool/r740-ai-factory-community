# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class Settings:
    bind: str
    port: int
    data_dir: Path
    model_catalog: Path
    admin_token_file: Path
    hardware_profile: str
    inference_base_url: str
    inference_api_key_file: Path | None
    inference_timeout_seconds: int
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        profile = os.getenv("R740_HARDWARE_PROFILE", "auto").strip().lower()
        if profile not in {"auto", "cpu", "nvidia"}:
            raise RuntimeError("R740_HARDWARE_PROFILE must be auto, cpu or nvidia")
        origins = tuple(
            origin.strip()
            for origin in os.getenv("R740_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        )
        return cls(
            bind=os.getenv("R740_BIND", "127.0.0.1"),
            port=_positive_int("R740_PORT", 8080),
            data_dir=Path(os.getenv("R740_DATA_DIR", "./data")),
            model_catalog=Path(
                os.getenv("R740_MODEL_CATALOG", "./model-manifests/catalog.json")
            ),
            admin_token_file=Path(
                os.getenv("R740_ADMIN_TOKEN_FILE", "./secrets/admin_token")
            ),
            hardware_profile=profile,
            inference_base_url=os.getenv("R740_INFERENCE_BASE_URL", "").rstrip("/"),
            inference_api_key_file=(
                Path(os.environ["R740_INFERENCE_API_KEY_FILE"])
                if os.getenv("R740_INFERENCE_API_KEY_FILE", "").strip() else None
            ),
            inference_timeout_seconds=_positive_int(
                "R740_INFERENCE_TIMEOUT_SECONDS", 120
            ),
            allowed_origins=origins,
        )

    def read_admin_token(self) -> str:
        try:
            token = self.admin_token_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(
                f"admin token file is not readable: {self.admin_token_file}"
            ) from exc
        if len(token) < 32:
            raise RuntimeError("admin token must contain at least 32 characters")
        return token

    def read_inference_api_key(self) -> str:
        if self.inference_api_key_file is None:
            return ""
        try:
            value = self.inference_api_key_file.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("inference API key file is not readable") from exc
        if not value:
            raise RuntimeError("inference API key file is empty")
        return value
