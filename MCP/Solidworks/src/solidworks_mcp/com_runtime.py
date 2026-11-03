from __future__ import annotations
import copy
import contextvars
import math
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable
from .contracts import ContractError, require_text
from .safety import (
    CadProcessLock,
    OperationJournal,
    SafetyError,
    fingerprint,
    request_context,
)


class SolidWorksUnavailable(RuntimeError):
    pass


@dataclass
class _Request:
    function: Callable[[], Any]
    future: Future[Any]


class StaExecutor:
    """Atomic admission and shutdown. All COM cleanup stays on the owning STA."""

    def __init__(self):
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._pending, self._closed = 0, False
        self._busy = threading.Event()
        self._active_started_at = None
        self._thread = threading.Thread(
            target=self._run, name="solidworks-sta", daemon=True
        )
        self._thread.start()

    def _run(self):
        try:
            import pythoncom
        except ImportError:
            pythoncom = None
        if pythoncom:
            pythoncom.CoInitialize()
        try:
            while (request := self._queue.get()) is not None:
                try:
                    if request.future.set_running_or_notify_cancel():
                        self._busy.set()
                        self._active_started_at = time.monotonic()
                        result, error = None, None
                        try:
                            result = request.function()
                        except BaseException as exc:
                            error = exc
                finally:
                    with self._lock:
                        self._pending -= 1
                        self._active_started_at = None
                        self._busy.clear()
                if request.future.running():
                    if error is not None:
                        request.future.set_exception(error)
                    else:
                        request.future.set_result(result)
        finally:
            if pythoncom:
                pythoncom.CoUninitialize()

    def call(self, function, timeout=90, *, reject_if_busy=False):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ContractError("timeout must be finite and positive")
        future = Future()
        with self._lock:
            if self._closed:
                raise SafetyError("EXECUTOR_CLOSED", "STA executor is closed")
            if reject_if_busy and self._pending:
                raise SafetyError(
                    "CAD_BUSY",
                    "SolidWorks is still processing the previous COM operation; the new request was not queued",
                )
            self._pending += 1
            context = contextvars.copy_context()
            self._queue.put(_Request(lambda: context.run(function), future))
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()  # Cannot cancel a running COM operation.
            raise

    def status(self):
        with self._lock:
            started = self._active_started_at
            return {
                "busy": self._pending > 0,
                "active_elapsed_seconds": None
                if started is None
                else time.monotonic() - started,
                "queued_requests": max(0, self._pending - int(self._busy.is_set())),
                "worker_alive": self._thread.is_alive(),
                "closed": self._closed,
            }

    def close(self, timeout=5.0, cleanup=None):
        with self._lock:
            if self._pending:
                raise SafetyError(
                    "CAD_BUSY",
                    "Cannot close or replace an executor while an operation is running",
                )
            if not self._closed:
                self._closed = True
                if cleanup:
                    self._pending += 1
                    self._queue.put(_Request(cleanup, Future()))
                self._queue.put(None)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise SafetyError(
                "CLOSE_INCOMPLETE", "STA did not terminate; replacement is forbidden"
            )


