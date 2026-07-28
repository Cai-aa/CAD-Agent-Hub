from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from solidworks_mcp.interactive import (
    delete_feature,
    edit_sketch,
    inspect_relations,
    rollback,
    set_dimension,
    set_feature_parameter,
)


class FakeDimension:
    def __init__(self, value: float = 0.01) -> None:
        self.value = value
        self.calls: list[tuple[float, int, object]] = []

    def GetSystemValue3(self, option: int, names: object) -> tuple[float]:
        return (self.value,)

    def SetSystemValue3(self, value: float, option: int, names: object) -> int:
        self.calls.append((value, option, names))
        self.value = value
        return 0


class FakeFeature:
    def __init__(self, name: str, feature_type: str = "Boss") -> None:
        self.Name = name
        self.feature_type = feature_type
        self.parents: list[FakeFeature] = []
        self.children: list[FakeFeature] = []

    def GetTypeName2(self) -> str:
        return self.feature_type

    def GetParents(self) -> list["FakeFeature"]:
        return self.parents

    def GetChildren(self) -> list["FakeFeature"]:
        return self.children


class FakeExtension:
    def __init__(self) -> None:
        self.delete_options: list[int] = []

    def DeleteSelection2(self, options: int) -> bool:
        self.delete_options.append(options)
        return True


class FakeFeatureManager:
    def __init__(self) -> None:
        self.rollback_calls: list[tuple[int, str]] = []

    def EditRollback(self, location: int, feature: str) -> bool:
        self.rollback_calls.append((location, feature))
        return True


class FakeModel:
    def __init__(self) -> None:
        self.dimension = FakeDimension()
        self.requested_dimensions: list[str] = []
        self.rebuild_count = 0
        self.Extension = FakeExtension()
        self.FeatureManager = FakeFeatureManager()
        self.features = [FakeFeature("Sketch1", "ProfileFeature"), FakeFeature("Boss1", "Boss")]
        self.features[0].children.append(self.features[1])
        self.features[1].parents.append(self.features[0])

    def Parameter(self, name: str) -> FakeDimension:
        self.requested_dimensions.append(name)
        return self.dimension

    def EditRebuild3(self) -> bool:
        self.rebuild_count += 1
        return True

    def ClearSelection2(self, clear: bool) -> None:
        return None

    def GetFeatureCount(self) -> int:
        return len(self.features)

    def FeatureByPositionReverse(self, position: int) -> FakeFeature:
        return list(reversed(self.features))[position]


class FakeSketchManager:
    def __init__(self) -> None:
        self.AutoSolve = True
        self.AddToDB = False
        self.DisplayWhenAdded = True
        self.created_lines: list[tuple[float, ...]] = []

    def CreateLine(self, *coordinates: float) -> object:
        self.created_lines.append(coordinates)
        return object()


class FakeSketchModel(FakeModel):
    def __init__(self) -> None:
        super().__init__()
        self.SketchManager = FakeSketchManager()
        self.sketch_edit_count = 0
        self.sketch_close_count = 0

    def EditSketch(self) -> None:
        self.sketch_edit_count += 1

    def InsertSketch2(self, update: bool) -> None:
        self.sketch_close_count += 1


class InteractiveTests(unittest.TestCase):
    def test_set_dimension_converts_mm_and_rebuilds_only_once(self) -> None:
        model = FakeModel()
        result = set_dimension(model, "D1@Boss1", 25.0, "mm")
        self.assertAlmostEqual(model.dimension.calls[0][0], 0.025)
        self.assertEqual(model.dimension.calls[0][1], 1)
        self.assertEqual(model.rebuild_count, 1)
        self.assertEqual(result["old_system_value"], 0.01)

    def test_set_feature_parameter_qualifies_dimension_name(self) -> None:
        model = FakeModel()
        set_feature_parameter(model, "Boss1", "D1", 90.0, "deg", rebuild=False)
        self.assertEqual(model.requested_dimensions, ["D1@Boss1"])
        self.assertAlmostEqual(model.dimension.value, math.pi / 2.0)
        self.assertEqual(model.rebuild_count, 0)

    def test_delete_feature_passes_child_and_absorbed_bitmask(self) -> None:
        model = FakeModel()
        with patch("solidworks_mcp.interactive._select_by_id", return_value=True):
            result = delete_feature(
                model,
                "Boss1",
                delete_children=True,
                delete_absorbed=True,
            )
        self.assertEqual(model.Extension.delete_options, [3])
        self.assertTrue(result["ok"])

    def test_edit_sketch_appends_geometry_and_restores_performance_flags(self) -> None:
        model = FakeSketchModel()
        with patch("solidworks_mcp.interactive._select_by_id", return_value=True):
            result = edit_sketch(
                model,
                "Sketch1",
                [{"kind": "line", "start": [0, 0], "end": [25, 0]}],
            )
        self.assertEqual(result["created_segments"], 1)
        self.assertEqual(model.sketch_edit_count, 1)
        self.assertEqual(model.sketch_close_count, 1)
        self.assertTrue(model.SketchManager.AutoSolve)
        self.assertFalse(model.SketchManager.AddToDB)
        self.assertTrue(model.SketchManager.DisplayWhenAdded)

    def test_rollback_uses_official_enum_values(self) -> None:
        model = FakeModel()
        rollback(model, "before", "Boss1")
        rollback(model, "end")
        self.assertEqual(model.FeatureManager.rollback_calls, [(3, "Boss1"), (1, "")])

    def test_inspect_relations_returns_direct_parent_child_graph(self) -> None:
        model = FakeModel()
        result = inspect_relations(model, include_topology=False)
        by_name = {item["name"]: item for item in result["features"]}
        self.assertEqual(by_name["Boss1"]["parents"], ["Sketch1"])
        self.assertEqual(by_name["Sketch1"]["children"], ["Boss1"])
        self.assertEqual(result["topology"], [])


if __name__ == "__main__":
    unittest.main()
