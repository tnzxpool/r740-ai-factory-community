# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
from pathlib import Path

from .audit import MetadataAudit
from .connector import OutboundConnector
from .policy import ConnectorConfig
from .secure_store import DeviceStore


def app_dir() -> Path:
    configured = os.environ.get("R740_LOCAL_MCP_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise RuntimeError("LOCALAPPDATA non disponibile")
    return Path(base) / "R740LocalMCP"


def build_connector(config_path: Path) -> OutboundConnector:
    return OutboundConnector(
        ConnectorConfig.load(config_path),
        DeviceStore(app_dir() / "device.dpapi"),
        MetadataAudit(app_dir() / "audit.jsonl"),
    )


def choose_root(config_path: Path) -> None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    chosen = filedialog.askdirectory(title="Scegli una cartella leggibile dal connettore R740", mustexist=True)
    root.destroy()
    if not chosen:
        print("Nessuna modifica")
        return
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    roots = list(dict.fromkeys([*raw.get("allowed_roots", []), str(Path(chosen).resolve())]))
    raw["allowed_roots"] = roots
    config_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Cartella autorizzata: {chosen}")


def main() -> int:
    parser = argparse.ArgumentParser(description="R740 local MCP connector (outbound-only)")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    pair = sub.add_parser("pair")
    pair.add_argument("--code", required=True)
    pair.add_argument("--device-name", default=socket.gethostname())
    sub.add_parser("connect")
    sub.add_parser("choose-root")
    sub.add_parser("revoke-local")
    args = parser.parse_args()
    if args.command == "choose-root":
        choose_root(args.config)
        return 0
    connector = build_connector(args.config)
    if args.command == "pair":
        result = asyncio.run(connector.pair(args.code, args.device_name))
        print(f"Associato a {result['subject']} come {result['device_id']}")
    elif args.command == "connect":
        asyncio.run(connector.run_forever())
    elif args.command == "revoke-local":
        connector.store.revoke_local()
        print("Credenziale locale rimossa. Revocare anche il dispositivo dal pannello Admin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
