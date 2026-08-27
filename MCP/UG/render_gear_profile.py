#!/usr/bin/env python3
"""Render the pure involute profile used by the NX MCP for visual regression."""

from __future__ import annotations

import argparse
import sys
import types
from pathlib import Path

from PIL import Image, ImageDraw


def _install_import_stubs() -> None:
    nxopen = types.ModuleType("NXOpen")
    nxopen.__path__ = []
    features = types.ModuleType("NXOpen.Features")
    geometric = types.ModuleType("NXOpen.GeometricUtilities")
    nxopen.Features = features
    nxopen.GeometricUtilities = geometric
    sys.modules.setdefault("NXOpen", nxopen)
    sys.modules.setdefault("NXOpen.Features", features)
    sys.modules.setdefault("NXOpen.GeometricUtilities", geometric)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    _install_import_stubs()
    import nx_remote_ops

    outer, inner, dimensions = nx_remote_ops._involute_gear_profile(
        2.0, 20, 20.0, 10.0, 10, 4
    )
    size = 1100
    margin = 70
    scale = (size - 2 * margin) / dimensions["outside_diameter"]
    center = size / 2.0

    def pixel(point):
        return (center + point[0] * scale, center - point[1] * scale)

    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    draw.polygon([pixel(point) for point in outer], fill="#cbd5e1", outline="#0f172a")
    if inner:
        draw.polygon([pixel(point) for point in inner], fill="white", outline="#0f172a")

    pitch_radius_px = dimensions["pitch_diameter"] * scale / 2.0
    pitch_box = (
        center - pitch_radius_px,
        center - pitch_radius_px,
        center + pitch_radius_px,
        center + pitch_radius_px,
    )
    for start in range(0, 360, 12):
        draw.arc(pitch_box, start=start, end=start + 6, fill="#2563eb", width=2)

    draw.text(
        (24, 20),
        "Corrected involute: m=2  z=20  PA=20 deg  pitch thickness=pi mm",
        fill="#0f172a",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
