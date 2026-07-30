from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from .contracts import (
    ContractError,
    require_choice,
    require_finite,
    require_positive,
    require_safe_name,
    require_text,
)


def _collection_items(collection: Any, limit: int = 500) -> Iterable[Any]:
    count = min(int(collection.Count), limit)
    for index in range(1, count + 1):
        yield collection.Item(index)


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    try:
        member = getattr(obj, name)
        return member() if callable(member) else member
    except Exception:
        return default


def document_kind(document: Any) -> str:
    name = str(_safe_attr(document, "Name", ""))
    suffix = Path(name).suffix.casefold()
    return {
        ".catpart": "Part",
        ".catproduct": "Product",
        ".catdrawing": "Drawing",
        ".catanalysis": "Analysis",
    }.get(suffix, str(_safe_attr(document, "Type", "Unknown")))


def active_document(app: Any) -> Any:
    if int(app.Documents.Count) < 1:
        raise RuntimeError("CATIA has no open document")
    return app.ActiveDocument


def active_part_document(app: Any) -> Any:
    document = active_document(app)
    if document_kind(document).casefold() != "part" and not hasattr(document, "Part"):
        raise RuntimeError(f"active document is not a CATPart: {document.Name}")
    return document


def _body(part: Any, body_name: str) -> Any:
    if body_name:
        try:
            return part.Bodies.Item(body_name)
        except Exception as exc:
            if body_name.casefold() not in {"partbody", "mainbody"}:
                raise RuntimeError(f"body not found: {body_name}") from exc
    try:
        return part.MainBody
    except Exception:
        if int(part.Bodies.Count) > 0:
            return part.Bodies.Item(1)
        body = part.Bodies.Add()
        try:
            body.Name = body_name or "PartBody"
        except Exception:
            pass
        return body


def _sketch(part: Any, body_name: str, sketch_name: str) -> Any:
    body = _body(part, body_name)
    try:
        return body.Sketches.Item(sketch_name)
    except Exception as exc:
        raise RuntimeError(f"sketch not found in {body.Name}: {sketch_name}") from exc


def _plane(part: Any, plane_name: str) -> Any:
    normalized = require_choice(plane_name, "plane", ("xy", "yz", "zx", "xz"))
    if normalized == "xy":
        return part.OriginElements.PlaneXY
    if normalized == "yz":
        return part.OriginElements.PlaneYZ
    return part.OriginElements.PlaneZX


def create_part(app: Any, title: str) -> dict[str, Any]:
    title = require_safe_name(title, "title")
    document = app.Documents.Add("Part")
    part = document.Part
    try:
        part.PartNumber = title
    except Exception:
        pass
    try:
        document.Product.PartNumber = title
    except Exception:
        pass
    try:
        document.Name = title
    except Exception:
        pass
    return {"document": document.Name, "kind": "Part", "part_number": title}


def create_product(app: Any, title: str) -> dict[str, Any]:
    title = require_safe_name(title, "title")
    document = app.Documents.Add("Product")
    product = document.Product
    product.PartNumber = title
    try:
        product.Name = title
    except Exception:
        pass
    return {"document": document.Name, "kind": "Product", "part_number": title}


def open_document(app: Any, path: Path) -> dict[str, Any]:
    document = app.Documents.Open(str(path))
    return {
        "document": document.Name,
        "kind": document_kind(document),
        "full_name": str(_safe_attr(document, "FullName", path)),
    }


def save_active(app: Any, path: Path | None = None) -> dict[str, Any]:
    document = active_document(app)
    if path is None:
        document.Save()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        document.SaveAs(str(path))
    return {
        "document": document.Name,
        "full_name": str(_safe_attr(document, "FullName", path)),
        "saved": bool(_safe_attr(document, "Saved", True)),
    }


_EXPORT_FORMATS = {
    ".stp": "stp",
    ".step": "stp",
    ".igs": "igs",
    ".iges": "igs",
    ".stl": "stl",
    ".3dxml": "3dxml",
    ".model": "model",
    ".cgr": "cgr",
    ".pdf": "pdf",
    ".dxf": "dxf",
    ".dwg": "dwg",
}


