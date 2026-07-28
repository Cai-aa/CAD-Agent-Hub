from __future__ import annotations

import queue
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable


class SolidWorksUnavailable(RuntimeError):
    pass


@dataclass
class _Request:
    function: Callable[[], Any]
    future: Future[Any]


class StaExecutor:
    """The only component allowed to touch COM.

    SolidWorks is a single-threaded COM application. A dedicated STA thread avoids
    interleaved calls from concurrent MCP requests and makes state transitions
    deterministic. The queue is also the natural place to add timeouts/retries.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[_Request | None] = queue.Queue()
        self._busy = threading.Event()
        self._active_started_at: float | None = None
        self._thread = threading.Thread(target=self._run, name="solidworks-sta", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            import pythoncom  # type: ignore
        except ImportError:
            pythoncom = None
        if pythoncom:
            pythoncom.CoInitialize()
        try:
            while (request := self._queue.get()) is not None:
                if request.future.set_running_or_notify_cancel():
                    self._busy.set()
                    self._active_started_at = time.monotonic()
                    try:
                        request.future.set_result(request.function())
                    except Exception as exc:  # pass COM details back as structured errors
                        request.future.set_exception(exc)
                    finally:
                        self._active_started_at = None
                        self._busy.clear()
        finally:
            if pythoncom:
                pythoncom.CoUninitialize()

    def call(
        self,
        function: Callable[[], Any],
        timeout: float = 90,
        *,
        reject_if_busy: bool = False,
    ) -> Any:
        if reject_if_busy and (self._busy.is_set() or not self._queue.empty()):
            raise RuntimeError(
                "SolidWorks is still processing the previous COM operation; "
                "the new request was not queued"
            )
        future: Future[Any] = Future()
        self._queue.put(_Request(function, future))
        return future.result(timeout=timeout)

    def status(self) -> dict[str, Any]:
        elapsed = (
            None
            if self._active_started_at is None
            else max(0.0, time.monotonic() - self._active_started_at)
        )
        return {
            "busy": self._busy.is_set(),
            "active_elapsed_seconds": elapsed,
            "queued_requests": self._queue.qsize(),
            "worker_alive": self._thread.is_alive(),
        }

    def close(self, timeout: float = 5.0) -> None:
        self._queue.put(None)
        self._thread.join(timeout=timeout)


class SolidWorksSession:
    """Connection, document state and idempotency cache owned by the STA executor."""

    def __init__(self, cache_size: int = 128, operation_timeout_seconds: float = 180.0) -> None:
        self._sta = StaExecutor()
        self._application: Any | None = None
        self._state_version = 0
        self._cache_size = cache_size
        self._operation_timeout_seconds = operation_timeout_seconds
        self._completed: OrderedDict[str, dict[str, Any]] = OrderedDict()

    @property
    def state_version(self) -> int:
        return self._state_version

    def _connect_in_sta(self, visible: bool, start_if_missing: bool) -> dict[str, Any]:
        try:
            import win32com.client  # type: ignore
        except ImportError as exc:
            raise SolidWorksUnavailable("pywin32 is unavailable; install requirements.txt") from exc
        try:
            app = win32com.client.GetActiveObject("SldWorks.Application")
            connection = "attached"
        except Exception:
            if not start_if_missing:
                raise SolidWorksUnavailable(
                    "No registered running SolidWorks instance was found. Start SolidWorks manually, "
                    "or call solidworks_connect(start_if_missing=true) once."
                )
            try:
                # DispatchEx guarantees a fresh local COM server after the ROT
                # lookup failed. Showing it immediately prevents an interrupted
                # startup from leaving an invisible -Embedding process behind.
                dispatch = getattr(win32com.client, "DispatchEx", win32com.client.Dispatch)
                app = dispatch("SldWorks.Application")
                app.Visible = visible
                connection = "launched"
            except Exception as exc:
                raise SolidWorksUnavailable(
                    "Could not create SldWorks.Application. Install/licence SolidWorks and start it once."
                ) from exc
        # Dispatch returns before SolidWorks has always completed startup. Wait for
        # the automation interface to answer before accepting work, otherwise later
        # file imports may block in an invisible not-yet-ready application.
        deadline = time.monotonic() + 60
        while True:
            try:
                revision_member = getattr(app, "RevisionNumber", "unknown")
                revision = revision_member() if callable(revision_member) else revision_member
                break
            except Exception as exc:
                if time.monotonic() >= deadline:
                    if connection == "launched":
                        try:
                            exit_member = getattr(app, "ExitApp", None)
                            if callable(exit_member):
                                exit_member()
                        except Exception:
                            pass
                    raise SolidWorksUnavailable("SolidWorks did not become automation-ready within 60 seconds") from exc
                time.sleep(0.5)
        app.Visible = visible
        self._application = app
        return {"connection": connection, "revision": str(revision), "state_version": self._state_version}

    def connect(self, visible: bool, start_if_missing: bool = False) -> dict[str, Any]:
        return self._sta.call(
            lambda: self._connect_in_sta(visible, start_if_missing),
            timeout=self._operation_timeout_seconds,
            reject_if_busy=True,
        )

    def execute(self, request_id: str, action: Callable[[Any], dict[str, Any]]) -> dict[str, Any]:
        """Execute exactly once per request_id and return cached success on retries."""
        def run() -> dict[str, Any]:
            if request_id in self._completed:
                return {**self._completed[request_id], "idempotent_replay": True}
            if self._application is None:
                self._connect_in_sta(True, start_if_missing=False)
            result = action(self._application)
            self._state_version += 1
            envelope = {**result, "state_version": self._state_version, "idempotent_replay": False}
            self._completed[request_id] = envelope
            self._completed.move_to_end(request_id)
            while len(self._completed) > self._cache_size:
                self._completed.popitem(last=False)
            return envelope
        try:
            return self._sta.call(
                run,
                timeout=self._operation_timeout_seconds,
                reject_if_busy=True,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"SolidWorks operation exceeded {self._operation_timeout_seconds:g} seconds; "
                "the serialized COM transaction is still being allowed to finish or roll back"
            ) from exc

    def close(self) -> None:
        self._application = None
        self._sta.close()

    def status(self) -> dict[str, Any]:
        return {
            **self._sta.status(),
            "connected": self._application is not None,
            "state_version": self._state_version,
            "completed_request_cache_size": len(self._completed),
        }
