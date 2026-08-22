from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import ContractError, require_text


def _com_value(obj: Any, name: str, *args: Any) -> Any:
    member = getattr(obj, name)
    return member(*args) if callable(member) else member


def _string_sequence(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _configuration_names(model: Any) -> list[str]:
    return _string_sequence(_com_value(model, "GetConfigurationNames"))


def _active_configuration_name(model: Any) -> str:
    manager = getattr(model, "ConfigurationManager", None)
    if manager is None:
        raise RuntimeError("The active document does not expose ConfigurationManager")
    # A late-bound CDispatch returned by this property is itself callable, so
    # the generic property-or-method helper would incorrectly invoke it.
    active = getattr(manager, "ActiveConfiguration")
    if active is None:
        raise RuntimeError("SolidWorks returned no active configuration")
    return str(getattr(active, "Name"))


def _resolve_configuration(model: Any, configuration_name: str | None) -> str:
    name = (
        _active_configuration_name(model)
        if configuration_name is None
        else require_text(configuration_name, "configuration_name")
    )
    available = _configuration_names(model)
    if name not in available:
        raise ContractError(
            f"Unknown configuration '{name}'. Available configurations: "
            f"{', '.join(available) or '<none>'}"
        )
    return name


def list_configurations(model: Any) -> dict[str, Any]:
    active_name = _active_configuration_name(model)
    configurations: list[dict[str, Any]] = []
    for name in _configuration_names(model):
        item: dict[str, Any] = {"name": name, "active": name == active_name}
        try:
            configuration = _com_value(model, "GetConfigurationByName", name)
        except Exception:
            configuration = None
        if configuration is not None:
            for output_name, member_name in (
                ("comment", "Comment"),
                ("alternate_name", "AlternateName"),
                ("derived", "IsDerived"),
            ):
                try:
                    item[output_name] = _com_value(configuration, member_name)
                except Exception:
                    item[output_name] = None
        configurations.append(item)
    return {
        "ok": True,
        "active_configuration": active_name,
        "configuration_count": len(configurations),
        "configurations": configurations,
    }


def activate_configuration(model: Any, configuration_name: str) -> dict[str, Any]:
    name = _resolve_configuration(model, configuration_name)
    api_result = bool(_com_value(model, "ShowConfiguration2", name))
    active_name = _active_configuration_name(model)
    # SolidWorks 2025 may return False even though the requested configuration
    # became active. The postcondition readback is authoritative.
    if active_name != name:
        raise RuntimeError(
            f"SolidWorks did not activate configuration '{name}'; active is '{active_name}'"
        )
    return {
        "ok": True,
        "operation": "activate_configuration",
        "configuration_name": name,
        "api_result": api_result,
    }


def create_configuration(
    model: Any,
    configuration_name: str,
    *,
    comment: str = "",
    alternate_name: str = "",
    activate: bool = True,
) -> dict[str, Any]:
    name = require_text(configuration_name, "configuration_name")
    existing = _configuration_names(model)
    if name in existing:
        raise ContractError(f"Configuration already exists: {name}")
    if len(name) > 128:
        raise ContractError("configuration_name must contain at most 128 characters")
    created = _com_value(
        model,
        "AddConfiguration3",
        name,
        str(comment),
        str(alternate_name),
        0,
    )
    if created is None and name not in _configuration_names(model):
        raise RuntimeError(f"SolidWorks failed to create configuration '{name}'")
    if activate:
        activate_configuration(model, name)
    return {
        "ok": True,
        "operation": "create_configuration",
        "configuration_name": name,
        "comment": str(comment),
        "alternate_name": str(alternate_name),
        "active": _active_configuration_name(model) == name,
    }


def _custom_property_manager(model: Any, configuration_name: str | None) -> tuple[Any, str]:
    extension = getattr(model, "Extension", None)
    if extension is None:
        raise RuntimeError("The active document does not expose ModelDocExtension")
    scope = "" if configuration_name is None else _resolve_configuration(model, configuration_name)
    manager = _com_value(extension, "CustomPropertyManager", scope)
    if manager is None:
        raise RuntimeError("SolidWorks returned no CustomPropertyManager")
    return manager, scope


def _read_custom_property(manager: Any, name: str) -> dict[str, Any]:
    try:
        import pythoncom  # type: ignore
        from win32com.client import VARIANT  # type: ignore

        raw = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
        resolved = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
        was_resolved = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
        link_to_property = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BOOL, False)
        result_code = int(
            manager.Get6(name, False, raw, resolved, was_resolved, link_to_property)
        )
        return {
            "name": name,
            "result_code": result_code,
            "raw_value": str(raw.value),
            "resolved_value": str(resolved.value),
            "was_resolved": bool(was_resolved.value),
            "link_to_property": bool(link_to_property.value),
        }
    except ImportError as exc:
        raise RuntimeError("pywin32 is required to read SolidWorks custom properties") from exc