def export_active(app: Any, path: Path, format_name: str | None = None) -> dict[str, Any]:
    document = active_document(app)
    resolved_format = format_name.strip().lower() if format_name else _EXPORT_FORMATS.get(path.suffix.casefold())
    if not resolved_format:
        raise ContractError(f"unsupported or ambiguous export extension: {path.suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    document.ExportData(str(path), resolved_format)
    return {
        "document": document.Name,
        "path": str(path),
        "format": resolved_format,
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else None,
    }


def update_active(app: Any) -> dict[str, Any]:
    document = active_document(app)
    kind = document_kind(document)
    if hasattr(document, "Part"):
        document.Part.Update()
    elif hasattr(document, "Product"):
        document.Product.Update()
    else:
        raise RuntimeError(f"update is not implemented for {kind} documents")
    return {"document": document.Name, "kind": kind, "updated": True}


def _point2(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ContractError(f"{name} must be [x, y]")
    return require_finite(value[0], f"{name}[0]"), require_finite(value[1], f"{name}[1]")


def _validate_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(entities, list) or not entities:
        raise ContractError("entities must be a non-empty list")
    if len(entities) > 1000:
        raise ContractError("a sketch is limited to 1000 requested entities")
    validated: list[dict[str, Any]] = []
    for index, entity in enumerate(entities):
        if not isinstance(entity, dict):
            raise ContractError(f"entities[{index}] must be an object")
        kind = require_choice(entity.get("kind"), f"entities[{index}].kind", ("line", "circle", "rectangle", "polyline"))
        if kind == "line":
            validated.append({"kind": kind, "start": _point2(entity.get("start"), "start"), "end": _point2(entity.get("end"), "end")})
        elif kind == "circle":
            validated.append({"kind": kind, "center": _point2(entity.get("center"), "center"), "radius": require_positive(entity.get("radius"), "radius")})
        elif kind == "rectangle":
            validated.append({
                "kind": kind,
                "origin": _point2(entity.get("origin", [0, 0]), "origin"),
                "width": require_positive(entity.get("width"), "width"),
                "height": require_positive(entity.get("height"), "height"),
            })
        else:
            points = entity.get("points")
            if not isinstance(points, list) or len(points) < 2 or len(points) > 1000:
                raise ContractError("polyline.points must contain 2..1000 points")
            validated.append({
                "kind": kind,
                "points": [_point2(point, f"points[{point_index}]") for point_index, point in enumerate(points)],
                "closed": bool(entity.get("closed", False)),
            })
    return validated


def create_sketch(
    app: Any,
    name: str,
    plane: str,
    entities: list[dict[str, Any]],
    body_name: str = "PartBody",
) -> dict[str, Any]:
    name = require_safe_name(name)
    body_name = require_safe_name(body_name, "body_name")
    validated = _validate_entities(entities)
    document = active_part_document(app)
    part = document.Part
    body = _body(part, body_name)
    sketch = body.Sketches.Add(_plane(part, plane))
    sketch.Name = name
    factory = sketch.OpenEdition()
    created = 0
    try:
        for entity in validated:
            kind = entity["kind"]
            if kind == "line":
                factory.CreateLine(*entity["start"], *entity["end"])
                created += 1
            elif kind == "circle":
                factory.CreateClosedCircle(*entity["center"], entity["radius"])
                created += 1
            elif kind == "rectangle":
                x, y = entity["origin"]
                w, h = entity["width"], entity["height"]
                points = ((x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y))
                for start, end in zip(points, points[1:]):
                    factory.CreateLine(*start, *end)
                    created += 1
            else:
                points = list(entity["points"])
                if entity["closed"]:
                    points.append(points[0])
                for start, end in zip(points, points[1:]):
                    factory.CreateLine(*start, *end)
                    created += 1
    finally:
        sketch.CloseEdition()
    part.Update()
    return {
        "document": document.Name,
        "body": body.Name,
        "sketch": sketch.Name,
        "plane": plane.lower(),
        "created_geometry_count": created,
    }


def add_pad(app: Any, sketch_name: str, length_mm: float, name: str = "Pad", body_name: str = "PartBody") -> dict[str, Any]:
    sketch_name = require_safe_name(sketch_name, "sketch_name")
    name = require_safe_name(name)
    length = require_positive(length_mm, "length_mm")
    document = active_part_document(app)
    part = document.Part
    body = _body(part, body_name)
    part.InWorkObject = body
    feature = part.ShapeFactory.AddNewPad(_sketch(part, body_name, sketch_name), length)
    feature.Name = name
    part.Update()
    return {"document": document.Name, "feature": feature.Name, "type": "Pad", "length_mm": length}


def add_pocket(app: Any, sketch_name: str, length_mm: float, name: str = "Pocket", body_name: str = "PartBody") -> dict[str, Any]:
    sketch_name = require_safe_name(sketch_name, "sketch_name")
    name = require_safe_name(name)
    length = require_positive(length_mm, "length_mm")
    document = active_part_document(app)
    part = document.Part
    body = _body(part, body_name)
    part.InWorkObject = body
    feature = part.ShapeFactory.AddNewPocket(_sketch(part, body_name, sketch_name), length)
    feature.Name = name
    part.Update()
    return {"document": document.Name, "feature": feature.Name, "type": "Pocket", "length_mm": length}


def create_parametric_part(app: Any, part_type: str, parameters: dict[str, Any], title: str) -> dict[str, Any]:
    kind = require_choice(part_type, "part_type", ("block", "cylinder", "tube"))
    create_part(app, title)
    if kind == "block":
        length = require_positive(parameters.get("length_mm"), "length_mm")
        width = require_positive(parameters.get("width_mm"), "width_mm")
        height = require_positive(parameters.get("height_mm"), "height_mm")
        create_sketch(app, "BaseSketch", "xy", [{"kind": "rectangle", "origin": [-length / 2, -width / 2], "width": length, "height": width}])
        add_pad(app, "BaseSketch", height, "BlockPad")
    else:
        diameter = require_positive(parameters.get("diameter_mm"), "diameter_mm")
        height = require_positive(parameters.get("height_mm"), "height_mm")
        create_sketch(app, "BaseSketch", "xy", [{"kind": "circle", "center": [0, 0], "radius": diameter / 2}])
        add_pad(app, "BaseSketch", height, "CylinderPad")
        if kind == "tube":
            inner = require_positive(parameters.get("inner_diameter_mm"), "inner_diameter_mm")
            if inner >= diameter:
                raise ContractError("inner_diameter_mm must be smaller than diameter_mm")
            create_sketch(app, "BoreSketch", "xy", [{"kind": "circle", "center": [0, 0], "radius": inner / 2}])
            add_pocket(app, "BoreSketch", height, "BorePocket")
    return {"document": active_document(app).Name, "part_type": kind, "parameters": parameters}


def add_components(app: Any, paths: list[Path]) -> dict[str, Any]:
    document = active_document(app)
    if not hasattr(document, "Product"):
        raise RuntimeError("active document is not a CATProduct")
    if not paths or len(paths) > 200:
        raise ContractError("paths must contain 1..200 component files")
    products = document.Product.Products
    values = tuple(str(path) for path in paths)
    before = int(products.Count)
    errors: list[str] = []

    # Dynamic pywin32 dispatch normally marshals a Python tuple correctly. Some
    # generated CATIA wrappers instead require an explicitly typed SAFEARRAY, so
    # keep both native array variants before falling back to one-by-one insertion.
    attempts: list[Any] = [values]
    try:
        import pythoncom  # type: ignore
        from win32com.client import VARIANT  # type: ignore

        attempts.extend(
            [
                VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, values),
                VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, values),
            ]
        )
    except ImportError:
        pass

    for candidate in attempts:
        try:
            products.AddComponentsFromFiles(candidate, "All")
            break
        except Exception as exc:
            errors.append(f"AddComponentsFromFiles: {exc}")
            # Do not retry through another route if CATIA inserted anything
            # before reporting an error; that could duplicate components.
            if int(products.Count) > before:
                break
    else:
        for path in paths:
            source = app.Documents.Open(str(path))
            try:
                products.AddComponent(source.Product)
            except Exception as add_component_error:
                try:
                    products.AddExternalComponent(source)
                except Exception as external_error:
                    raise RuntimeError(
                        "CATIA rejected all component insertion routes: "
                        + " | ".join(errors + [str(add_component_error), str(external_error)])
                    ) from external_error

    document.Product.Update()
    return {"document": document.Name, "added": list(values), "component_count": int(products.Count)}


