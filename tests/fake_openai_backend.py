#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    expected_bearer = ""
    def log_message(self, *_: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404); return
        if self.expected_bearer and self.headers.get("Authorization") != f"Bearer {self.expected_bearer}":
            self.send_error(401); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            value = json.loads(self.rfile.read(length))
            assert isinstance(value, dict) and isinstance(value.get("messages"), list)
        except (ValueError, json.JSONDecodeError, AssertionError):
            self.send_error(400); return
        body = json.dumps({"id": "community-e2e", "choices": [{"index": 0, "message": {"role": "assistant", "content": "R740-READY"}, "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--require-bearer", default="")
    args = parser.parse_args(); Handler.expected_bearer = args.require_bearer
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()
