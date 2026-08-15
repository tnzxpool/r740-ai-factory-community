# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class PolicyError(ValueError):
    pass


SENSITIVE_NAMES = {
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker",
    "credentials", "passwords", "cookies", "login data",
}


@dataclass(frozen=True)
class ConnectorConfig:
    endpoint: str
    certificate_pin: str | None
    consent: str
    result_limit_bytes: int
    timeout_seconds: int
    allowed_roots: tuple[Path, ...]
    allowed_tools: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> "ConnectorConfig":
        raw = json.loads(path.read_text(encoding="utf-8"))
        endpoint = str(raw.get("endpoint", "")).strip()
        parsed = urlsplit(endpoint)
        try:
            endpoint_port = parsed.port or 443
        except ValueError as exc:
            raise PolicyError("Porta endpoint MCP non valida") from exc
        if (
            parsed.scheme != "wss"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/api/local-mcp/connect"
            or parsed.query
            or parsed.fragment
            or endpoint_port not in {443, 8448}
        ):
            raise PolicyError("L'endpoint deve essere WSS pubblico, porta 443/8448 e path MCP esatto")
        try:
            import ipaddress
            ipaddress.ip_address(parsed.hostname)
        except ValueError:
            pass
        else:
            raise PolicyError("L'endpoint MCP richiede un hostname pubblico, non un IP letterale")
        if "." not in parsed.hostname or parsed.hostname.casefold().endswith((".local", ".localhost")):
            raise PolicyError("Hostname MCP non pubblico")
        if raw.get("tls_trust") != "system":
            raise PolicyError("tls_trust deve usare la catena pubblica verificata dal sistema")
        if raw.get("ca_file"):
            raise PolicyError("La vecchia CA privata non deve essere configurata")
        raw_pin = str(raw.get("server_certificate_sha256", "")).strip()
        pin = raw_pin.lower().replace(":", "") or None
        if pin is not None and (len(pin) != 64 or any(c not in "0123456789abcdef" for c in pin)):
            raise PolicyError("Fingerprint TLS SHA-256 opzionale non valido")
        consent = str(raw.get("consent", "every_call"))
        if consent != "every_call":
            raise PolicyError("L'MVP richiede consenso locale per ogni chiamata")
        limit = int(raw.get("result_limit_bytes", 65536))
        timeout = int(raw.get("timeout_seconds", 20))
        if not 1024 <= limit <= 65536:
            raise PolicyError("result_limit_bytes deve essere tra 1024 e 65536")
        if not 1 <= timeout <= 30:
            raise PolicyError("timeout_seconds deve essere tra 1 e 30")
        roots = tuple(Path(p).resolve(strict=True) for p in raw.get("allowed_roots", []))
        tools = {str(k): str(v) for k, v in raw.get("allowed_tools", {}).items()}
        expected = {"local_files_list": "read", "local_files_read_text": "read"}
        if tools != expected:
            raise PolicyError("L'MVP consente soltanto i due strumenti locali read-only incorporati")
        return cls(endpoint, pin, consent, limit, timeout, roots, tools)


def require_non_guest(subject: str) -> None:
    if not subject or subject.strip().casefold() == "guest":
        raise PolicyError("guest non puo usare MCP locale")


def resolve_allowed_path(roots: tuple[Path, ...], requested: str, *, must_file: bool = False) -> Path:
    if not roots:
        raise PolicyError("Nessuna cartella locale autorizzata")
    candidate = Path(requested)
    if not candidate.is_absolute():
        raise PolicyError("Il percorso deve essere assoluto e scelto localmente")
    resolved = candidate.resolve(strict=True)
    allowed = False
    for root in roots:
        try:
            if os.path.commonpath((str(root), str(resolved))) == str(root):
                allowed = True
                break
        except ValueError:
            continue
    if not allowed:
        raise PolicyError("Percorso fuori dalle cartelle autorizzate")
    relative = resolved.relative_to(root)
    current = root
    for part in relative.parts:
        if part.casefold() in SENSITIVE_NAMES:
            raise PolicyError("Percorso sensibile escluso")
        current = current / part
        if current.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(current)):
            raise PolicyError("Link e junction non sono consentiti")
    if must_file and not resolved.is_file():
        raise PolicyError("Il percorso non e un file")
    return resolved


def schema_hash(tools: list[dict[str, Any]]) -> str:
    canonical = json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