def list_materials(app: Any, catalog_path: Path, family_name: str | None = None, limit: int = 500) -> dict[str, Any]:
    try:
        original = active_document(app)
    except Exception:
        original = None
    catalog = app.Documents.Open(str(catalog_path))
    try:
        families = []
        for family in _collection_items(catalog.Families, limit):
            current_name = str(_safe_attr(family, "Name", ""))
            if family_name and current_name.casefold() != family_name.strip().casefold():
                continue
            materials = [
                str(_safe_attr(material, "Name", ""))
                for material in _collection_items(family.Materials, limit)
            ]
            families.append({"name": current_name, "materials": materials})
        return {"catalog": str(catalog_path), "families": families}
    finally:
        catalog.Close()
        if original is not None:
            original.Activate()


def apply_material(
    app: Any,
    catalog_path: Path,
    family_name: str,
    material_name: str,
    link_mode: int = 1,
) -> dict[str, Any]:
    target = active_document(app)
    family_text = require_text(family_name, "family_name", max_length=256)
    material_text = require_text(material_name, "material_name", max_length=256)
    if link_mode not in (0, 1):
        raise ContractError("link_mode must be 0 (copy) or 1 (linked)")
    catalog = app.Documents.Open(str(catalog_path))
    try:
        family = catalog.Families.Item(family_text)
        material = family.Materials.Item(material_text)
        if hasattr(target, "Part"):
            part = target.Part
            manager = part.GetItem("CATMatManagerVBExt")
            manager.ApplyMaterialOnPart(part, material, link_mode)
            part.Update()
            target_kind = "Part"
        elif hasattr(target, "Product"):
            product = target.Product
            manager = product.GetItem("CATMatManagerVBExt")
            manager.ApplyMaterialOnProduct(product, material, link_mode)
            product.Update()
            target_kind = "Product"
        else:
            raise RuntimeError("active document is not a CATPart or CATProduct")
    finally:
        catalog.Close()
        target.Activate()
    return {
        "document": target.Name,
        "kind": target_kind,
        "catalog": str(catalog_path),
        "family": family_text,
        "material": material_text,
        "link_mode": link_mode,
    }


