from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .contracts import ContractError, require_text


DOCUMENT_TYPE_NAMES = {
    1: "part",
    2: "assembly",
    3: "drawing",
}


def _com_value(obj: Any, name: str, *args: Any) -> Any:
    member = getattr(obj, name)
    return member(*args) if callable(member) else member


def _number_sequence(value: Any, name: str, expected: int | None = None) -> list[float]:
    if isinstance(value, tuple) and len(value) == 1 and isinstance(value[0], (list, tuple)):
        value = value[0]
    if not isinstance(value, (list, tuple)):
        raise RuntimeError(f"SolidWorks returned an invalid {name}")
    try:
        result = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"SolidWorks returned non-numeric {name}") from exc
    if expected is not None and len(result) != expected:
        raise RuntimeError(f"SolidWorks returned {len(result)} {name} values; expected {expected}")
    return result


def document_summary(document: Any, *, active: bool = False) -> dict[str, Any]:
    document_type = int(_com_value(document, "GetType"))
    try:
        path = str(_com_value(document, "GetPathName"))
    except Exception:
        path = ""
    try:
        dirty = bool(_com_value(document, "GetSaveFlag"))
    except Exception:
        dirty = None
    return {
        "title": str(_com_value(document, "GetTitle")),
        "path": path,
        "document_type": document_type,
        "document_type_name": DOCUMENT_TYPE_NAMES.get(document_type, "unknown"),
        "active": active,
        "dirty": dirty,
    }


def list_documents(documents: Iterable[Any], active_document: Any | None) -> dict[str, Any]:
    items = [
        document_summary(document, active=document is active_document)
        for document in documents
    ]
    active_title = None
    if active_document is not None:
        active_title = str(_com_value(active_document, "GetTitle"))
        for item in items:
            if item["title"] == active_title:
                item["active"] = True
    return {
        "ok": True,
        "document_count": len(items),
        "active_title": active_title,
        "documents": items,
    }


def activate_document(app: Any, title: str, documents: Iterable[Any]) -> dict[str, Any]:
    requested = require_text(title, "title")
    available = {
        str(_com_value(document, "GetTitle")): document
        for document in documents
    }
    if requested not in available:
        raise ContractError(
            f"No open SolidWorks document is titled '{requested}'. "
            f"Available documents: {', '.join(sorted(available)) or '<none>'}"
        )

    activated = None
    attempts: list[str] = []
    for method_name, arguments in (
        ("ActivateDoc3", (requested, True, 0, 0)),
        ("ActivateDoc2", (requested, True, 0, 0)),
        ("ActivateDoc", (requested,)),
    ):
        try:
            result = _com_value(app, method_name, *arguments)
            if isinstance(result, tuple):
                activated = result[0] if result else None
            else:
                activated = result
            activated = getattr(app, "ActiveDoc", None) or activated
            if activated is not None:
                break
        except Exception as exc:
            attempts.append(f"{method_name}: {type(exc).__name__}: {exc}")
    if activated is None:
        raise RuntimeError("SolidWorks could not activate the document; " + "; ".join(attempts))

    summary = document_summary(activated, active=True)
    if summary["title"] != requested:
        raise RuntimeError(
            f"SolidWorks activated '{summary['title']}' instead of requested '{requested}'"
        )
    return {"ok": True, "operation": "activate_document", **summary}


def get_bounding_box(model: Any, include_hidden: bool = True) -> dict[str, Any]:
    document_type = int(_com_value(model, "GetType"))
    if document_type == 1:
        raw = _com_value(model, "GetPartBox", bool(include_hidden))
    elif document_type == 2:
        raw = _com_value(model, "GetBox", 0)
    else:
        raise ContractError("Bounding boxes are supported for part and assembly documents only")

    values_m = _number_sequence(raw, "bounding-box", expected=6)
    minimum_m = values_m[:3]
    maximum_m = values_m[3:]
    size_m = [maximum - minimum for minimum, maximum in zip(minimum_m, maximum_m)]
    if any(size < 0 for size in size_m):
        raise RuntimeError("SolidWorks returned an inverted bounding box")
    return {
        "ok": True,
        "document_type": document_type,
        "document_type_name": DOCUMENT_TYPE_NAMES.get(document_type, "unknown"),
        "include_hidden": bool(include_hidden),
        "minimum_mm": [value * 1000.0 for value in minimum_m],
        "maximum_mm": [value * 1000.0 for value in maximum_m],
        "size_mm": [value * 1000.0 for value in size_m],
        "approximate": True,
    }


