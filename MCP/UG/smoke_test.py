#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Route A smoke test - the make-or-break check.

Validates that NXOpen can be driven from the bridge's background worker thread on
this machine's NX 2412. Run AFTER starting the bridge in NX (play start_mcp.py)
and with a part open.

    python smoke_test.py

It calls ping, then create_block. If a block appears in NX and you get ok=True,
Route A is viable here. If NX crashes or hangs, it is not, and we fall back.
"""

from __future__ import annotations

import json
import os
import socket
import uuid

HOST = os.environ.get("NX_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("NX_MCP_PORT", "48160"))
TIMEOUT = float(os.environ.get("NX_MCP_TIMEOUT", "60"))


def _read(sock: socket.socket) -> dict:
    chunks = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("socket closed before response")
        nl = chunk.find(b"\n")
        if nl >= 0:
            chunks.append(chunk[:nl])
            break
        chunks.append(chunk)
    return json.loads(b"".join(chunks).decode("utf-8"))


def call(method: str, params: dict | None = None) -> dict:
    payload = {"id": str(uuid.uuid4()), "method": method, "params": {**(params or {}), "timeout": TIMEOUT}}
    with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as sock:
        sock.settimeout(TIMEOUT)
        sock.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
        return _read(sock)


def show(label: str, resp: dict) -> None:
    print("\n=== %s ===" % label)
    print(json.dumps(resp, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    print("NX MCP smoke test -> %s:%s" % (HOST, PORT))
    try:
        show("ping", call("ping"))
        show("create_block 100x60x40", call("create_block", {"length": 100, "width": 60, "height": 40}))
        print("\nIf a block appeared in NX with ok=True, Route A works here.")
    except ConnectionRefusedError:
        print("\nConnection refused. In NX, play start_mcp.py first (Tools > Journal > Play).")
