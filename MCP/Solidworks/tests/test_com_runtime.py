from __future__ import annotations

import threading
import unittest

from solidworks_mcp.com_runtime import StaExecutor


class ComRuntimeTests(unittest.TestCase):
    def test_busy_executor_rejects_instead_of_queueing_retry(self) -> None:
        executor = StaExecutor()
        entered = threading.Event()
        release = threading.Event()
        completed: list[str] = []

        def slow_operation() -> str:
            entered.set()
            release.wait(timeout=2)
            completed.append("first")
            return "done"

        first_result: list[str] = []
        worker = threading.Thread(
            target=lambda: first_result.append(
                executor.call(slow_operation, timeout=2, reject_if_busy=True)
            )
        )
        worker.start()
        self.assertTrue(entered.wait(timeout=1))
        with self.assertRaisesRegex(RuntimeError, "was not queued"):
            executor.call(lambda: "second", timeout=1, reject_if_busy=True)
        self.assertEqual(executor.status()["queued_requests"], 0)
        release.set()
        worker.join(timeout=2)
        executor.close()
        self.assertEqual(first_result, ["done"])
        self.assertEqual(completed, ["first"])


if __name__ == "__main__":
    unittest.main()
