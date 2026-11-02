"""Length-framed, local-only IPC client for the EPLAN add-in."""
from __future__ import annotations

import json
import os
import struct
import re
import ctypes
from ctypes import wintypes
from pathlib import Path
from .config import load_settings
from .transport import exchange

MAX_FRAME = 4 * 1024 * 1024
INSTANCE_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "EplanMcp" / "instances"
PIPE_PATTERN = re.compile(r'eplan-mcp-[1-9][0-9]*-[0-9a-f]{32}\Z')
READ_OPERATIONS = frozenset({
    'hello', 'list_projects', 'list_pages', 'list_functions',
    'trial_symbol_catalog', 'trial_connection_catalog', 'trial_asset_catalog',
    'trial_three_phase_catalog', 'trial_plc_audit', 'trial_terminal_audit',
    'trial_reference_inspect', 'trial_client_engineering_inspect', 'trial_curated_parts_inspect',
})


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


def _process_matches(data: dict) -> bool:
    if os.name != "nt":
        return False
    pid = data.get("pid")
    expected_exe = data.get("exe")
    expected_started = data.get("start_filetime_utc")
    if not isinstance(pid, int) or pid < 1 or not isinstance(expected_exe, str):
        return False
    try:
        expected_started = int(expected_started)
    except (TypeError, ValueError):
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        path_buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(path_buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, path_buffer, ctypes.byref(size)):
            return False
        started = _FileTime()
        exited, kernel_time, user_time = _FileTime(), _FileTime(), _FileTime()
        if not kernel.GetProcessTimes(handle, ctypes.byref(started), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return False
        actual_started = (started.high << 32) | started.low
        actual_exe = os.path.normcase(os.path.normpath(path_buffer.value))
        return actual_started == expected_started and actual_exe == os.path.normcase(os.path.normpath(expected_exe))
    finally:
        kernel.CloseHandle(handle)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _pipe_accepting(pipe_name: object) -> bool:
    if os.name != "nt" or not isinstance(pipe_name, str) or not PIPE_PATTERN.fullmatch(pipe_name):
        return False
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel.WaitNamedPipeW.restype = wintypes.BOOL
    return bool(kernel.WaitNamedPipeW("\\\\.\\pipe\\" + pipe_name, 100))


def discover() -> list[dict]:
    if not INSTANCE_DIR.is_dir():
        return []
    found = []
    for path in INSTANCE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
            if not isinstance(data, dict) or data.get("protocol") != 1:
                continue
            pid = data.get("pid")
            if not _process_matches(data) or not _pipe_accepting(data.get("pipe")):
                continue
            # Discovery files are hints, not authorization. The pipe handshake proves availability.
            found.append({"instance_id": data.get("instance_id"), "pid": pid,
                          "build": data.get("build"), "pipe": data.get("pipe"),
                          "trial_writes_enabled": data.get("trial_writes_enabled") is True,
                          "path": str(path)})
        except (OSError, ValueError, UnicodeError):
            continue
    return found


def request(instance_id: str, operation: str, payload: dict | None = None) -> dict:
    settings = load_settings()
    mutating = operation not in READ_OPERATIONS
    if mutating and settings.profile != 'trial':
        return {"ok": False, "error": {"code": "READ_ONLY_PROFILE", "message": "Configure the separate trial profile for bounded native writes"}}
    matches = [x for x in discover() if x["instance_id"] == instance_id]
    if len(matches) != 1:
        return {"ok": False, "error": {"code": "INSTANCE_NOT_FOUND", "message": "EPLAN bridge instance not found"}}
    if (operation.startswith("trial_") or operation == "prepare_trial_pages") and not matches[0]["trial_writes_enabled"]:
        return {"ok": False, "error": {"code": "TRIAL_INSTANCE_REQUIRED", "message": "Start a dedicated EPLAN trial instance; this process is not marked for trial operations"}}
    pipe = matches[0]["pipe"]
    if not isinstance(pipe, str) or not PIPE_PATTERN.fullmatch(pipe):
        return {"ok": False, "error": {"code": "INVALID_DISCOVERY", "message": "Invalid pipe name"}}
    if mutating:
        hello = request(instance_id, 'hello')
        if not hello.get('ok') or hello.get('data', {}).get('build') != settings.expected_build:
            return {'ok': False, 'error': {'code': 'NATIVE_BUILD_NOT_VERIFIED', 'message': 'No write: exact native build differs or handshake failed'}}
    body = json.dumps({"protocol": 1, "instance_id": instance_id,
                       "operation": operation, "payload": payload or {}},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise ValueError("request too large")
    try:
        raw = exchange(pipe, body, settings.timeout_seconds, MAX_FRAME)
        response = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_pairs)
        if not isinstance(response, dict) or type(response.get('ok')) is not bool:
            raise ValueError('Malformed bridge response envelope')
        return response
    except TimeoutError as exc:
        return {'ok': False, 'error': {'code': 'BRIDGE_TIMEOUT_OUTCOME_UNKNOWN' if mutating else 'BRIDGE_TIMEOUT',
                                     'message': str(exc), 'automatic_retry_allowed': False,
                                     'native_outcome_unknown': mutating}}
    except (OSError, ValueError, UnicodeError, EOFError) as exc:
        return {"ok": False, "error": {"code": "BRIDGE_NOT_CONNECTED", "message": str(exc),
                                      'automatic_retry_allowed': False, 'native_outcome_unknown': mutating}}


def _read_exact(stream, n: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < n:
        part = stream.read(n - len(chunks))
        if not part:
            raise EOFError("bridge disconnected")
        chunks.extend(part)
    return bytes(chunks)
