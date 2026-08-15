# SPDX-License-Identifier: LGPL-3.0-or-later
from __future__ import annotations

import asyncio
import json
import ssl
import time
import uuid
from pathlib import Path
from typing import Any

from websockets.asyncio.client import ClientConnection, connect

from .audit import MetadataAudit
from .builtin_files import BuiltinFilesMcp
from .consent import ask_local_consent
from .policy import ConnectorConfig, PolicyError, require_non_guest, schema_hash
from .protocol import (
    PROTOCOL,
    bounded_tool_result,
    certificate_sha256,
    new_device_key,
    safe_json_message,
    sign_challenge,
)
from .secure_store import DeviceStore


class ConnectorError(RuntimeError):
    pass


class OutboundConnector:
    def __init__(self, config: ConnectorConfig, store: DeviceStore, audit: MetadataAudit):
        self.config = config
        self.store = store
        self.audit = audit
        self.tools = BuiltinFilesMcp(config.allowed_roots, config.result_limit_bytes)

    def _ssl_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return context

    def _verify_pin(self, websocket: ClientConnection) -> None:
        if self.config.certificate_pin is None:
            return
        transport = getattr(websocket, "transport", None)
        ssl_object = transport.get_extra_info("ssl_object") if transport else None
        if ssl_object is None:
            raise ConnectorError("Connessione senza TLS verificabile")
        actual = certificate_sha256(ssl_object.getpeercert(binary_form=True))
        if actual != self.config.certificate_pin:
            raise ConnectorError("Fingerprint del certificato R740 inatteso")

    async def _open(self) -> ClientConnection:
        websocket = await connect(
            self.config.endpoint,
            ssl=self._ssl_context(),
            subprotocols=[PROTOCOL],
            open_timeout=self.config.timeout_seconds,
            close_timeout=5,
            ping_interval=20,
            ping_timeout=20,
            max_size=131072,
            max_queue=8,
        )
        try:
            if websocket.subprotocol != PROTOCOL:
                raise ConnectorError("Subprotocollo R740 non negoziato")
            self._verify_pin(websocket)
            return websocket
        except Exception:
            await websocket.close()
            raise

    async def pair(self, code: str, device_name: str) -> dict[str, str]:
        if not (8 <= len(code) <= 32 and code.replace("-", "").isalnum()):
            raise PolicyError("Codice pairing non valido")
        private_key, public_key = new_device_key()
        device_id = str(uuid.uuid4())
        websocket = await self._open()
        try:
            await websocket.send(json.dumps({
                "type": "connect.hello", "protocol": PROTOCOL, "mode": "pair",
            }, separators=(",", ":")))
            ready = safe_json_message(await asyncio.wait_for(websocket.recv(), self.config.timeout_seconds))
            if ready.get("type") != "pair.ready":
                raise ConnectorError("Canale pairing non disponibile")
            await websocket.send(json.dumps({
                "type": "pair.start", "protocol": PROTOCOL, "code": code,
                "device_id": device_id, "device_name": device_name[:80],
                "public_key": public_key,
            }, separators=(",", ":")))
            response = safe_json_message(await asyncio.wait_for(websocket.recv(), self.config.timeout_seconds))
            if response.get("type") != "pair.accepted":
                raise ConnectorError("Pairing rifiutato")
            subject = str(response.get("subject", ""))
            require_non_guest(subject)
            token = str(response.get("device_token", ""))
            if len(token) < 32:
                raise ConnectorError("Token dispositivo non valido")
            record = {
                "device_id": device_id,
                "device_name": device_name[:80],
                "subject": subject,
                "private_key": private_key,
                "public_key": public_key,
                "device_token": token,
            }
            self.store.save(record)
            self.audit.write("pairing_complete", device_id=device_id, subject=subject, outcome="accepted")
            return {"device_id": device_id, "subject": subject}
        finally:
            await websocket.close()

    async def _authenticate(self, websocket: ClientConnection, record: dict[str, str]) -> str:
        await websocket.send(json.dumps({
            "type": "connect.hello", "protocol": PROTOCOL, "mode": "auth",
            "device_id": record["device_id"],
        }, separators=(",", ":")))
        challenge = safe_json_message(await asyncio.wait_for(websocket.recv(), self.config.timeout_seconds))
        if challenge.get("type") != "auth.challenge" or not isinstance(challenge.get("nonce"), str):
            raise ConnectorError("Challenge di autenticazione non valido")
        nonce = challenge["nonce"]
        if not 16 <= len(nonce) <= 256:
            raise ConnectorError("Nonce non valido")
        await websocket.send(json.dumps({
            "type": "auth.response", "device_id": record["device_id"],
            "device_token": record["device_token"],
            "public_key": record["public_key"],
            "signature": sign_challenge(record["private_key"], record["device_id"], nonce),
        }, separators=(",", ":")))
        response = safe_json_message(await asyncio.wait_for(websocket.recv(), self.config.timeout_seconds))
        if response.get("type") != "auth.accepted":
            raise ConnectorError("Autenticazione dispositivo rifiutata")
        subject = str(response.get("subject", ""))
        require_non_guest(subject)
        if subject != record["subject"]:
            raise ConnectorError("Identita del dispositivo non coerente")
        return subject

    async def _handle_call(self, websocket: ClientConnection, message: dict[str, Any], subject: str) -> None:
        call_id = message.get("call_id")
        tool = message.get("tool")
        arguments = message.get("arguments")
        remote_subject = message.get("subject")
        if not isinstance(call_id, str) or not 8 <= len(call_id) <= 128:
            raise PolicyError("call_id non valido")
        if remote_subject != subject:
            raise PolicyError("Identita chiamata non coerente")
        require_non_guest(str(remote_subject))
        if not isinstance(tool, str) or self.config.allowed_tools.get(tool) != "read":
            raise PolicyError("Strumento non autorizzato o mutativo")
        if message.get("class") != "read" or not isinstance(arguments, dict):
            raise PolicyError("Classe o argomenti non validi")
        started = time.monotonic()
        consent = await asyncio.to_thread(ask_local_consent, subject, tool, arguments)
        self.audit.write("tool_consent", call_id=call_id, tool=tool, subject=subject, decision="allow_once" if consent else "deny")
        if not consent:
            await websocket.send(json.dumps({"type": "tool.denied", "call_id": call_id, "reason": "local_consent_denied"}, separators=(",", ":")))
            return
        try:
            result = await asyncio.wait_for(asyncio.to_thread(self.tools.call, tool, arguments), self.config.timeout_seconds)
            safe_result = bounded_tool_result(result, self.config.result_limit_bytes)
            await websocket.send(json.dumps({"type": "tool.result", "call_id": call_id, **safe_result}, ensure_ascii=False, separators=(",", ":")))
            outcome = "success"
        except Exception as exc:
            await websocket.send(json.dumps({"type": "tool.error", "call_id": call_id, "error": type(exc).__name__}, separators=(",", ":")))
            outcome = "error"
        duration = int((time.monotonic() - started) * 1000)
        self.audit.write("tool_complete", call_id=call_id, tool=tool, subject=subject, outcome=outcome, duration_ms=duration)

    async def connect_once(self) -> None:
        record = self.store.load()
        require_non_guest(record.get("subject", ""))
        websocket = await self._open()
        try:
            subject = await self._authenticate(websocket, record)
            tools = self.tools.list_tools()
            await websocket.send(json.dumps({
                "type": "tools.manifest", "tools": tools, "schema_hash": schema_hash(tools),
            }, ensure_ascii=False, separators=(",", ":")))
            self.audit.write("connector_online", device_id=record["device_id"], subject=subject, outcome="connected")
            async for raw in websocket:
                message = safe_json_message(raw)
                if message.get("type") != "tool.call":
                    raise ConnectorError("Messaggio remoto non consentito")
                try:
                    await self._handle_call(websocket, message, subject)
                except PolicyError as exc:
                    call_id = message.get("call_id", "invalid")
                    await websocket.send(json.dumps({"type": "tool.denied", "call_id": call_id, "reason": "policy_denied"}, separators=(",", ":")))
                    self.audit.write("tool_policy_deny", call_id=str(call_id)[:128], subject=subject, outcome=type(exc).__name__)
        finally:
            await websocket.close()

    async def run_forever(self) -> None:
        delay = 2
        while True:
            try:
                await self.connect_once()
                delay = 2
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.audit.write("connector_offline", outcome=type(exc).__name__)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