def get_mass_properties(model: Any) -> dict[str, Any]:
    document_type = int(_com_value(model, "GetType"))
    if document_type not in {1, 2}:
        raise ContractError("Mass properties are supported for part and assembly documents only")

    extension = getattr(model, "Extension", None)
    if extension is None:
        raise RuntimeError("The active document does not expose ModelDocExtension")
    try:
        mass_property = _com_value(extension, "CreateMassProperty")
        if mass_property is None:
            raise RuntimeError("SolidWorks returned no mass-property evaluator")

        def read_number(name: str) -> float | None:
            try:
                return float(_com_value(mass_property, name))
            except Exception:
                return None

        center_of_mass_m: list[float] | None = None
        try:
            center_of_mass_m = _number_sequence(
                _com_value(mass_property, "CenterOfMass"), "center-of-mass", expected=3
            )
        except Exception:
            pass

        principal_moments_kg_m2: list[float] | None = None
        for member_name in ("PrincipalMomentsOfInertia", "GetPrincipalMomentsOfInertia"):
            try:
                principal_moments_kg_m2 = _number_sequence(
                    _com_value(mass_property, member_name), "principal-moment", expected=3
                )
                break
            except Exception:
                continue

        result: dict[str, Any] = {
            "ok": True,
            "source": "ModelDocExtension.CreateMassProperty",
            "document_type": document_type,
            "document_type_name": DOCUMENT_TYPE_NAMES.get(document_type, "unknown"),
            "mass_kg": read_number("Mass"),
            "volume_m3": read_number("Volume"),
            "surface_area_m2": read_number("SurfaceArea"),
            "density_kg_m3": read_number("Density"),
            "center_of_mass_mm": (
                [value * 1000.0 for value in center_of_mass_m]
                if center_of_mass_m is not None
                else None
            ),
            "moments_of_inertia_kg_m2": None,
            "products_of_inertia_kg_m2": None,
            "principal_moments_kg_m2": principal_moments_kg_m2,
        }
        if all(result[name] is None for name in ("mass_kg", "volume_m3", "surface_area_m2")):
            raise RuntimeError("SolidWorks returned no usable modern mass properties")
        return result
    except Exception as modern_error:
        # Some SolidWorks 2025 late-bound ModelDocExtension proxies advertise
        # CreateMassProperty but fail when it is invoked. ModelDoc2 exposes the
        # legacy 12-value array reliably on the same host, including COM, volume,
        # area, mass, moments, and products of inertia.
        try:
            values = _number_sequence(
                _com_value(model, "GetMassProperties"),
                "legacy mass-property",
                expected=12,
            )
        except Exception as legacy_error:
            raise RuntimeError(
                "SolidWorks mass-property APIs failed; "
                f"CreateMassProperty: {type(modern_error).__name__}: {modern_error}; "
                f"GetMassProperties: {type(legacy_error).__name__}: {legacy_error}"
            ) from legacy_error
        volume_m3 = values[3]
        mass_kg = values[5]
        return {
            "ok": True,
            "source": "ModelDoc2.GetMassProperties",
            "document_type": document_type,
            "document_type_name": DOCUMENT_TYPE_NAMES.get(document_type, "unknown"),
            "mass_kg": mass_kg,
            "volume_m3": volume_m3,
            "surface_area_m2": values[4],
            "density_kg_m3": mass_kg / volume_m3 if volume_m3 > 0 else None,
            "center_of_mass_mm": [value * 1000.0 for value in values[:3]],
            "moments_of_inertia_kg_m2": values[6:9],
            "products_of_inertia_kg_m2": values[9:12],
            "principal_moments_kg_m2": None,
        }


def rebuild_diagnostics(
    model: Any,
    *,
    perform_rebuild: bool = False,
    full_rebuild: bool = False,
) -> dict[str, Any]:
    extension = getattr(model, "Extension", None)
    needs_rebuild_before: bool | None = None
    if extension is not None:
        try:
            needs_rebuild_before = bool(_com_value(extension, "NeedsRebuild2"))
        except Exception:
            pass
    try:
        dirty_before = bool(_com_value(model, "GetSaveFlag"))
    except Exception:
        dirty_before = None

    rebuild_result: bool | None = None
    if perform_rebuild:
        if full_rebuild:
            rebuild_result = bool(_com_value(model, "ForceRebuild3", False))
        else:
            rebuild_result = bool(_com_value(model, "EditRebuild3"))

    needs_rebuild_after: bool | None = None
    if extension is not None:
        try:
            needs_rebuild_after = bool(_com_value(extension, "NeedsRebuild2"))
        except Exception:
            pass
    try:
        feature_count = int(_com_value(model, "GetFeatureCount"))
    except Exception:
        feature_count = None
    try:
        dirty_after = bool(_com_value(model, "GetSaveFlag"))
    except Exception:
        dirty_after = None

    return {
        "ok": rebuild_result is not False,
        "operation": "rebuild_diagnostics",
        "performed_rebuild": bool(perform_rebuild),
        "full_rebuild": bool(full_rebuild) if perform_rebuild else False,
        "rebuild_result": rebuild_result,
        "needs_rebuild_before": needs_rebuild_before,
        "needs_rebuild_after": needs_rebuild_after,
        "dirty_before": dirty_before,
        "dirty_after": dirty_after,
        "feature_count": feature_count,
    }


def capture_view(
    model: Any,
    output_path: str,
    *,
    width: int = 1600,
    height: int = 900,
    fit_view: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    if not isinstance(width, int) or isinstance(width, bool) or not 64 <= width <= 7680:
        raise ContractError("width must be an integer from 64 to 7680")
    if not isinstance(height, int) or isinstance(height, bool) or not 64 <= height <= 7680:
        raise ContractError("height must be an integer from 64 to 7680")
    target = Path(require_text(output_path, "output_path")).expanduser().resolve()
    if target.suffix.lower() != ".bmp":
        raise ContractError("SolidWorks view capture output_path must end with .bmp")
    if target.exists() and not overwrite:
        raise ContractError(f"output_path already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)

    if fit_view:
        _com_value(model, "ViewZoomtofit2")
    try:
        _com_value(model, "GraphicsRedraw2")
    except Exception:
        pass
    saved = bool(_com_value(model, "SaveBMP", str(target), width, height))
    if not saved or not target.exists() or target.stat().st_size <= 0:
        raise RuntimeError("SolidWorks SaveBMP did not create a non-empty image")
    return {
        "ok": True,
        "operation": "capture_view",
        "path": str(target),
        "width": width,
        "height": height,
        "fit_view": bool(fit_view),
        "bytes": target.stat().st_size,
    }
