#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NX MCP server (stdio).

Talks to a live NX session through the socket bridge started by start_mcp.py
inside NX. Mirrors the Abaqus MCP transport: one JSON object per line over a
local TCP socket.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP

HOST = os.environ.get("NX_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("NX_MCP_PORT", "48160"))
DEFAULT_TIMEOUT = float(os.environ.get("NX_MCP_TIMEOUT", "120"))

INSTRUCTIONS = """You are driving a live Siemens NX session through MCP.

NXOpen runs on a single serialized worker thread, so issue one operation at a
time. A work part must be open in NX before modeling. Prefer the dedicated tools
(create_block, ...) when they exist; use run_python for anything else, building
up the model in small validated steps. `NXOpen`, `session`, and `workPart` are
preloaded in the run_python namespace.
"""

mcp = FastMCP("nx-mcp-server", instructions=INSTRUCTIONS)


class ProtocolError(RuntimeError):
    pass


def _send(sock: socket.socket, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sock.sendall(data + b"\n")


def _read(sock: socket.socket) -> dict[str, Any]:
    chunks: list[bytes] = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise ProtocolError("socket closed before a complete message was received")
        nl = chunk.find(b"\n")
        if nl >= 0:
            chunks.append(chunk[:nl])
            break
        chunks.append(chunk)
    msg = json.loads(b"".join(chunks).decode("utf-8"))
    if not isinstance(msg, dict):
        raise ProtocolError("protocol message must be a JSON object")
    return msg


def _request(method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
    eff = timeout if timeout is not None else DEFAULT_TIMEOUT
    payload = {"id": str(uuid.uuid4()), "method": method, "params": {**(params or {}), "timeout": eff}}
    with socket.create_connection((HOST, PORT), timeout=eff) as sock:
        sock.settimeout(eff)
        _send(sock, payload)
        resp = _read(sock)
    if resp.get("id") != payload["id"]:
        raise ProtocolError("NX bridge returned a mismatched response id")
    if not resp.get("ok", False):
        err = resp.get("error") or {}
        raise RuntimeError(err.get("message") if isinstance(err, dict) else str(err))
    result = resp.get("result")
    if not isinstance(result, dict):
        raise ProtocolError("NX bridge returned an invalid result envelope")
    return result


async def _bridge(method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_request, method, params, timeout)
    except ConnectionRefusedError as exc:
        raise RuntimeError(
            f"Cannot reach the NX bridge at {HOST}:{PORT}. In NX, play start_mcp.py "
            f"(Tools > Journal > Play) to start it. Original error: {exc}"
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            f"Timed out waiting for the NX bridge. NX may be busy. Original error: {exc}"
        ) from exc


@mcp.tool()
async def ping() -> dict[str, Any]:
    """Check the NX bridge is alive and report session/bridge info."""
    return await _bridge("ping")


@mcp.tool()
async def create_block(
    length: float = 100.0,
    width: float = 60.0,
    height: float = 40.0,
    origin: list[float] | None = None,
) -> dict[str, Any]:
    """Create a block (long x wide x high) at origin in the current NX work part."""
    params = {"length": length, "width": width, "height": height, "origin": origin or [0.0, 0.0, 0.0]}
    return await _bridge("create_block", params)


@mcp.tool()
async def run_python(code: str, timeout: float | None = None) -> dict[str, Any]:
    """Execute NXOpen Python in the live session. `NXOpen`, `session`, `workPart`
    are preloaded; set a `result` variable to return a value."""
    return await _bridge("execute", {"code": code}, timeout)


if __name__ == "__main__":
    mcp.run()
