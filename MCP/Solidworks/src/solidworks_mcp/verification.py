"""Read native model facts before a save is allowed."""

from __future__ import annotations
import math
from .native_features import _com_value, _cast_to, feature_names, rebuild
from .inspection import get_mass_properties
from .safety import SafetyError


def feature_status(feature):
    try:
        import pythoncom
        from win32com.client import VARIANT

        warning = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
        result = _com_value(feature, "GetErrorCode2", warning)
        if isinstance(result, tuple):
            return int(result[0]), bool(result[1]) if len(result) > 1 else bool(
                warning.value
            )
        return int(result), bool(warning.value)
    except Exception:
        # Generated pywin32 wrappers return the out-parameter in a tuple.
        result = _com_value(feature, "GetErrorCode2")
        if isinstance(result, tuple):
            return int(result[0]), bool(result[1]) if len(result) > 1 else False
        return int(result), False


def verify_model(model, expected_names=(), expected_volume_m3=None):
    rebuild(model)
    tree = feature_names(model)
    actual_names = {item["name"] for item in tree}
    missing = sorted(set(expected_names) - actual_names)
    if missing:
        raise SafetyError(
            "FEATURES_MISSING",
            f"Native feature tree lacks expected features: {missing}",
        )
    try:
        needs_rebuild = _com_value(model.Extension, "NeedsRebuild2")
    except Exception as exc:
        raise SafetyError(
            "VERIFICATION_UNAVAILABLE", "Cannot read NeedsRebuild2; save refused"
        ) from exc
    if needs_rebuild:
        raise SafetyError(
            "REBUILD_PENDING", "Model still needs rebuilding; save refused"
        )
    errors, warnings, checked = [], [], 0
    names_to_check = list(expected_names) or [
        item["name"]
        for item in tree
        if item["type"]
        in {
            "ProfileFeature",
            "3DProfileFeature",
            "Extrusion",
            "Cut",
            "Revolution",
            "Fillet",
            "Chamfer",
            "CirPattern",
            "LPattern",
            "HoleWzd",
            "Boss",
            "ICE",
        }
    ]
    for name in names_to_check:
        feature = _com_value(model, "FeatureByName", name)
        if feature is None:
            raise SafetyError("FEATURES_MISSING", f"Feature disappeared: {name}")
        try:
            error, is_warning = feature_status(feature)
            checked += 1
            if error:
                (warnings if is_warning else errors).append(
                    {"name": name, "error_code": error}
                )
        except Exception as exc:
            raise SafetyError(
                "VERIFICATION_UNAVAILABLE",
                f"Cannot inspect feature errors: {name}",
                detail=str(exc),
            ) from exc
    if errors:
        raise SafetyError(
            "FEATURE_ERRORS", "Native features have errors", errors=errors
        )
    kind = int(_com_value(model, "GetType"))
    result = {
        "rebuild_verified": True,
        "feature_error_checks": checked,
        "feature_warnings": warnings,
        "features": tree,
    }
    if kind in (1, 2):
        mass = get_mass_properties(model)
        volume = mass.get("volume_m3")
        if volume is None or not math.isfinite(volume) or volume <= 0:
            raise SafetyError(
                "NO_VALID_SOLID", "Model has no finite positive solid volume"
            )
        result["volume_m3"] = volume
        if kind == 1:
            try:
                bodies = _com_value(model, "GetBodies2", 0, True) or []
            except Exception:
                bodies = (
                    _com_value(_cast_to(model, "PartDoc"), "GetBodies2", 0, True) or []
                )
            if not bodies:
                raise SafetyError("NO_VALID_SOLID", "Part has no solid bodies")
            result["solid_body_count"] = len(bodies)
        if expected_volume_m3 is not None:
            if not math.isclose(
                volume, expected_volume_m3, rel_tol=1e-5, abs_tol=1e-12
            ):
                raise SafetyError(
                    "VOLUME_MISMATCH",
                    "Native volume does not match the analytic part definition",
                    expected_m3=expected_volume_m3,
                    actual_m3=volume,
                )
            result["analytic_volume_verified"] = True
    return result


def analytic_volume(metadata):
    params, kind = metadata.get("parameters", {}), metadata.get("part_type")
    if kind == "block":
        return (
            params.get("length_mm", 100)
            * params.get("width_mm", 60)
            * params.get("height_mm", 20)
            * 1e-9
        )
    if kind == "cylinder":
        return (
            math.pi
            * (params.get("diameter_mm", 50) / 2) ** 2
            * params.get("length_mm", 100)
            * 1e-9
        )
    if kind == "tube":
        return (
            math.pi
            / 4
            * (
                params.get("outer_diameter_mm", 50) ** 2
                - params.get("inner_diameter_mm", 40) ** 2
            )
            * params.get("length_mm", 100)
            * 1e-9
        )
    return None
