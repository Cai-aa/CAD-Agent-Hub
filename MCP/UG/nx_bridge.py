# -*- coding: utf-8 -*-
"""Persistent TCP bridge executed inside Siemens NX 2412.

This module intentionally uses only Python's standard library plus NXOpen. The
calling journal remains alive and serializes every NXOpen call on one thread.
"""

from __future__ import print_function

import hmac
import io
import json
import math
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

__version__ = "0.3.0"

HOST = os.environ.get("NX_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("NX_MCP_PORT", "48160"))
TOKEN = os.environ.get("NX_MCP_TOKEN", "")
LOG_PATH = os.environ.get(
    "NX_MCP_LOG", os.path.join(tempfile.gettempdir(), "nx_mcp_bridge.log")
)
MAX_REQUEST_BYTES = int(
    os.environ.get("NX_MCP_MAX_REQUEST_BYTES", str(4 * 1024 * 1024))
)
MAX_OUTPUT_CHARS = int(os.environ.get("NX_MCP_MAX_OUTPUT_CHARS", "16000"))
WORKSPACE = os.path.abspath(
    os.environ.get("NX_MCP_WORKSPACE", os.path.join(os.path.dirname(__file__), "workspace"))
)

if not 1 <= PORT <= 65535:
    raise ValueError("NX_MCP_PORT must be between 1 and 65535")
if MAX_REQUEST_BYTES < 1024:
    raise ValueError("NX_MCP_MAX_REQUEST_BYTES must be at least 1024")

_SERVER = None
_STOP = threading.Event()
_PROCESSED = 0
_START_TIME = None
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
        window = NXOpen.Session.GetSession().ListingWindow
        window.Open()
        window.WriteLine(message)
    except Exception:
        pass


def _send(sock, payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    sock.sendall(encoded + b"\n")


def _recv(sock):
    data = bytearray()
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            raise RuntimeError("socket closed before a complete request was received")
        newline = chunk.find(b"\n")
        data.extend(chunk if newline < 0 else chunk[:newline])
        if len(data) > MAX_REQUEST_BYTES:
            raise RuntimeError("request exceeded %s bytes" % MAX_REQUEST_BYTES)
        if newline >= 0:
            break
    message = json.loads(bytes(data).decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("request must be a JSON object")
    return message


def _work_part():
    work = NXOpen.Session.GetSession().Parts.Work
    if work is None or getattr(work, "Tag", 0) == 0:
        raise RuntimeError("No work part is open in NX. Create or open a part first.")
    return work


def _jsonable(value, depth=0):
    if depth > 8:
        return {"repr": repr(value), "type": type(value).__name__}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item, depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item, depth + 1) for key, item in value.items()}
    return {"repr": repr(value), "type": type(value).__name__}


def _op_ping(_params):
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
        "work_part": (
            getattr(work, "Leaf", None)
            if work is not None and getattr(work, "Tag", 0) != 0
            else None
        ),
        "log": LOG_PATH,
        "token_required": bool(TOKEN),
    }


def _op_part_summary(params):
    work = _work_part()
    max_features = int(params.get("max_features", 100))
    if not 1 <= max_features <= 1000:
        raise ValueError("max_features must be between 1 and 1000")

    bodies = list(work.Bodies)
    features = []
    total_features = 0
    for feature in work.Features:
        total_features += 1
        if len(features) < max_features:
            features.append(
                {
                    "name": getattr(feature, "Name", None),
                    "journal_id": getattr(feature, "JournalIdentifier", None),
                }
            )
    return {
        "ok": True,
        "name": getattr(work, "Leaf", None),
        "full_path": getattr(work, "FullPath", None),
        "tag": int(work.Tag),
        "body_count": len(bodies),
        "feature_count": total_features,
        "features": features,
        "features_truncated": total_features > len(features),
    }


def _op_create_part(params):
    file_name = params.get("file_name")
    if not isinstance(file_name, str) or not file_name.strip():
        raise ValueError("file_name must be a non-empty string")
    file_name = file_name.strip()
    if os.path.basename(file_name) != file_name or file_name in (".", ".."):
        raise ValueError("file_name must be a plain file name, not a path")
    if not file_name.lower().endswith(".prt"):
        file_name += ".prt"
    units_name = str(params.get("units", "millimeters")).strip().lower()
    if units_name in ("millimeter", "millimeters", "mm"):
        units = NXOpen.Part.Units.Millimeters
    elif units_name in ("inch", "inches", "in"):
        units = NXOpen.Part.Units.Inches
    else:
        raise ValueError("units must be 'millimeters' or 'inches'")

    os.makedirs(WORKSPACE, exist_ok=True)
    path = os.path.abspath(os.path.join(WORKSPACE, file_name))
    if os.path.commonpath([WORKSPACE, path]) != WORKSPACE:
        raise ValueError("part path escapes NX_MCP_WORKSPACE")
    if os.path.exists(path):
        raise FileExistsError("part already exists: %s" % path)
    part = NXOpen.Session.GetSession().Parts.NewDisplay(path, units)
    return {
        "ok": True,
        "name": getattr(part, "Leaf", None),
        "full_path": getattr(part, "FullPath", path),
        "tag": int(part.Tag),
        "units": units_name,
        "workspace": WORKSPACE,
    }


