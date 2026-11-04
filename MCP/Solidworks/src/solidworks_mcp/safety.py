"""Request identity, durable outcomes and cooperative COM exclusion."""

from __future__ import annotations
import contextlib
import contextvars
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any
from .contracts import ContractError


class SafetyError(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code, self.details = code, details


READ_OPERATIONS = {
    "list_documents",
    "get_bounding_box",
    "get_mass_properties",
    "capture_view",
    "list_configurations",
    "get_custom_properties",
    "list_material_databases",
    "get_material",
    "inspect_active",
    "inspect_relations",
    "bind_document",
    "activate_document",
}
request_context = contextvars.ContextVar("sw_request", default=None)
document_context = contextvars.ContextVar("sw_document", default=None)


@contextlib.contextmanager
def expected_document(token):
    reset = document_context.set(token)
    try:
        yield
    finally:
        document_context.reset(reset)


def request_operation(function):
    signature = inspect.signature(function)

    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        token = kwargs.pop("document_token", document_context.get())
        with expected_document(token):
            if request_context.get() is not None:
                return function(*args, **kwargs)
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            params = {
                k: v
                for k, v in bound.arguments.items()
                if k not in {"self", "request_id"}
            }
            params["document_token"] = token
            op = function.__name__
            mutating = (
                bool(params.get("perform_rebuild"))
                if op == "rebuild_diagnostics"
                else op not in READ_OPERATIONS
            )
            reset = request_context.set(
                {"operation": op, "parameters": params, "mutating": mutating}
            )
            try:
                return function(*args, **kwargs)
            finally:
                request_context.reset(reset)

    return wrapped


def fingerprint(operation, parameters):
    try:
        encoded = json.dumps(
            [operation, parameters],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"Request must contain finite JSON values: {exc}") from exc
    if len(encoded) > 4_000_000:
        raise ContractError("Request exceeds the 4 MB operation budget")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def same_com_object(first, second):
    if first is None or second is None:
        return False
    if not hasattr(first, "_oleobj_") or not hasattr(second, "_oleobj_"):
        return first is second
    import pythoncom

    return first._oleobj_.QueryInterface(
        pythoncom.IID_IUnknown
    ) == second._oleobj_.QueryInterface(pythoncom.IID_IUnknown)


class OperationJournal:
    def __init__(self, path=None):
        self.path, self.memory = path, {}
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.closing(sqlite3.connect(path)) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                )
                db.commit()

    def get(self, request_id):
        if self.path is None:
            return self.memory.get(request_id)
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            row = db.execute(
                "SELECT payload FROM operations WHERE id=?", (request_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, request_id, record):
        record = {**record, "updated_at": time.time()}
        payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
        if self.path is None:
            self.memory[request_id] = json.loads(payload)
        else:
            with contextlib.closing(sqlite3.connect(self.path)) as db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute(
                    "INSERT OR REPLACE INTO operations VALUES (?, ?)",
                    (request_id, payload),
                )
                db.commit()


class CadProcessLock:
    """One cooperative lock per Windows account; unrelated UI is not isolated."""

    def __init__(self, path=None):
        base = (
            Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir()))
            / "SolidWorksAgentMCP"
        )
        self.path, self.stream = path or base / "cad.lock", None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise SafetyError(
                "CAD_BUSY", "Another patched MCP process owns the CAD execution lock"
            ) from exc
        self.stream = stream
        return self

    def __exit__(self, *args):
        stream = self.stream
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_UN)
        finally:
            stream.close()
            self.stream = None
