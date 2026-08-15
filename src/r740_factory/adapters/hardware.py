# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class HardwareReport:
    requested_profile: str
    active_profile: str
    accelerator_available: bool
    devices: tuple[dict[str, object], ...]
    warning: str | None = None

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["devices"] = list(self.devices)
        return result


class HardwareAdapter(Protocol):
    def inspect(self) -> HardwareReport: ...


class CpuAdapter:
    def __init__(self, requested_profile: str = "cpu") -> None:
        self.requested_profile = requested_profile

    def inspect(self) -> HardwareReport:
        return HardwareReport(
            requested_profile=self.requested_profile,
            active_profile="cpu",
            accelerator_available=False,
            devices=(),
        )


class NvidiaAdapter:
    def __init__(self, requested_profile: str = "nvidia") -> None:
        self.requested_profile = requested_profile

    def inspect(self) -> HardwareReport:
        executable = shutil.which("nvidia-smi")
        if not executable:
            return HardwareReport(
                requested_profile=self.requested_profile,
                active_profile="nvidia",
                accelerator_available=False,
                devices=(),
                warning="nvidia-smi is unavailable; driver/toolkit access is not ready",
            )
        command = [
            executable,
            "--query-gpu=index,name,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=5, check=True
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return HardwareReport(
                requested_profile=self.requested_profile,
                active_profile="nvidia",
                accelerator_available=False,
                devices=(),
                warning=f"NVIDIA probe failed: {type(exc).__name__}",
            )
        devices: list[dict[str, object]] = []
        for row in completed.stdout.splitlines():
            parts = [item.strip() for item in row.split(",")]
            if len(parts) != 4:
                continue
            devices.append(
                {
                    "index": parts[0],
                    "name": parts[1],
                    "memory_mib": int(parts[2]) if parts[2].isdigit() else parts[2],
                    "compute_capability": parts[3],
                }
            )
        return HardwareReport(
            requested_profile=self.requested_profile,
            active_profile="nvidia",
            accelerator_available=bool(devices),
            devices=tuple(devices),
            warning=None if devices else "nvidia-smi returned no parseable devices",
        )


def select_hardware_adapter(profile: str) -> HardwareAdapter:
    if profile == "cpu":
        return CpuAdapter(profile)
    if profile == "nvidia":
        return NvidiaAdapter(profile)
    return NvidiaAdapter(profile) if shutil.which("nvidia-smi") else CpuAdapter(profile)