def list_parameters(app: Any, limit: int = 200) -> dict[str, Any]:
    document = active_part_document(app)
    parameters = document.Part.Parameters
    rows = []
    for parameter in _collection_items(parameters, max(1, min(limit, 1000))):
        rows.append({
            "name": str(_safe_attr(parameter, "Name", "")),
            "value": str(_safe_attr(parameter, "ValueAsString", _safe_attr(parameter, "Value", ""))),
        })
    return {"document": document.Name, "count": int(parameters.Count), "parameters": rows, "truncated": int(parameters.Count) > len(rows)}


def set_parameter(app: Any, parameter_name: str, value: str, update: bool = True) -> dict[str, Any]:
    document = active_part_document(app)
    name = require_text(parameter_name, "parameter_name", max_length=512)
    expression = require_text(value, "value", max_length=128)
    try:
        parameter = document.Part.Parameters.Item(name)
    except Exception as exc:
        raise RuntimeError(f"parameter not found: {name}") from exc
    parameter.ValuateFromString(expression)
    if update:
        document.Part.Update()
    return {
        "document": document.Name,
        "parameter": name,
        "value": str(_safe_attr(parameter, "ValueAsString", expression)),
        "updated": update,
    }


def inspect_active(app: Any, include_parameters: bool = False, limit: int = 200) -> dict[str, Any]:
    document = active_document(app)
    result: dict[str, Any] = {
        "document": document.Name,
        "kind": document_kind(document),
        "full_name": str(_safe_attr(document, "FullName", "")),
        "saved": bool(_safe_attr(document, "Saved", False)),
        "read_only": bool(_safe_attr(document, "ReadOnly", False)),
    }
    if hasattr(document, "Part"):
        part = document.Part
        bodies = []
        for body in _collection_items(part.Bodies, limit):
            sketches = [str(_safe_attr(item, "Name", "")) for item in _collection_items(body.Sketches, limit)]
            shapes = [
                {"name": str(_safe_attr(item, "Name", "")), "type": str(_safe_attr(item, "Type", type(item).__name__))}
                for item in _collection_items(body.Shapes, limit)
            ]
            bodies.append({"name": body.Name, "sketches": sketches, "shapes": shapes})

        def inspect_hybrid_body(hybrid_body: Any) -> dict[str, Any]:
            shapes = [
                {
                    "name": str(_safe_attr(item, "Name", "")),
                    "type": str(_safe_attr(item, "Type", type(item).__name__)),
                }
                for item in _collection_items(hybrid_body.HybridShapes, limit)
            ]
            children = [
                inspect_hybrid_body(item)
                for item in _collection_items(hybrid_body.HybridBodies, limit)
            ]
            return {
                "name": str(_safe_attr(hybrid_body, "Name", "")),
                "shapes": shapes,
                "children": children,
            }

        hybrid_bodies = [
            inspect_hybrid_body(item)
            for item in _collection_items(part.HybridBodies, limit)
        ]
        result["part_number"] = str(_safe_attr(part, "PartNumber", ""))
        result["bodies"] = bodies
        result["hybrid_bodies"] = hybrid_bodies
        if include_parameters:
            result["parameter_inventory"] = list_parameters(app, limit)
    elif hasattr(document, "Product"):
        product = document.Product
        result["part_number"] = str(_safe_attr(product, "PartNumber", ""))
        result["components"] = [
            {"name": str(_safe_attr(item, "Name", "")), "part_number": str(_safe_attr(item, "PartNumber", ""))}
            for item in _collection_items(product.Products, limit)
        ]
    return result


