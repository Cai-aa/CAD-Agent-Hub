from __future__ import annotations

import unittest
import threading

from catia_mcp.com_runtime import StaExecutor


class RuntimeTests(unittest.TestCase):
    def test_sta_serializes_calls(self) -> None:
        executor = StaExecutor()
        try:
            order = []
            self.assertEqual(executor.call(lambda: order.append(1) or "one", 2), "one")
            self.assertEqual(executor.call(lambda: order.append(2) or "two", 2), "two")
            self.assertEqual(order, [1, 2])
            self.assertFalse(executor.status()["busy"])
        finally:
            executor.close()

    def test_busy_worker_rejects_retry_instead_of_queueing(self) -> None:
        executor = StaExecutor()
        started = threading.Event()
        release = threading.Event()
        errors = []

        def long_call() -> str:
            started.set()
            release.wait(2)
            return "done"

        def invoke() -> None:
            try:
                executor.call(long_call, 3)
            except Exception as exc:  # pragma: no cover - failure detail aid
                errors.append(exc)

        worker = threading.Thread(target=invoke)
        try:
            worker.start()
            self.assertTrue(started.wait(1))
            with self.assertRaisesRegex(RuntimeError, "Do not retry"):
                executor.call(lambda: "duplicate", 1, reject_if_busy=True)
            self.assertEqual(executor.status()["queued_requests"], 0)
            self.assertFalse(executor.status()["retry_allowed"])
            release.set()
            worker.join(2)
            self.assertEqual(errors, [])
            self.assertTrue(executor.status()["retry_allowed"])
        finally:
            release.set()
            worker.join(2)
            executor.close()


if __name__ == "__main__":
    unittest.main()
