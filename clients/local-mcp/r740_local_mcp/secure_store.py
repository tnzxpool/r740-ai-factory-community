# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any


class SecureStoreError(RuntimeError):
    pass


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, Any]:
    buf = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))), buf


def protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecureStoreError("DPAPI e disponibile solo su Windows")
    source, keepalive = _blob(data)
    result = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(ctypes.byref(source), "R740 local MCP", None, None, None, 1, ctypes.byref(result)):
        raise SecureStoreError("CryptProtectData non riuscita")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecureStoreError("DPAPI e disponibile solo su Windows")
    source, keepalive = _blob(data)
    result = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise SecureStoreError("CryptUnprotectData non riuscita")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


class DeviceStore:
    def __init__(self, path: Path):
        self.path = path

    def save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encrypted = protect(json.dumps(data, separators=(",", ":")).encode("utf-8"))
        temp = self.path.with_suffix(".tmp")
        temp.write_bytes(encrypted)
        os.replace(temp, self.path)

    def load(self) -> dict[str, str]:
        return json.loads(unprotect(self.path.read_bytes()).decode("utf-8"))

    def revoke_local(self) -> None:
        if self.path.exists():
            self.path.unlink()
