import os
import struct
import threading
import time
import uuid

import pytest

from eplan_mcp.transport import exchange

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows named-pipe integration')


def server(reply, stall=False):
    import pywintypes
    import win32file
    import win32pipe
    name = 'eplan-mcp-123-' + uuid.uuid4().hex
    handle = win32pipe.CreateNamedPipe('\\\\.\\pipe\\' + name,
        win32pipe.PIPE_ACCESS_DUPLEX, win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT, 1, 8192, 8192, 0, None)
    done = threading.Event()
    received = []
    failures = []
    def run():
        try:
            try:
                win32pipe.ConnectNamedPipe(handle, None)
            except pywintypes.error as e:
                if e.winerror != 535:
                    raise
            _, header = win32file.ReadFile(handle, 4)
            count = struct.unpack('<I', header)[0]
            _, body = win32file.ReadFile(handle, count)
            received.append(body)
            if stall:
                done.wait(2)
            else:
                win32file.WriteFile(handle, struct.pack('<I', len(reply)) + reply)
                win32file.FlushFileBuffers(handle)
        except Exception as exc:
            failures.append(exc)
        finally:
            handle.Close()
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return name, done, thread, received, failures


def test_real_windows_framing_and_utf8():
    expected = '中文原生数据'.encode('utf-8')
    name, done, thread, received, failures = server(expected)
    try:
        assert exchange(name, b'{"operation":"hello"}', 2, 4194304) == expected
    finally:
        done.set()
        thread.join(3)
    assert not thread.is_alive() and not failures
    assert received == [b'{"operation":"hello"}']


def test_real_windows_stalled_response_has_bounded_deadline():
    name, done, thread, received, failures = server(b'', stall=True)
    start = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            exchange(name, b'query', .15, 4194304)
    finally:
        done.set()
        thread.join(3)
    assert time.monotonic() - start < 2
    assert not thread.is_alive() and not failures and received == [b'query']
