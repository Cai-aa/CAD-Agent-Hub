"""Deadline-bounded Windows pipe I/O, with no worker threads or automatic retry."""
from __future__ import annotations

import struct
import time


def exchange(pipe_name: str, body: bytes, timeout: float, max_frame: int) -> bytes:
    import pywintypes
    try:
        return _exchange(pipe_name, body, timeout, max_frame)
    except pywintypes.error as exc:
        raise OSError(exc.winerror, exc.strerror) from exc


def _exchange(pipe_name: str, body: bytes, timeout: float, max_frame: int) -> bytes:
    import pywintypes
    import win32con
    import win32event
    import win32file

    deadline = time.monotonic() + timeout
    handle = win32file.CreateFile('\\\\.\\pipe\\' + pipe_name,
                                win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                0, None, win32con.OPEN_EXISTING,
                                win32con.FILE_FLAG_OVERLAPPED, None)

    def transfer(data, writing=False):
        event = win32event.CreateEvent(None, True, False, None)
        overlap = pywintypes.OVERLAPPED()
        overlap.hEvent = event
        pending = False
        try:
            if writing:
                status, buffer = win32file.WriteFile(handle, data, overlap)
            else:
                status, buffer = win32file.ReadFile(handle, data, overlap)
            pending = status == 997  # ERROR_IO_PENDING
            if pending:
                remaining = max(0, int((deadline - time.monotonic()) * 1000))
                if win32event.WaitForSingleObject(event, remaining) != win32event.WAIT_OBJECT_0:
                    # Keep the OVERLAPPED and buffers alive until cancellation completes.
                    win32file.CancelIo(handle)  # This thread owns the only pending I/O on this handle.
                    try:
                        win32file.GetOverlappedResult(handle, overlap, True)
                    except pywintypes.error:
                        pass
                    pending = False
                    raise TimeoutError('Bridge deadline expired; do not automatically retry a mutation')
            count = win32file.GetOverlappedResult(handle, overlap, False)
            pending = False
            if count == 0:
                raise EOFError('Bridge disconnected')
            return count if writing else bytes(buffer[:count])
        finally:
            if pending:
                try:
                    win32file.CancelIo(handle)
                    win32file.GetOverlappedResult(handle, overlap, True)
                except pywintypes.error:
                    pass
            event.Close()

    def read_exact(size):
        output = bytearray()
        while len(output) < size:
            if time.monotonic() >= deadline:
                raise TimeoutError('Bridge response deadline expired')
            output.extend(transfer(size - len(output)))
        return bytes(output)

    try:
        frame = struct.pack('<I', len(body)) + body
        sent = 0
        while sent < len(frame):
            if time.monotonic() >= deadline:
                raise TimeoutError('Bridge request deadline expired; outcome may be unknown')
            sent += transfer(frame[sent:], writing=True)
        size = struct.unpack('<I', read_exact(4))[0]
        if not 1 <= size <= max_frame:
            raise ValueError('Invalid bridge response length')
        return read_exact(size)
    finally:
        handle.Close()
