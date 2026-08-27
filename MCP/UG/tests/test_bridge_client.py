from __future__ import annotations

import json
import socket
import threading
import unittest

from nx_bridge_client import (
    BridgeProtocolError,
    BridgeRemoteError,
    NXBridgeClient,
)


class OneShotBridge:
    def __init__(self, responder):
        self.responder = responder
        self.request = None
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        conn, _ = self.listener.accept()
        with conn:
            data = bytearray()
            while b"\n" not in data:
                data.extend(conn.recv(4096))
            self.request = json.loads(bytes(data).split(b"\n", 1)[0].decode("utf-8"))
            payload = self.responder(self.request)
            if isinstance(payload, bytes):
                conn.sendall(payload)
            else:
                conn.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        self.listener.close()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.thread.join(timeout=2)
        self.listener.close()


class NXBridgeClientTests(unittest.TestCase):
    def test_success_and_token(self):
        def respond(request):
            return {"id": request["id"], "ok": True, "result": {"pong": True}}

        with OneShotBridge(respond) as bridge:
            client = NXBridgeClient(port=bridge.port, timeout=2, token="secret", transport="tcp")
            self.assertEqual({"pong": True}, client.request("ping"))
        self.assertEqual("secret", bridge.request["token"])
        self.assertEqual("ping", bridge.request["method"])

    def test_remote_error_preserves_type(self):
        def respond(request):
            return {
                "id": request["id"],
                "ok": False,
                "error": {"message": "no work part", "type": "builtins.RuntimeError"},
            }

        with OneShotBridge(respond) as bridge:
            client = NXBridgeClient(port=bridge.port, timeout=2, transport="tcp")
            with self.assertRaisesRegex(BridgeRemoteError, "no work part"):
                client.request("part_summary")

    def test_mismatched_id_is_rejected(self):
        with OneShotBridge(
            lambda _request: {"id": "wrong", "ok": True, "result": {}}
        ) as bridge:
            client = NXBridgeClient(port=bridge.port, timeout=2, transport="tcp")
            with self.assertRaisesRegex(BridgeProtocolError, "mismatched"):
                client.request("ping")

    def test_invalid_json_is_rejected(self):
        with OneShotBridge(lambda _request: b"not-json\n") as bridge:
            client = NXBridgeClient(port=bridge.port, timeout=2, transport="tcp")
            with self.assertRaisesRegex(BridgeProtocolError, "invalid UTF-8 JSON"):
                client.request("ping")

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 65535"):
            NXBridgeClient(port=0, transport="tcp")
        with self.assertRaisesRegex(ValueError, "at least 1024"):
            NXBridgeClient(max_response_bytes=100, transport="tcp")


if __name__ == "__main__":
    unittest.main()