def _op_save_work_part(_params):
    work = _work_part()
    status = work.Save(
        NXOpen.BasePart.SaveComponents.TrueValue,
        NXOpen.BasePart.CloseAfterSave.FalseValue,
    )
    try:
        unsaved = getattr(status, "NumberUnsavedParts", None)
    finally:
        status.Dispose()
    path = getattr(work, "FullPath", None)
    return {
        "ok": True,
        "name": getattr(work, "Leaf", None),
        "full_path": path,
        "number_unsaved_parts": unsaved,
        "file_exists": bool(path and os.path.isfile(path)),
        "file_size": os.path.getsize(path) if path and os.path.isfile(path) else None,
    }


def _finite_positive(name, value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("%s must be finite and greater than zero" % name)
    return value


def _op_create_block(params):
    length = _finite_positive("length", params.get("length", 100.0))
    width = _finite_positive("width", params.get("width", 60.0))
    height = _finite_positive("height", params.get("height", 40.0))
    origin = params.get("origin", [0.0, 0.0, 0.0])
    if not isinstance(origin, (list, tuple)) or len(origin) != 3:
        raise ValueError("origin must contain exactly three coordinates")
    origin = [float(item) for item in origin]
    if not all(math.isfinite(item) for item in origin):
        raise ValueError("origin coordinates must be finite")

    work = _work_part()
    session = NXOpen.Session.GetSession()
    mark = session.SetUndoMark(
        NXOpen.Session.MarkVisibility.Visible, "MCP create block"
    )
    builder = work.Features.CreateBlockFeatureBuilder(NXOpen.Features.Feature.Null)
    try:
        builder.Type = NXOpen.Features.BlockFeatureBuilder.Types.OriginAndEdgeLengths
        point = NXOpen.Point3d(origin[0], origin[1], origin[2])
        builder.SetOriginAndLengths(point, str(length), str(width), str(height))
        builder.SetBooleanOperationAndTarget(
            NXOpen.Features.Feature.BooleanType.Create, NXOpen.Body.Null
        )
        feature = builder.CommitFeature()
        session.SetUndoMarkName(mark, "MCP create block")
    finally:
        builder.Destroy()

    return {
        "ok": True,
        "feature": feature.JournalIdentifier,
        "name": feature.Name,
        "part": getattr(work, "Leaf", None),
        "length": length,
        "width": width,
        "height": height,
        "origin": origin,
        "body_count": len(list(work.Bodies)),
    }


def _op_execute(params):
    code = params.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("params.code must be a non-empty string")

    session = NXOpen.Session.GetSession()
    _EXEC_NS.update(
        {
            "NXOpen": NXOpen,
            "session": session,
            "theSession": session,
            "workPart": session.Parts.Work,
            "displayPart": session.Parts.Display,
        }
    )
    _EXEC_NS.pop("result", None)

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
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
    if len(err) > MAX_OUTPUT_CHARS:
        err = err[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
    return {
        "ok": True,
        "return_value": _jsonable(returned),
        "stdout": out,
        "stderr": err,
    }


_OPS = {
    "ping": _op_ping,
    "part_summary": _op_part_summary,
    "create_part": _op_create_part,
    "create_block": _op_create_block,
    "save_work_part": _op_save_work_part,
    "execute": _op_execute,
}


def _handle_connection(conn):
    global _PROCESSED
    request_id = None
    try:
        conn.settimeout(30.0)
        message = _recv(conn)
        request_id = message.get("id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request.id must be a non-empty string")
        if TOKEN:
            supplied = message.get("token")
            if not isinstance(supplied, str) or not hmac.compare_digest(TOKEN, supplied):
                raise PermissionError("invalid NX_MCP_TOKEN")
        method = message.get("method")
        if not isinstance(method, str) or not method:
            raise ValueError("request.method must be a non-empty string")
        params = message.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("request.params must be a JSON object")
        _log("request method=%s id=%s" % (method, request_id))

        if method == "stop":
            _STOP.set()
            result = {"ok": True, "message": "stop accepted"}
        else:
            operation = _OPS.get(method)
            if operation is None:
                raise ValueError("unknown method: %r" % method)
            result = operation(params)
            _PROCESSED += 1
        _send(conn, {"id": request_id, "ok": True, "result": result})
    except Exception as exc:
        details = traceback.format_exc()
        _log("error id=%s: %s\n%s" % (request_id, exc, details))
        try:
            _send(
                conn,
                {
                    "id": request_id,
                    "ok": False,
                    "error": {
                        "message": str(exc),
                        "type": "%s.%s"
                        % (type(exc).__module__, type(exc).__name__),
                        "traceback": details,
                    },
                },
            )
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def serve_blocking():
    """Serve requests on the calling NX journal thread until `stop` arrives."""
    global _SERVER, _START_TIME
    if _SERVER is not None:
        _announce("NX MCP bridge is already running on %s:%s" % (HOST, PORT))
        return

    _STOP.clear()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((HOST, PORT))
    listener.listen(8)
    listener.setblocking(False)
    _SERVER = listener
    _START_TIME = time.time()
    _announce(
        "NX MCP bridge %s listening on %s:%s (log: %s)"
        % (__version__, HOST, PORT, LOG_PATH)
    )
    _log("serve_blocking start on thread %s" % threading.current_thread().name)
    try:
        while not _STOP.is_set():
            try:
                ready, _, _ = select.select([listener], [], [], 0.05)
            except (OSError, ValueError):
                break
            if ready:
                try:
                    conn, _address = listener.accept()
                except OSError:
                    continue
                _handle_connection(conn)
    finally:
        try:
            listener.close()
        finally:
            _SERVER = None
        _announce("NX MCP bridge stopped.")
        _log("serve_blocking exited")


def stop_serving():
    _STOP.set()


def main(args=None):
    serve_blocking()


if __name__ == "__main__":
    main()
