#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ask the NX MCP bridge to stop, over the socket (external client)."""

from __future__ import annotations

import json
import os
import socket
import uuid

HOST = os.environ.get("NX_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("NX_MCP_PORT", "48160"))
TIMEOUT = float(os.environ.get("NX_MCP_TIMEOUT", "10"))


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


payload = {"id": str(uuid.uuid4()), "method": "stop", "params": {"timeout": TIMEOUT}}
with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as sock:
    sock.settimeout(TIMEOUT)
    sock.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
    print(json.dumps(_read(sock), indent=2, ensure_ascii=False))
