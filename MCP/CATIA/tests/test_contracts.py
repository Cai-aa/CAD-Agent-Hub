from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catia_mcp.contracts import ContractError, require_positive, require_safe_name, resolve_within


class ContractTests(unittest.TestCase):
    def test_positive_rejects_boolean_and_zero(self) -> None:
        for value in (True, False, 0, -1):
            with self.assertRaises(ContractError):
                require_positive(value, "value")

    def test_safe_name_rejects_path_characters(self) -> None:
        with self.assertRaises(ContractError):
            require_safe_name("bad/name")

    def test_resolve_within_blocks_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = resolve_within(root / "model.CATPart", (root,))
            self.assertEqual(allowed, (root / "model.CATPart").resolve())
            with self.assertRaises(ContractError):
                resolve_within(root.parent / "escape.CATPart", (root,))


if __name__ == "__main__":
    unittest.main()