def capture_view(app: Any, path: Path) -> dict[str, Any]:
    if path.suffix.casefold() != ".bmp":
        raise ContractError("CATIA Automation capture is intentionally restricted to the stable BMP format")
    path.parent.mkdir(parents=True, exist_ok=True)
    viewer = app.ActiveWindow.ActiveViewer
    viewer.Reframe()
    viewer.CaptureToFile(0, str(path))  # catCaptureFormatBMP
    return {"path": str(path), "exists": path.exists(), "size_bytes": path.stat().st_size if path.exists() else None}


def close_active(
    app: Any,
    save: bool = False,
    discard_unsaved: bool = False,
    expected_document_name: str | None = None,
) -> dict[str, Any]:
    document = active_document(app)
    if expected_document_name:
        expected = require_text(expected_document_name, "expected_document_name", max_length=512)
        if str(document.Name).casefold() != expected.casefold():
            raise ContractError(
                f"refusing to close active document {document.Name}; expected {expected}"
            )
    was_saved = bool(_safe_attr(document, "Saved", False))
    if not was_saved and not save and not discard_unsaved:
        raise ContractError("active document has unsaved changes; set save=true or discard_unsaved=true")
    name = document.Name
    if save:
        document.Save()
    previous_alerts = bool(_safe_attr(app, "DisplayFileAlerts", True))
    if discard_unsaved:
        app.DisplayFileAlerts = False
    try:
        document.Close()
    finally:
        app.DisplayFileAlerts = previous_alerts
    return {"document": name, "closed": True, "saved_before_close": save or was_saved, "discarded": discard_unsaved and not was_saved}
