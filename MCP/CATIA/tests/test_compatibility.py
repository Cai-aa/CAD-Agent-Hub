from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from catia_mcp.compatibility import (
    parse_environment_file,
    release_index_from_path,
    release_label,
    support_tier,
)


class CompatibilityTests(unittest.TestCase):
    def test_release_mapping(self) -> None:
        self.assertEqual(release_index_from_path(Path(r"G:\DS\B33\win_b64")), 33)
        self.assertEqual(release_label(33), "V5-6R2023")
        self.assertEqual(release_label(21), "V5R21")

    def test_support_tiers_do_not_reduce_newer_releases(self) -> None:
        self.assertEqual(support_tier(27, 28), "legacy_unsupported")
        self.assertEqual(support_tier(33, 28), "locally_validated_target")
        self.assertEqual(support_tier(34, 28), "forward_capability_gated")

    def test_environment_parser(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "CATIA.txt"
            path.write_text("! comment\nCATInstallPath=G:\\DS\\B33\\win_b64\nCATDLLPath=x\n", encoding="utf-8")
            values = parse_environment_file(path)
            self.assertEqual(values["CATInstallPath"], r"G:\DS\B33\win_b64")


if __name__ == "__main__":
    unittest.main()
