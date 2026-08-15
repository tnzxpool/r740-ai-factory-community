# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MetadataAudit:
    ALLOWED = {"event", "device_id", "call_id", "tool", "decision", "outcome", "duration_ms", "subject"}

    def __init__(self, path: Path):
        self.path = path

    def write(self, event: str, **metadata: Any) -> None:
        forbidden = set(metadata) - (self.ALLOWED - {"event"})
        if forbidden:
            raise ValueError(f"Campi audit vietati: {sorted(forbidden)}")
        row = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **metadata}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
