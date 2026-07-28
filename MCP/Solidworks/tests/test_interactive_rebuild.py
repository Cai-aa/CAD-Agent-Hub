from __future__ import annotations

import unittest

from solidworks_mcp.native_features import rebuild


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def ClearSelection2(self, clear: bool) -> None:
        self.calls.append("clear")

    def EditRebuild3(self) -> None:
        self.calls.append("dirty_rebuild")

    def ForceRebuild3(self, top_only: bool) -> None:
        self.calls.append("full_rebuild")

    def GraphicsRedraw2(self) -> None:
        self.calls.append("redraw")


class InteractiveRebuildTests(unittest.TestCase):
    def test_default_rebuild_skips_force_and_redraw(self) -> None:
        model = FakeModel()
        rebuild(model)
        self.assertEqual(model.calls, ["clear", "dirty_rebuild"])

    def test_strict_rebuild_can_still_be_requested(self) -> None:
        model = FakeModel()
        rebuild(model, full=True, redraw=True)
        self.assertEqual(model.calls, ["clear", "full_rebuild", "redraw"])


if __name__ == "__main__":
    unittest.main()
