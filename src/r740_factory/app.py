# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import argparse
import hmac
import json
import logging
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .adapters.hardware import select_hardware_adapter
from .adapters.inference import InferenceError, OpenAICompatibleAdapter
from .config import Settings

LOG = logging.getLogger("r740_factory")
STATIC_DIR = Path(__file__).with_name("static")


class FactoryServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], settings: Settings) -> None:
        super().__init__(address, FactoryHandler)
        self.settings = settings
        self.admin_token = settings.read_admin_token()
        self.hardware = select_hardware_adapter(settings.hardware_profile)
        self.inference = OpenAICompatibleAdapter(
            settings.inference_base_url, settings.inference_timeout_seconds
        )
        settings.data_dir.mkdir(parents=True, exist_ok=True)


class FactoryHandler(BaseHTTPRequestHandler):
    server: FactoryServer
    server_version = "R740Community/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def _cors_origin(self) -> str | None:
        origin = self.headers.get("Origin", "")
        if origin and origin in self.server.settings.allowed_origins:
            return origin
        return None

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        origin = self._cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.admin_token}"
        return hmac.compare_digest(supplied, expected)

    def _read_json(self) -> dict[str, object] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > 1_048_576:
            return None
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok", "version": __version__})
        elif path == "/api/v1/info":
            self._send_json(
                HTTPStatus.OK,
                {
                    "name": "R740 AI Factory Community",
                    "version": __version__,
                    "inference_configured": self.server.inference.configured,
                },
            )
        elif path == "/api/v1/hardware":
            self._send_json(HTTPStatus.OK, self.server.hardware.inspect().to_dict())
        elif path == "/api/v1/models":
            try:
                catalog = json.loads(
                    self.server.settings.model_catalog.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {"error": "model catalog unavailable"},
                )
                return
            self._send_json(HTTPStatus.OK, catalog)
        elif path in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html")
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/v1/chat/completions":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        payload = self._read_json()
        if payload is None:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON body"})
            return
        try:
            status, response = self.server.inference.chat(payload)
        except InferenceError as exc:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        self._send_json(status, response)


def main() -> None:
    parser = argparse.ArgumentParser(description="R740 AI Factory Community control plane")
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.read_admin_token()
    json.loads(settings.model_catalog.read_text(encoding="utf-8"))
    if args.check_config:
        print("configuration valid")
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = FactoryServer((settings.bind, settings.port), settings)
    LOG.info("listening on %s:%s", settings.bind, settings.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
