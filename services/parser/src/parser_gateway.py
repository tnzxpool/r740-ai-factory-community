#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


LISTEN_HOST = os.getenv("AI_PARSER_HOST", "127.0.0.1")
LISTEN_PORT = int(os.getenv("AI_PARSER_PORT", "41144"))
KEY_FILE = Path(os.getenv("AI_PARSER_KEY_FILE", "/etc/ai-parser/internal.key"))
TIKA_JAR = os.getenv("AI_PARSER_TIKA_JAR", "/opt/ai-parser/tika-app-3.3.2.jar")
TEMP_DIR = Path(os.getenv("AI_PARSER_TEMP_DIR", "/var/lib/ai-parser/tmp"))
MAX_INPUT = int(os.getenv("AI_PARSER_MAX_INPUT", str(20 * 1024 * 1024)))
MAX_OUTPUT = int(os.getenv("AI_PARSER_MAX_OUTPUT", str(5 * 1024 * 1024)))
TIMEOUT_SECONDS = int(os.getenv("AI_PARSER_TIMEOUT", "35"))
ALLOWED_IPS = {
    item.strip()
    for item in os.getenv("AI_PARSER_ALLOWED_IPS", "127.0.0.1,::1").split(",")
    if item.strip()
}
JAVA_BIN = os.getenv("AI_PARSER_JAVA_BIN", "/usr/bin/java")
SERVICE_HOME = os.getenv("AI_PARSER_HOME", "/var/lib/ai-parser")
TESSDATA_PREFIX = os.getenv(
    "AI_PARSER_TESSDATA_PREFIX", "/usr/share/tesseract-ocr/5/tessdata"
)
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".odp", ".rtf", ".txt", ".md", ".csv", ".json",
    ".xml", ".html", ".htm", ".epub", ".eml", ".msg",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
SLOTS = threading.BoundedSemaphore(2)


def load_key() -> bytes:
    value = KEY_FILE.read_text(encoding="ascii").strip()
    if len(value) < 32:
        raise RuntimeError("internal parser key is too short")
    return value.encode("ascii")


INTERNAL_KEY = load_key()


class ParserHandler(BaseHTTPRequestHandler):
    server_version = "R740Parser/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        source = self.client_address[0]
        supplied = self.headers.get("X-AI-Parser-Key", "").encode("ascii", "ignore")
        return source in ALLOWED_IPS and hmac.compare_digest(supplied, INTERNAL_KEY)

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_json(404, {"error": "not_found"})
            return
        if not self.authorized():
            self.send_json(403, {"error": "forbidden"})
            return
        self.send_json(200, {
            "status": "ok",
            "service": "ai-parser",
            "parser": "Apache Tika 3.3.2",
            "ocr": ["ita", "eng"],
            "max_input_bytes": MAX_INPUT,
        })

    def do_POST(self) -> None:
        request_id = uuid.uuid4().hex[:16]
        if self.path != "/v1/extract":
            self.send_json(404, {"error": "not_found", "request_id": request_id})
            return
        if not self.authorized():
            self.send_json(403, {"error": "forbidden", "request_id": request_id})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 1 or length > MAX_INPUT:
            self.send_json(413, {"error": "invalid_size", "max_bytes": MAX_INPUT, "request_id": request_id})
            return

        raw_name = urllib.parse.unquote(self.headers.get("X-Filename", "document.bin"))
        safe_name = Path(raw_name.replace("\\", "/")).name[:180]
        suffix = Path(safe_name).suffix.lower()
        if not safe_name or suffix not in ALLOWED_EXTENSIONS:
            self.send_json(415, {"error": "unsupported_format", "request_id": request_id})
            return
        if not SLOTS.acquire(blocking=False):
            self.send_json(429, {"error": "parser_busy", "request_id": request_id})
            return

        started = time.monotonic()
        input_path: Path | None = None
        output_path: Path | None = None
        error_path: Path | None = None
        try:
            data = self.rfile.read(length)
            if len(data) != length:
                self.send_json(400, {"error": "incomplete_upload", "request_id": request_id})
                return
            digest = hashlib.sha256(data).hexdigest()
            with tempfile.NamedTemporaryFile(dir=TEMP_DIR, prefix="input-", suffix=suffix, delete=False) as handle:
                handle.write(data)
                input_path = Path(handle.name)
            with tempfile.NamedTemporaryFile(dir=TEMP_DIR, prefix="output-", delete=False) as handle:
                output_path = Path(handle.name)
            with tempfile.NamedTemporaryFile(dir=TEMP_DIR, prefix="error-", delete=False) as handle:
                error_path = Path(handle.name)

            environment = {
                "PATH": "/usr/bin:/bin",
                "HOME": SERVICE_HOME,
                "LANG": "C.UTF-8",
                "TESSDATA_PREFIX": TESSDATA_PREFIX,
            }
            with output_path.open("wb") as stdout_handle, error_path.open("wb") as stderr_handle:
                completed = subprocess.run(
                    [
                        JAVA_BIN, "-Xms64m", "-Xmx768m",
                        f"-Djava.io.tmpdir={TEMP_DIR}", "-jar", TIKA_JAR,
                        "--text", str(input_path),
                    ],
                    cwd=TEMP_DIR,
                    env=environment,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    timeout=TIMEOUT_SECONDS,
                    check=False,
                )
            if completed.returncode != 0:
                detail = error_path.read_text(encoding="utf-8", errors="replace")[-1000:]
                self.send_json(422, {"error": "extraction_failed", "detail": detail, "request_id": request_id})
                return
            output_size = output_path.stat().st_size
            if output_size > MAX_OUTPUT:
                self.send_json(413, {"error": "extracted_text_too_large", "max_bytes": MAX_OUTPUT, "request_id": request_id})
                return
            text = output_path.read_text(encoding="utf-8", errors="replace").replace("\x00", " ").strip()
            if not text:
                self.send_json(422, {"error": "no_text_extracted", "request_id": request_id})
                return
            if suffix in IMAGE_EXTENSIONS:
                readable_tokens = re.findall(r"[^\W\d_]{3,}", text, flags=re.UNICODE)
                alnum_count = sum(character.isalnum() for character in text)
                if alnum_count < 12 or len(readable_tokens) < 2:
                    self.send_json(422, {
                        "error": "ocr_not_reliable",
                        "detail": "Use a clearer scan or a native vision model.",
                        "request_id": request_id,
                    })
                    return
            self.send_json(200, {
                "ok": True,
                "request_id": request_id,
                "filename": safe_name,
                "sha256": digest,
                "text": text,
                "characters": len(text),
                "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                "parser": "apache-tika-3.3.2",
            })
        except subprocess.TimeoutExpired:
            self.send_json(408, {"error": "extraction_timeout", "request_id": request_id})
        except Exception as exc:
            self.send_json(500, {"error": "internal_error", "detail": type(exc).__name__, "request_id": request_id})
        finally:
            for candidate in (input_path, output_path, error_path):
                if candidate is not None:
                    candidate.unlink(missing_ok=True)
            SLOTS.release()


def main() -> None:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ParserHandler)
    server.daemon_threads = True
    print(f"ai-parser listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
