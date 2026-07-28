from __future__ import annotations

import json
from pathlib import Path

from solidworks_mcp.executor import SolidWorksExecutor


def emit(label: str, value: object) -> None:
    print(json.dumps({label: value}, ensure_ascii=False, default=str), flush=True)


def main() -> None:
    executor = SolidWorksExecutor()
    try:
        emit("connect", executor.connect(False))
        output_dir = Path(__file__).resolve().parents[1] / "artifacts"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = str(output_dir / "solidworks_two_stage_reducer_m2_i6_corrected.SLDPRT")
        emit(
            "model",
            executor.create_two_stage_reducer(
                "create-two-stage-reducer-20260723-v7",
                output,
                module_mm=2.0,
                pressure_angle_deg=20.0,
                stage1_teeth=(20, 40),
                stage2_teeth=(20, 60),
                gear_thickness_mm=10.0,
                axial_gap_mm=8.0,
                bore_diameters_mm=(10.0, 12.0, 14.0),
            ),
        )
        emit(
            "inspect",
            executor.inspect_active("inspect-two-stage-reducer-20260723-v7", True),
        )
        emit(
            "relations",
            executor.inspect_relations(
                "relations-two-stage-reducer-20260723-v7",
                False,
                False,
                120,
            ),
        )
    finally:
        executor.session.close()


if __name__ == "__main__":
    main()
