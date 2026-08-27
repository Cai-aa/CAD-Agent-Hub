#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Client for the non-blocking NX remoting bridge, with legacy TCP fallback."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 48160
DEFAULT_REMOTING_PORT = 48161
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class BridgeError(RuntimeError):
    """Base error raised by the NX bridge client."""


class BridgeConnectionError(BridgeError):
    """The local NX bridge could not be reached."""


class BridgeProtocolError(BridgeError):
    """The bridge returned an invalid protocol message."""


class BridgeRemoteError(BridgeError):
    """NX received the request but the NXOpen operation failed."""

    def __init__(self, message: str, remote_type: str | None = None) -> None:
        self.remote_type = remote_type
        prefix = f"{remote_type}: " if remote_type else ""
        super().__init__(prefix + message)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


class NXBridgeClient:
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
        token: str | None = None,
        max_response_bytes: int | None = None,
        transport: str | None = None,
        remoting_port: int | None = None,
        client_exe: str | os.PathLike[str] | None = None,
    ) -> None:
        self.transport = (
            transport or os.environ.get("NX_MCP_TRANSPORT", "remoting")
        ).strip().lower()
        if self.transport not in {"remoting", "tcp"}:
            raise ValueError("NX_MCP_TRANSPORT must be 'remoting' or 'tcp'")
        self.host = host or os.environ.get("NX_MCP_HOST", DEFAULT_HOST)
        self.port = port if port is not None else _env_int("NX_MCP_PORT", DEFAULT_PORT)
        self.remoting_port = (
            remoting_port
            if remoting_port is not None
            else _env_int("NX_MCP_REMOTING_PORT", DEFAULT_REMOTING_PORT)
        )
        self.timeout = timeout if timeout is not None else _env_float("NX_MCP_TIMEOUT", DEFAULT_TIMEOUT)
        self.token = token if token is not None else os.environ.get("NX_MCP_TOKEN", "")
        configured_client = client_exe or os.environ.get("NX_MCP_CLIENT_EXE")
        self.client_exe = Path(configured_client) if configured_client else (
            ROOT / "dotnet_bridge" / "bin" / "NXRemoteClient.exe"
        )
        self.operations_path = Path(
            os.environ.get("NX_MCP_REMOTE_OPS", str(ROOT / "nx_remote_ops.py"))
        )
        ugii_base = os.environ.get("UGII_BASE_DIR", "")
        self.nxopen_path = Path(
            os.environ.get(
                "NX_MCP_NXOPEN_DLL",
                str(Path(ugii_base) / "NXBIN" / "managed" / "NXOpen.dll")
                if ugii_base
                else "",
            )
        )
        self.max_response_bytes = (
            max_response_bytes
            if max_response_bytes is not None
            else _env_int("NX_MCP_MAX_RESPONSE_BYTES", DEFAULT_MAX_RESPONSE_BYTES)
        )
        if not self.host.strip():
            raise ValueError("NX_MCP_HOST must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("NX_MCP_PORT must be between 1 and 65535")
        if not 1 <= self.remoting_port <= 65535:
            raise ValueError("NX_MCP_REMOTING_PORT must be between 1 and 65535")
        if self.timeout <= 0:
            raise ValueError("NX_MCP_TIMEOUT must be greater than zero")
        if self.max_response_bytes < 1024:
            raise ValueError("NX_MCP_MAX_RESPONSE_BYTES must be at least 1024")

    @property
    def endpoint(self) -> str:
        if self.transport == "remoting":
            return f"http://{self.host}:{self.remoting_port}/NXOpenSession"
        return f"{self.host}:{self.port}"

    def _decode_response(self, data: bytes) -> dict[str, Any]:
        if len(data) > self.max_response_bytes:
            raise BridgeProtocolError(
                f"bridge response exceeded {self.max_response_bytes} bytes"
            )
        try:
            message = json.loads(data.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BridgeProtocolError(f"bridge returned invalid UTF-8 JSON: {exc}") from exc
        if not isinstance(message, dict):
            raise BridgeProtocolError("bridge response must be a JSON object")
        return message

    def _read_response(self, sock: socket.socket) -> dict[str, Any]:
        data = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                raise BridgeProtocolError("socket closed before a complete response was received")
            newline = chunk.find(b"\n")
            data.extend(chunk if newline < 0 else chunk[:newline])
            if len(data) > self.max_response_bytes:
                raise BridgeProtocolError(
                    f"bridge response exceeded {self.max_response_bytes} bytes"
                )
            if newline >= 0:
                break
        return self._decode_response(bytes(data))

    def _request_remoting(
        self,
        encoded: bytes,
        effective_timeout: float,
        operations_path: Path | None = None,
        class_name: str | None = None,
        method_name: str = "handle",
    ) -> dict[str, Any]:
        if not self.client_exe.is_file():
            raise BridgeConnectionError(
                f"NX remoting client is not built: {self.client_exe}; run "
                "dotnet_bridge\\build_bridge.ps1"
            )
        target_path = operations_path or self.operations_path
        if not target_path.is_file():
            raise BridgeConnectionError(
                f"NX remoting operations file is missing: {target_path}"
            )
        if not self.nxopen_path.is_file():
            raise BridgeConnectionError(
                "NXOpen.dll was not found; set UGII_BASE_DIR or NX_MCP_NXOPEN_DLL"
            )
        command = [
            str(self.client_exe),
            "--url",
            self.endpoint,
            "--nxopen",
            str(self.nxopen_path),
            "--ops",
            str(target_path),
        ]
        if class_name:
            command.extend(["--class", class_name, "--method", method_name])
        try:
            completed = subprocess.run(
                command,
                input=encoded,
                capture_output=True,
                timeout=effective_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BridgeConnectionError(
                f"timed out waiting for NX remoting at {self.endpoint}"
            ) from exc
        except OSError as exc:
            raise BridgeConnectionError(
                f"failed to start NX remoting client {self.client_exe}: {exc}"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise BridgeConnectionError(
                f"cannot reach the non-blocking NX bridge at {self.endpoint}; "
                "load NXMcPRemotingServer.dll in NX with Ctrl+U"
                + (f" ({detail})" if detail else "")
            )
        return self._decode_response(completed.stdout.strip())

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not isinstance(method, str) or not method.strip():
            raise ValueError("method must be a non-empty string")
        if params is not None and not isinstance(params, dict):
            raise ValueError("params must be an object")
        effective_timeout = self.timeout if timeout is None else float(timeout)
        if effective_timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        request_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "id": request_id,
            "method": method,
            "params": {**(params or {}), "timeout": effective_timeout},
        }
        if self.token:
            payload["token"] = self.token
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8") + b"\n"

        if self.transport == "remoting":
            response = self._request_remoting(encoded, effective_timeout)
        else:
            try:
                with socket.create_connection(
                    (self.host, self.port), timeout=effective_timeout
                ) as sock:
                    sock.settimeout(effective_timeout)
                    sock.sendall(encoded)
                    response = self._read_response(sock)
            except (socket.timeout, TimeoutError) as exc:
                raise BridgeConnectionError(
                    f"timed out waiting for the NX bridge at {self.endpoint}; NX may be busy"
                ) from exc
            except OSError as exc:
                raise BridgeConnectionError(
                    f"cannot reach the legacy NX TCP bridge at {self.endpoint} ({exc})"
                ) from exc

        if response.get("id") != request_id:
            raise BridgeProtocolError("NX bridge returned a mismatched response id")
        if response.get("ok") is not True:
            error = response.get("error")
            if isinstance(error, dict):
                raise BridgeRemoteError(
                    str(error.get("message") or "NX operation failed"),
                    str(error.get("type")) if error.get("type") else None,
                )
            raise BridgeRemoteError(str(error or "NX operation failed"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise BridgeProtocolError("NX bridge returned an invalid result envelope")
        return result
