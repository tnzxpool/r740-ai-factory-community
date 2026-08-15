# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

from pathlib import Path
from typing import Any

from .policy import PolicyError, resolve_allowed_path


TOOLS = [
    {
        "name": "local_files_list",
        "description": "Elenca nomi, tipo e dimensione in una cartella locale autorizzata. Sola lettura.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": "local_files_read_text",
        "description": "Legge un file di testo in una cartella locale autorizzata. Sola lettura, massimo 64 KiB.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
]


class BuiltinFilesMcp:
    """Tiny in-process MCP tool provider; it opens no socket and executes no shell."""

    def __init__(self, roots: tuple[Path, ...], result_limit: int):
        self.roots = roots
        self.result_limit = result_limit

    def list_tools(self) -> list[dict[str, Any]]:
        return TOOLS

    def handle_jsonrpc(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0" or not isinstance(request_id, (str, int)):
            raise PolicyError("Richiesta MCP JSON-RPC non valida")
        method = request.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": str((request.get("params") or {}).get("protocolVersion", "")),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "r740-local-files", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": self.list_tools()}
        elif method == "tools/call":
            params = request.get("params")
            if not isinstance(params, dict):
                raise PolicyError("Parametri MCP non validi")
            result = self.call(str(params.get("name", "")), params.get("arguments"))
        else:
            raise PolicyError("Metodo MCP non autorizzato")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict) or set(arguments) != {"path"} or not isinstance(arguments.get("path"), str):
            raise PolicyError("Argomenti non validi")
        if name == "local_files_list":
            path = resolve_allowed_path(self.roots, arguments["path"])
            if not path.is_dir():
                raise PolicyError("Il percorso non e una cartella")
            entries = []
            for item in sorted(path.iterdir(), key=lambda p: p.name.casefold())[:200]:
                if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
                    continue
                if item.name.casefold() in {".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker"}:
                    continue
                stat = item.stat()
                entries.append({"name": item.name, "type": "directory" if item.is_dir() else "file", "bytes": stat.st_size})
            return {"content": [{"type": "text", "text": str(entries)}], "isError": False}
        if name == "local_files_read_text":
            path = resolve_allowed_path(self.roots, arguments["path"], must_file=True)
            if path.stat().st_size > self.result_limit:
                raise PolicyError("File oltre il limite locale")
            raw = path.read_bytes()
            if b"\x00" in raw:
                raise PolicyError("Il file non sembra testo")
            text = raw.decode("utf-8", errors="strict")
            return {"content": [{"type": "text", "text": text}], "isError": False}
        raise PolicyError("Strumento non autorizzato")
