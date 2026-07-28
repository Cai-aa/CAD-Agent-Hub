from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
