from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

from .compatibility import CatiaInstallation, choose_installation, discover_installations
from .config import Settings


class CatiaUnavailable(RuntimeError):
    pass


@dataclass
class _Request:
    function: Callable[[], Any]
    future: Future[Any]


class StaExecutor:
    """Serialize all CATIA COM access on one dedicated STA thread."""

    def __init__(self) -> None:
        self._queue: queue.Queue[_Request | None] = queue.Queue()
        self._busy = threading.Event()
        self._active_started_at: float | None = None
        self._thread = threading.Thread(target=self._run, name="catia-sta", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            import pythoncom  # type: ignore
        except ImportError:
            pythoncom = None
        if pythoncom:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        try:
            while (request := self._queue.get()) is not None:
                if not request.future.set_running_or_notify_cancel():
                    continue
                self._busy.set()
                self._active_started_at = time.monotonic()
                result: Any = None
                error: Exception | None = None
                try:
                    result = request.function()
                except Exception as exc:
                    error = exc
                finally:
                    if pythoncom:
                        pythoncom.PumpWaitingMessages()
                    self._active_started_at = None
                    self._busy.clear()
                # Publish completion only after the busy flag is cleared. Otherwise
                # the awakened caller can race the worker's finally block and have
                # its next sequential operation rejected as still busy.
                if error is not None:
                    request.future.set_exception(error)
                else:
                    request.future.set_result(result)
        finally:
            if pythoncom:
                pythoncom.CoUninitialize()

    def call(self, function: Callable[[], Any], timeout: float, *, reject_if_busy: bool = False) -> Any:
        if reject_if_busy and (self._busy.is_set() or not self._queue.empty()):
            raise RuntimeError(
                "CATIA is still processing the previous COM operation. "
                "Do not retry or queue another export; call catia_operation_status "
                "and inspect the target path before deciding the next action."
            )
        future: Future[Any] = Future()
        self._queue.put(_Request(function, future))
        return future.result(timeout=timeout)

    def status(self) -> dict[str, Any]:
        elapsed = None if self._active_started_at is None else time.monotonic() - self._active_started_at
        busy = self._busy.is_set()
        queued_requests = self._queue.qsize()
        return {
            "busy": busy,
            "active_elapsed_seconds": elapsed,
            "queued_requests": queued_requests,
            "worker_alive": self._thread.is_alive(),
            "retry_allowed": not busy and queued_requests == 0,
        }

    def close(self, timeout: float = 5.0) -> None:
        self._queue.put(None)
        self._thread.join(timeout=timeout)


class CatiaSession:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._sta = StaExecutor()
        self._application: Any | None = None
        self._state_version = 0
        self._completed: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._last_timeout: dict[str, Any] | None = None

    @staticmethod
    def _get_active() -> Any:
        import win32com.client  # type: ignore

        errors: list[str] = []
        for progid in ("CATIA.Application", "CATIA.Application.1"):
            try:
                return win32com.client.GetActiveObject(progid)
            except Exception as exc:
                errors.append(f"{progid}: {exc}")
        raise CatiaUnavailable("No CATIA Automation object is published in this process ROT. " + " | ".join(errors))

    def _selected_installation(self) -> CatiaInstallation | None:
        return choose_installation(self.settings, discover_installations(self.settings))

    def _launch_selected(self) -> subprocess.Popen[Any] | None:
        selected = self._selected_installation()
        if selected and selected.release_index is not None:
            if (
                selected.release_index < self.settings.minimum_supported_release_index
                and not self.settings.allow_legacy_release
            ):
                raise CatiaUnavailable(
                    f"{selected.release_label} is below the configured support floor B"
                    f"{self.settings.minimum_supported_release_index}. Set CATIA_MCP_ALLOW_LEGACY=true "
                    "only for an explicit best-effort trial."
                )
        if selected and selected.components.get("catstart"):
            executable = selected.install_path / "code" / "bin" / "CATSTART.exe"
            args = [
                str(executable),
                "-run",
                "CNEXT.exe",
                "-env",
                selected.environment_name,
                "-direnv",
                str(selected.environment_file.parent),
            ]
            return subprocess.Popen(args, close_fds=True)
        return None

    @staticmethod
    def _application_info(app: Any, connection: str) -> dict[str, Any]:
        def safe(name: str, default: Any = None) -> Any:
            try:
                member = getattr(app, name)
                return member() if callable(member) else member
            except Exception:
                return default

        workbench = None
        try:
            workbench = app.GetWorkbenchId()
        except Exception:
            pass
        active_document = None
        try:
            active_document = app.ActiveDocument.Name if app.Documents.Count else None
        except Exception:
            pass
        documents_object = safe("Documents")
        try:
            document_count = int(documents_object.Count) if documents_object is not None else None
        except Exception:
            document_count = None
        return {
            "connection": connection,
            "name": safe("Name"),
            "caption": safe("Caption"),
            "full_name": safe("FullName"),
            "path": safe("Path"),
            "visible": bool(safe("Visible", False)),
            "documents": document_count,
            "active_document": active_document,
            "workbench": workbench,
        }

    def _connect_in_sta(self, start_if_missing: bool) -> dict[str, Any]:
        try:
            import win32com.client  # type: ignore
        except ImportError as exc:
            raise CatiaUnavailable("pywin32 is unavailable; install the project dependencies") from exc
        try:
            app = self._get_active()
            connection = "attached"
        except CatiaUnavailable as attach_error:
            if not start_if_missing:
                raise attach_error
            launched = self._launch_selected()
            deadline = time.monotonic() + self.settings.startup_timeout_seconds
            app = None
            while time.monotonic() < deadline:
                try:
                    app = self._get_active()
                    break
                except CatiaUnavailable:
                    time.sleep(0.5)
            if app is None:
                try:
                    dispatch = getattr(win32com.client, "DispatchEx", win32com.client.Dispatch)
                    app = dispatch("CATIA.Application")
                    connection = "launched_via_com_fallback"
                except Exception as exc:
                    if launched and launched.poll() is not None:
                        detail = f"CATSTART exited with code {launched.returncode}"
                    else:
                        detail = "CATSTART did not publish an Automation object"
                    raise CatiaUnavailable(f"Could not start CATIA: {detail}") from exc
            else:
                connection = "launched_via_environment"
        app.Visible = self.settings.visible
        self._application = app
        return {**self._application_info(app, connection), "state_version": self._state_version}

    def connect(self, start_if_missing: bool = False) -> dict[str, Any]:
        return self._sta.call(
            lambda: self._connect_in_sta(start_if_missing),
            timeout=self.settings.startup_timeout_seconds + 15,
            reject_if_busy=True,
        )

    def run(
        self,
        request_id: str,
        action: Callable[[Any], dict[str, Any]],
        *,
        mutating: bool = True,
    ) -> dict[str, Any]:
        def invoke() -> dict[str, Any]:
            if mutating and request_id in self._completed:
                return {**self._completed[request_id], "idempotent_replay": True}
            if self._application is None:
                self._connect_in_sta(start_if_missing=False)
            result = action(self._application)
            if mutating:
                self._state_version += 1
            envelope = {
                **result,
                "state_version": self._state_version,
                "idempotent_replay": False,
            }
            if mutating:
                self._completed[request_id] = envelope
                while len(self._completed) > self.settings.operation_cache_size:
                    self._completed.popitem(last=False)
            return envelope

        try:
            result = self._sta.call(
                invoke,
                timeout=self.settings.operation_timeout_seconds,
                reject_if_busy=True,
            )
            self._last_timeout = None
            return result
        except TimeoutError as exc:
            self._last_timeout = {
                "request_id": request_id,
                "at_unix_seconds": time.time(),
                "instruction": (
                    "Do not retry until retry_allowed is true; inspect the target "
                    "path before starting another export."
                ),
            }
            raise TimeoutError(
                f"CATIA operation exceeded {self.settings.operation_timeout_seconds:g} seconds. "
                "The serialized COM call may still be completing inside CATIA. "
                "Do not retry; call catia_operation_status and inspect the target path first."
            ) from exc

    def status(self) -> dict[str, Any]:
        return {
            **self._sta.status(),
            "connected": self._application is not None,
            "state_version": self._state_version,
            "completed_request_cache_size": len(self._completed),
            "last_timeout": self._last_timeout,
        }

    def close(self) -> None:
        self._application = None
        self._sta.close()