class SolidWorksSession:
    def __init__(
        self, cache_size=128, operation_timeout_seconds=180.0, journal_path=None
    ):
        self._journal = OperationJournal(journal_path)
        self._sta = StaExecutor()
        self._application, self._state_version = None, 0
        self._operation_timeout_seconds = operation_timeout_seconds
        self._last_request_id = None

    @property
    def state_version(self):
        return self._state_version

    def _connect_in_sta(self, visible, start_if_missing):
        try:
            import win32com.client
        except ImportError as exc:
            raise SolidWorksUnavailable("pywin32 is unavailable") from exc
        if self._application is not None:
            app, connection = self._application, "attached"
        else:
            try:
                app = win32com.client.GetActiveObject("SldWorks.Application")
                connection = "attached"
            except Exception:
                if not start_if_missing:
                    raise SolidWorksUnavailable(
                        "No registered running SolidWorks instance. Start it or call connect(start_if_missing=true)."
                    )
                app = win32com.client.DispatchEx("SldWorks.Application")
                app.Visible = visible
                connection = "launched"
        deadline = time.monotonic() + 60
        while True:
            try:
                member = getattr(app, "RevisionNumber")
                revision = member() if callable(member) else member
                break
            except Exception as exc:
                if time.monotonic() >= deadline:
                    raise SolidWorksUnavailable(
                        "SolidWorks was not automation-ready within 60 seconds"
                    ) from exc
                time.sleep(0.5)
        app.Visible = visible
        self._application = app
        return {
            "connection": connection,
            "revision": str(revision),
            "state_version": self._state_version,
        }

    def connect(self, visible, start_if_missing=False):
        def run():
            with CadProcessLock():
                return self._connect_in_sta(visible, start_if_missing)

        return self._sta.call(
            run, timeout=self._operation_timeout_seconds, reject_if_busy=True
        )

    def execute(
        self, request_id, action, *, operation=None, parameters=None, mutating=True
    ):
        request_id = require_text(request_id, "request_id")
        if len(request_id) > 200:
            raise ContractError("request_id exceeds 200 characters")
        context = request_context.get()
        if context:
            operation, parameters, mutating = (
                context["operation"],
                context["parameters"],
                context["mutating"],
            )
        if not operation:
            raise ContractError(
                "Direct session calls require an explicit operation name and parameters"
            )
        digest = fingerprint(operation, parameters or {})

        def run():
            with CadProcessLock():
                if not mutating:
                    if self._application is None:
                        self._connect_in_sta(True, False)
                    result = action(self._application)
                    return {
                        **result,
                        "state_version": self._state_version,
                        "idempotent_replay": False,
                    }
                previous = self._journal.get(request_id)
                if previous:
                    if previous["fingerprint"] != digest:
                        raise SafetyError(
                            "REQUEST_CONFLICT",
                            "request_id was used with another operation, document or parameter set",
                        )
                    if previous["state"] == "SUCCEEDED":
                        return {
                            **copy.deepcopy(previous["result"]),
                            "idempotent_replay": True,
                        }
                    raise SafetyError(
                        "REQUEST_NOT_RETRYABLE",
                        "Previous request failed or has an unknown outcome; inspect it before using a new ID",
                        request_id=request_id,
                        state=previous["state"],
                        error=previous.get("error"),
                    )
                if self._application is None:
                    self._connect_in_sta(True, False)
                record = {
                    "operation": operation,
                    "fingerprint": digest,
                    "state": "RUNNING",
                    "mutating": mutating,
                }
                self._journal.put(request_id, record)
                self._last_request_id = request_id
                try:
                    result = action(self._application)
                    if result.get("ok") is False:
                        raise SafetyError(
                            "OPERATION_FAILED",
                            "Operation returned ok=false",
                            result=result,
                        )
                    if mutating:
                        self._state_version += 1
                    envelope = {
                        **result,
                        "state_version": self._state_version,
                        "idempotent_replay": False,
                    }
                    self._journal.put(
                        request_id, {**record, "state": "SUCCEEDED", "result": envelope}
                    )
                    return copy.deepcopy(envelope)
                except BaseException as exc:
                    if mutating:
                        self._state_version += 1
                    self._journal.put(
                        request_id,
                        {
                            **record,
                            "state": "FAILED",
                            "error": str(exc),
                            "error_code": getattr(exc, "code", type(exc).__name__),
                        },
                    )
                    raise

        try:
            return self._sta.call(
                run, timeout=self._operation_timeout_seconds, reject_if_busy=True
            )
        except TimeoutError as exc:
            raise SafetyError(
                "OPERATION_TIMEOUT",
                "COM may still be running; query this request_id and do not issue a replacement",
                request_id=request_id,
                outcome="UNKNOWN_OR_RUNNING",
            ) from exc

    def operation_result(self, request_id):
        record = self._journal.get(require_text(request_id, "request_id"))
        if record is None:
            return {"request_id": request_id, "state": "NOT_FOUND"}
        record = copy.deepcopy(record)
        if record["state"] == "RUNNING" and not self._sta.status()["busy"]:
            record["state"] = "UNKNOWN"
        return {"request_id": request_id, **record}

    def close(self):
        def cleanup():
            self._application = None

        self._sta.close(cleanup=cleanup)

    def status(self):
        return {
            **self._sta.status(),
            "connected": self._application is not None,
            "state_version": self._state_version,
            "last_request_id": self._last_request_id,
            "journal_persistent": self._journal.path is not None,
        }
