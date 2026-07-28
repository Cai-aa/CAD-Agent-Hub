#!/usr/bin/env python3
"""Validate the portable job contract used by ansys-structural-workbench."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


PROFILES = {
    "linear_static",
    "nonlinear_static",
    "contact",
    "modal",
    "eigenvalue_buckling",
    "nonlinear_buckling",
    "submodeling",
}
MODEL_SOURCES = {"existing_project", "import_cad", "procedural_geometry"}
MESH_PROFILES = {
    "solid_general",
    "solid_contact",
    "thin_solid_bending",
    "shell_structure",
    "beam_frame",
    "plasticity_large_deformation",
    "modal_buckling",
    "submodel",
}


def load(path: str) -> dict:
    with Path(path).open("r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("root must be a JSON object")
    return value


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"status": "invalid", "errors": ["usage: validate_job_spec.py JOB.json"]}))
        return 2
    try:
        data = load(sys.argv[1])
    except Exception as exc:
        print(json.dumps({"status": "invalid", "errors": [str(exc)]}))
        return 2

    errors: list[str] = []
    warnings: list[str] = []
    if data.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    task_name = data.get("task_name")
    if not isinstance(task_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", task_name):
        errors.append("task_name must be a non-empty filesystem-safe identifier")
    single_profile = data.get("analysis_profile")
    profile_list = data.get("analysis_profiles")
    if single_profile is not None and profile_list is not None:
        errors.append("provide analysis_profile or analysis_profiles, not both")
        profiles: set[str] = set()
    elif profile_list is not None:
        if not isinstance(profile_list, list) or not profile_list:
            errors.append("analysis_profiles must be a non-empty array")
            profiles = set()
        else:
            profiles = set(profile_list)
            if len(profiles) != len(profile_list):
                errors.append("analysis_profiles must not contain duplicates")
    else:
        profiles = {single_profile} if single_profile is not None else set()
    if not profiles or not profiles.issubset(PROFILES):
        errors.append("analysis profile set is missing or unsupported")

    model = data.get("model")
    if not isinstance(model, dict):
        errors.append("model must be an object")
        model = {}
    source = model.get("source")
    if source not in MODEL_SOURCES:
        errors.append("model.source is missing or unsupported")
    if source == "existing_project" and not (model.get("project_path") or model.get("use_active_project")):
        errors.append("existing_project requires project_path or use_active_project=true")
    if source == "import_cad" and not model.get("cad_path"):
        errors.append("import_cad requires model.cad_path")
    if source == "procedural_geometry" and not model.get("geometry"):
        errors.append("procedural_geometry requires model.geometry")
    units = model.get("units")
    if not isinstance(units, dict) or any(not units.get(key) for key in ("length", "force", "stress")):
        errors.append("model.units must define length, force, and stress")

    materials = data.get("materials")
    if not isinstance(materials, list) or not materials:
        errors.append("materials must contain at least one material")
    else:
        for index, material in enumerate(materials):
            if not isinstance(material, dict) or not material.get("name") or not material.get("model"):
                errors.append(f"materials[{index}] requires name and model")
        if "modal" in profiles and not all(m.get("density") for m in materials if isinstance(m, dict)):
            errors.append("modal profile requires density for every material")

    mesh = data.get("mesh")
    if not isinstance(mesh, dict):
        errors.append("mesh must be an object")
        mesh = {}
    if mesh.get("profile") not in MESH_PROFILES:
        errors.append("mesh.profile is missing or unsupported")
    convergence = mesh.get("convergence", {})
    if convergence.get("enabled"):
        levels = convergence.get("levels", [])
        metrics = convergence.get("metrics", [])
        if len(levels) < 3:
            errors.append("enabled convergence study requires at least three levels")
        if not metrics:
            errors.append("enabled convergence study requires at least one metric")

    if "contact" in profiles and not data.get("connections"):
        errors.append("contact profile requires at least one connection definition")
    if profiles.intersection({"nonlinear_static", "contact", "nonlinear_buckling"}) and not data.get("solution"):
        warnings.append("nonlinear profile has no explicit solution controls")
    if not data.get("outputs"):
        warnings.append("no output artifacts requested")

    status = "fail" if errors else ("warning" if warnings else "pass")
    print(json.dumps({"status": status, "errors": errors, "warnings": warnings}, indent=2))
    return 2 if errors else (1 if warnings else 0)


if __name__ == "__main__":
    raise SystemExit(main())
