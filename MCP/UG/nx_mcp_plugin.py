# -*- coding: utf-8 -*-
"""
NX MCP bridge - runs INSIDE a live NX session.

Why this shape (NX 2412, learned the hard way):
  NX runs a Python journal in a SUBINTERPRETER on its own thread (not the main
  UI thread). A journal that spawns daemon threads and then RETURNS gets those
  threads frozen/torn down when the journal ends - the subinterpreter goes away.

  So instead of "spawn-and-return", the start journal calls serve_blocking()
  which NEVER returns: it runs a single-threaded socket loop right here. Because
  the journal already lives on a non-main thread, blocking it does not freeze the
  NX UI, and every request is handled on this same thread - the normal thread
  journals use to call NXOpen - so NXOpen calls are safe and fully serialized.

  Do not add a `# nx: threaded` directive to the start journal: that would move
  execution onto the main thread and blocking WOULD freeze the UI.

Start:  play start_mcp.py    (blocks inside NX; UI stays usable)
Stop:   run  stop_mcp.py     (external; connects and sends "stop")
"""

from __future__ import print_function

import ctypes
from ctypes import wintypes
import io
import json
import os
import select
import socket
import sys
import tempfile
import threading
import time
import traceback

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

__version__ = "0.2.0"

HOST = os.environ.get("NX_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("NX_MCP_PORT", "48160"))
LOG_PATH = os.environ.get(
    "NX_MCP_LOG",
    os.path.join(tempfile.gettempdir(), "nx_mcp_bridge.log"),
)
MAX_OUTPUT = 8000

_SERVER = None
_STOP = threading.Event()
_PROCESSED = 0
_START_TIME = None
# Namespace persisted across execute() calls so users can build up state.
_EXEC_NS = {"__name__": "__nx_mcp_exec__", "__doc__": None}


def _log(message):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except Exception:
        pass


def _announce(message):
    print(message)
    try:
        lw = NXOpen.Session.GetSession().ListingWindow
        lw.Open()
        lw.WriteLine(message)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Socket framing: one JSON object per line (matches the Abaqus MCP protocol).
# --------------------------------------------------------------------------- #
def _send(sock, payload):
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sock.sendall(data + b"\n")


def _recv(sock):
    chunks = []
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("socket closed before a complete message was received")
        newline = chunk.find(b"\n")
        if newline >= 0:
            chunks.append(chunk[:newline])
            break
        chunks.append(chunk)
    return json.loads(b"".join(chunks).decode("utf-8"))


# --------------------------------------------------------------------------- #
# NXOpen operations - run inline on the journal (subinterpreter) thread.
# --------------------------------------------------------------------------- #
def _work_part():
    work = NXOpen.Session.GetSession().Parts.Work
    if work is None or work.Tag == 0:
        raise RuntimeError("No work part is open in NX. Create or open a part first.")
    return work


def _op_ping(params):
    session = NXOpen.Session.GetSession()
    work = session.Parts.Work
    return {
        "ok": True,
        "bridge_version": __version__,
        "python": sys.version,
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
        "endpoint": "%s:%s" % (HOST, PORT),
        "processed": _PROCESSED,
        "uptime_seconds": int(time.time() - _START_TIME) if _START_TIME else 0,
        "work_part": (work.Leaf if (work and work.Tag != 0) else None),
        "log": LOG_PATH,
    }


def _op_create_block(params):
    length = params.get("length", 100.0)
    width = params.get("width", 60.0)
    height = params.get("height", 40.0)
    origin = params.get("origin", [0.0, 0.0, 0.0])

    work = _work_part()
    session = NXOpen.Session.GetSession()
    session.SetUndoMark(NXOpen.Session.MarkVisibility.Visible, "MCP create_block")
    builder = work.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    try:
        builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
        origin_pt = NXOpen.Point3d(float(origin[0]), float(origin[1]), float(origin[2]))
        builder.SetOriginAndLengths(origin_pt, str(length), str(width), str(height))
        builder.SetBooleanOperationAndTarget(
            NXOpen.Features.Feature.BooleanType.Create, NXOpen.Body.Null
        )
        feature = builder.CommitFeature()
    finally:
        builder.Destroy()

    return {
        "ok": True,
        "feature": feature.JournalIdentifier,
        "name": feature.Name,
        "length": length,
        "width": width,
        "height": height,
        "origin": [float(origin[0]), float(origin[1]), float(origin[2])],
    }


def _op_execute(params):
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("params.code must be a non-empty string")

    session = NXOpen.Session.GetSession()
    _EXEC_NS.update({
        "NXOpen": NXOpen,
        "session": session,
        "theSession": session,
        "workPart": session.Parts.Work,
        "displayPart": session.Parts.Display,
    })

    stdout, stderr = io.StringIO(), io.StringIO()
    returned = None
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = stdout, stderr
        try:
            compiled = compile(code, "<nx-mcp>", "eval")
            returned = eval(compiled, _EXEC_NS, _EXEC_NS)
        except SyntaxError:
            compiled = compile(code, "<nx-mcp>", "exec")
            exec(compiled, _EXEC_NS, _EXEC_NS)
            returned = _EXEC_NS.get("result")
    finally:
        sys.stdout, sys.stderr = old_out, old_err

    out, err = stdout.getvalue(), stderr.getvalue()
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + "\n... (truncated)"
    if len(err) > MAX_OUTPUT:
        err = err[:MAX_OUTPUT] + "\n... (truncated)"

    def _jsonable(value):
        try:
            json.dumps(value, ensure_ascii=False)
            return value
        except Exception:
            return {"repr": repr(value), "type": type(value).__name__}

    return {"ok": True, "return_value": _jsonable(returned), "stdout": out, "stderr": err}


_OPS = {
    "ping": _op_ping,
    "create_block": _op_create_block,
    "execute": _op_execute,
}


# --------------------------------------------------------------------------- #
# Win32 message pump: keeps the NX UI alive while we block on the main thread.
# The journal runs on NX's main UI thread, so pumping PeekMessage/DispatchMessage
# here lets NX service paint + input events. Everything stays single-threaded and
# cooperative: a user command (via DispatchMessage) and a Claude request (via the
# socket) both run to completion on this thread, never concurrently.
# --------------------------------------------------------------------------- #
_user32 = ctypes.windll.user32
_PM_REMOVE = 0x0001
_WM_QUIT = 0x0012


def _pump_messages():
    msg = wintypes.MSG()
    pmsg = ctypes.byref(msg)
    # Drain all currently-pending messages, then return so we can poll the socket.
    while _user32.PeekMessageW(pmsg, 0, 0, 0, _PM_REMOVE):
        if msg.message == _WM_QUIT:
            _STOP.set()
            return
        _user32.TranslateMessage(pmsg)
        _user32.DispatchMessageW(pmsg)


def _handle_conn(conn):
    global _PROCESSED
    request_id = None
    try:
        conn.settimeout(30.0)
        message = _recv(conn)
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        _log("request method=%s id=%s" % (method, request_id))

        if method == "stop":
            _STOP.set()
            result = {"ok": True, "message": "stop accepted"}
        else:
            op = _OPS.get(method)
            if op is None:
                raise ValueError("unknown method: %r" % method)
            result = op(params)
            _PROCESSED += 1

        _send(conn, {"id": request_id, "ok": True, "result": result})
    except Exception as exc:
        _log("error id=%s: %s\n%s" % (request_id, exc, traceback.format_exc()))
        try:
            _send(conn, {
                "id": request_id,
                "ok": False,
                "error": {
                    "message": str(exc),
                    "type": "%s.%s" % (type(exc).__module__, type(exc).__name__),
                    "traceback": traceback.format_exc(),
                },
            })
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def serve_blocking():
    """Run a cooperative loop on the calling (NX main UI) thread: pump the NX
    message queue AND service the socket. NEVER returns until a 'stop' request
    arrives or stop_serving() is called. The message pump keeps the UI usable."""
    global _SERVER, _START_TIME
    if _SERVER is not None:
        _announce("NX MCP bridge already running on %s:%s" % (HOST, PORT))
        return

    _STOP.clear()
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind((HOST, PORT))
    lsock.listen(8)
    lsock.setblocking(False)
    _SERVER = lsock
    _START_TIME = time.time()
    _announce("NX MCP bridge listening on %s:%s (log: %s)" % (HOST, PORT, LOG_PATH))
    _log("serve_blocking start on thread %s" % threading.current_thread().name)
    try:
        while not _STOP.is_set():
            _pump_messages()
            try:
                ready, _, _ = select.select([lsock], [], [], 0.01)
            except (OSError, ValueError):
                break
            if ready:
                try:
                    conn, _addr = lsock.accept()
                except OSError:
                    continue
                _handle_conn(conn)
    finally:
        try:
            lsock.close()
        finally:
            _SERVER = None
        _announce("NX MCP bridge stopped.")
        _log("serve_blocking exited")


def stop_serving():
    _STOP.set()


def main(args=None):
    serve_blocking()


# NX runs journals with __name__ == "__main__". Prefer playing start_mcp.py so
# the bridge is an importable module that survives across journals.
if __name__ == "__main__":
    main()
