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


if __name__ == "__main__":
    unittest.main()
