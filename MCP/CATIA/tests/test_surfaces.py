from __future__ import annotations

import unittest

from catia_mcp.contracts import ContractError
from catia_mcp.surfaces import (
    _continuity_code,
    _coupling_code,
    _validate_point_records,
    create_fill,
    create_loft,
    join_surfaces,
    thick_surface,
)


class SurfaceContractTests(unittest.TestCase):
    def test_validates_named_3d_points(self) -> None:
        result = _validate_point_records(
            [
                {"name": "P1", "coordinates": [1, 2, 3]},
                {"name": "P2", "x_mm": 4, "y_mm": 5, "z_mm": 6},
            ]
        )
        self.assertEqual(result[0], {"name": "P1", "coordinates": (1.0, 2.0, 3.0)})
        self.assertEqual(result[1], {"name": "P2", "coordinates": (4.0, 5.0, 6.0)})

    def test_rejects_duplicate_point_names_case_insensitively(self) -> None:
        with self.assertRaises(ContractError):
            _validate_point_records(
                [
                    {"name": "LeadingEdge", "coordinates": [0, 0, 0]},
                    {"name": "leadingedge", "coordinates": [0, 0, 1]},
                ]
            )

    def test_maps_continuity_and_coupling_contracts(self) -> None:
        self.assertEqual([_continuity_code(value) for value in ("g0", "g1", "g2")], [0, 1, 2])
        self.assertEqual(
            [_coupling_code(value) for value in ("ratio", "tangency", "curvature", "vertices")],
            [1, 2, 3, 4],
        )

    def test_rejects_mismatched_loft_closing_points_before_com(self) -> None:
        with self.assertRaises(ContractError):
            create_loft(
                None,
                "BladeLoft",
                ["Section1", "Section2"],
                closing_point_names=["Close1"],
            )

    def test_rejects_single_element_join_before_com(self) -> None:
        with self.assertRaises(ContractError):
            join_surfaces(None, "Join", ["OnlyOne"])

    def test_rejects_fill_support_count_mismatch_before_com(self) -> None:
        with self.assertRaises(ContractError):
            create_fill(
                None,
                "Fill",
                ["Boundary1", "Boundary2"],
                support_names=["Support1"],
            )

    def test_rejects_zero_thick_surface_before_com(self) -> None:
        with self.assertRaises(ContractError):
            thick_surface(None, "Thick", "Surface", 0, 0)

    def test_fill_tolerates_rejected_tolerant_mode_property(self) -> None:
        # V5R21 exposes AddNewFill.AdvancedTolerantMode but rejects the
        # assignment; the fill must still be created with the native default.
        class FakeFill:
            def __init__(self):
                self.Name = ""
                self.bounds = []

            @property
            def AdvancedTolerantMode(self):
                return None

            @AdvancedTolerantMode.setter
            def AdvancedTolerantMode(self, value):
                raise AttributeError("Property 'AddNewFill.AdvancedTolerantMode' can not be set.")

            def AddBound(self, reference):
                self.bounds.append(reference)

        class FakeHybridBody:
            Name = "Surfaces"

            def AppendHybridShape(self, feature):
                self.appended = feature

        class FakeHybridBodies:
            def __init__(self):
                self.items = []

            @property
            def Count(self):
                return len(self.items)

            def Item(self, index):
                return self.items[index - 1]

            def Add(self):
                body = FakeHybridBody()
                self.items.append(body)
                return body

        fill = FakeFill()

        class FakeFactory:
            def AddNewFill(self):
                return fill

        class FakePart:
            def __init__(self):
                self.HybridBodies = FakeHybridBodies()
                self.HybridShapeFactory = FakeFactory()
                self.OriginElements = type("Origin", (), {"PlaneXY": object()})()
                self.InWorkObject = None

            def CreateReferenceFromObject(self, obj):
                return obj

            def UpdateObject(self, feature):
                return None

            def Update(self):
                return None

        part = FakePart()
        document = type("Document", (), {"Name": "Test.CATPart", "Part": part})()
        app = type(
            "App",
            (),
            {"Documents": type("D", (), {"Count": 1})(), "ActiveDocument": document},
        )()

        result = create_fill(app, "TestFill", ["xy"], geometrical_set="Surfaces")
        self.assertEqual(result["fill"], "TestFill")
        self.assertIsNone(result["advanced_tolerant_mode"])
        self.assertIn("AdvancedTolerantMode", result["advanced_tolerant_mode_error"])
        self.assertEqual(len(fill.bounds), 1)

    def _join_app(self, join, update_object):
        class FakeFactory:
            def AddNewJoin(self, first, second):
                return join

        class FakeHybridBody:
            Name = "Surfaces"

            def AppendHybridShape(self, feature):
                self.appended = feature

        class FakeHybridBodies:
            def __init__(self):
                self.items = []

            @property
            def Count(self):
                return len(self.items)

            def Item(self, index):
                return self.items[index - 1]

            def Add(self):
                body = FakeHybridBody()
                self.items.append(body)
                return body

        class FakePart:
            def __init__(self):
                self.HybridBodies = FakeHybridBodies()
                self.HybridShapeFactory = FakeFactory()
                self.OriginElements = type(
                    "Origin", (), {"PlaneXY": object(), "PlaneYZ": object(), "PlaneZX": object()}
                )()
                self.InWorkObject = None

            def CreateReferenceFromObject(self, obj):
                return obj

            def UpdateObject(self, feature):
                update_object(self, feature)

            def Update(self):
                return None

        part = FakePart()
        document = type("Document", (), {"Name": "Test.CATPart", "Part": part})()
        app = type(
            "App",
            (),
            {"Documents": type("D", (), {"Count": 1})(), "ActiveDocument": document},
        )()
        return app, part

    def _angular_join(self):
        class FakeJoin:
            def __init__(self):
                self.Name = ""
                self.angular_mode = None

            def SetConnex(self, value):
                return None

            def SetManifold(self, value):
                return None

            def SetSimplify(self, value):
                return None

            def SetDeviation(self, value):
                return None

            def SetAngularTolerance(self, value):
                return None

            def SetAngularToleranceMode(self, value):
                self.angular_mode = bool(value)

        return FakeJoin()

    def test_join_falls_back_when_solver_rejects_angular_mode(self) -> None:
        join = self._angular_join()
        updates = {"count": 0}

        def update_object(part, feature):
            updates["count"] += 1
            if join.angular_mode is True:
                raise RuntimeError("solver rejected angular tolerance mode")

        app, part = self._join_app(join, update_object)
        result = join_surfaces(
            app, "Join", ["xy", "yz"], tolerance_mm=0.1, connex=False, manifold=False, simplify=False
        )
        self.assertEqual(result["join"], "Join")
        self.assertFalse(result["angular_tolerance_mode"])
        self.assertIn("recomputed without it", result["angular_tolerance_note"])
        self.assertEqual(updates["count"], 2)
        self.assertIs(join.angular_mode, False)

    def test_join_reports_both_errors_when_retry_also_fails(self) -> None:
        join = self._angular_join()

        def update_object(part, feature):
            raise RuntimeError("update blew up")

        app, _ = self._join_app(join, update_object)
        with self.assertRaisesRegex(RuntimeError, "retry without the mode also failed"):
            join_surfaces(app, "Join", ["xy", "yz"])


if __name__ == "__main__":
    unittest.main()