def get_custom_properties(
    model: Any,
    configuration_name: str | None = None,
) -> dict[str, Any]:
    manager, scope = _custom_property_manager(model, configuration_name)
    names = _string_sequence(_com_value(manager, "GetNames"))
    properties = [_read_custom_property(manager, name) for name in names]
    return {
        "ok": True,
        "scope": "document" if not scope else "configuration",
        "configuration_name": scope or None,
        "property_count": len(properties),
        "properties": properties,
    }


def _property_value(value: Any, name: str) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (str, int, float)) and not isinstance(value, complex):
        rendered = str(value)
        if len(rendered) > 4096:
            raise ContractError(f"properties.{name} must contain at most 4096 characters")
        return rendered
    raise ContractError(f"properties.{name} must be text, a number, or a boolean")


def set_custom_properties(
    model: Any,
    properties: dict[str, Any],
    configuration_name: str | None = None,
) -> dict[str, Any]:
    if not isinstance(properties, dict) or not properties:
        raise ContractError("properties must be a non-empty object")
    if len(properties) > 100:
        raise ContractError("properties must contain at most 100 entries")
    manager, scope = _custom_property_manager(model, configuration_name)
    writes: list[dict[str, Any]] = []
    for raw_name, raw_value in properties.items():
        name = require_text(raw_name, "property name")
        if len(name) > 255:
            raise ContractError("property names must contain at most 255 characters")
        value = _property_value(raw_value, name)
        # swCustomInfoText=30; swCustomPropertyReplaceValue=1.
        result_code = int(manager.Add3(name, 30, value, 1))
        readback = _read_custom_property(manager, name)
        writes.append({"name": name, "value": value, "result_code": result_code, "readback": readback})
    return {
        "ok": True,
        "operation": "set_custom_properties",
        "scope": "document" if not scope else "configuration",
        "configuration_name": scope or None,
        "write_count": len(writes),
        "writes": writes,
    }


def list_material_databases(app: Any) -> dict[str, Any]:
    paths = _string_sequence(_com_value(app, "GetMaterialDatabases"))
    return {
        "ok": True,
        "database_count": len(paths),
        "databases": [
            {"path": path, "exists": Path(path).exists()}
            for path in paths
        ],
    }


def get_material(model: Any, configuration_name: str | None = None) -> dict[str, Any]:
    if int(_com_value(model, "GetType")) != 1:
        raise ContractError("Material tools currently support part documents only")
    configuration = _resolve_configuration(model, configuration_name)
    try:
        import pythoncom  # type: ignore
        from win32com.client import VARIANT  # type: ignore

        database = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
        material_name = str(model.GetMaterialPropertyName2(configuration, database))
    except ImportError as exc:
        raise RuntimeError("pywin32 is required to read SolidWorks material properties") from exc
    return {
        "ok": True,
        "configuration_name": configuration,
        "assigned": bool(material_name),
        "material_name": material_name or None,
        # SolidWorks returns the database display name here, not its filesystem path.
        "database_name": str(database.value) or None,
    }


def assign_material(
    model: Any,
    database_path: str,
    material_name: str,
    configuration_name: str | None = None,
    *,
    rebuild: bool = True,
) -> dict[str, Any]:
    if int(_com_value(model, "GetType")) != 1:
        raise ContractError("Material tools currently support part documents only")
    configuration = _resolve_configuration(model, configuration_name)
    database = Path(require_text(database_path, "database_path")).expanduser().resolve()
    if database.suffix.lower() != ".sldmat" or not database.is_file():
        raise ContractError(f"database_path must be an existing .sldmat file: {database}")
    name = require_text(material_name, "material_name")
    result = _com_value(
        model,
        "SetMaterialPropertyName2",
        configuration,
        str(database),
        name,
    )
    if rebuild:
        _com_value(model, "EditRebuild3")
    readback = get_material(model, configuration)
    if readback["material_name"] != name:
        raise RuntimeError(
            f"SolidWorks did not assign requested material '{name}'; "
            f"read back '{readback['material_name']}'"
        )
    return {
        "ok": True,
        "operation": "assign_material",
        "api_result": result,
        "rebuild": bool(rebuild),
        "database_path": str(database),
        **readback,
    }
