from __future__ import annotations

import os
import re
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import Settings


_ENV_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_BUILD_MARKER = re.compile(r"(?:^|[\\/])B(\d+)(?:[\\/]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class CatiaInstallation:
    environment_name: str
    environment_file: Path
    install_path: Path
    release_index: int | None
    release_label: str
    support_tier: str
    components: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["environment_file"] = str(self.environment_file)
        data["install_path"] = str(self.install_path)
        return data


def release_label(index: int | None) -> str:
    if index is None:
        return "unknown"
    if index <= 21:
        return f"V5R{index}"
    return f"V5-6R{1990 + index}"


def release_index_from_path(path: Path) -> int | None:
    match = _BUILD_MARKER.search(str(path))
    return int(match.group(1)) if match else None


def support_tier(index: int | None, minimum: int) -> str:
    if index is None:
        return "unknown"
    if index < minimum:
        return "legacy_unsupported"
    if index == 33:
        return "locally_validated_target"
    if index > 33:
        return "forward_capability_gated"
    return "supported_capability_gated"


def parse_environment_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("!") or line.startswith("#"):
            continue
        match = _ENV_ASSIGNMENT.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def _components(install_path: Path) -> dict[str, bool]:
    bin_dir = install_path / "code" / "bin"
    return {
        "catia_runtime": (bin_dir / "CNEXT.exe").is_file(),
        "catstart": (bin_dir / "CATSTART.exe").is_file(),
        "automation_help": (bin_dir / "V5Automation.chm").is_file(),
        "part_design_automation": (bin_dir / "CATPdgAutomation.dll").is_file(),
        "sketcher_automation": (bin_dir / "CATSkmAutomation.dll").is_file(),
        "assembly_automation": (bin_dir / "CATCafAutomation.dll").is_file(),
        "analysis_automation": (bin_dir / "CATAnalysisTypLib.tlb").is_file(),
        "generative_analysis": (bin_dir / "CATAnalysisGenerative.dll").is_file(),
        "elfini_solver": (bin_dir / "CATElfiniSolver.dll").is_file(),
    }


def discover_installations(settings: Settings) -> list[CatiaInstallation]:
    files: list[Path] = []
    if settings.environment_directory.is_dir():
        files.extend(sorted(settings.environment_directory.glob("*.txt")))
    installations: list[CatiaInstallation] = []
    for env_file in files:
        values = parse_environment_file(env_file)
        raw_install = values.get("CATInstallPath")
        if not raw_install:
            continue
        install_path = Path(os.path.expandvars(raw_install))
        index = release_index_from_path(install_path)
        installations.append(
            CatiaInstallation(
                environment_name=env_file.stem,
                environment_file=env_file,
                install_path=install_path,
                release_index=index,
                release_label=release_label(index),
                support_tier=support_tier(index, settings.minimum_supported_release_index),
                components=_components(install_path),
            )
        )
    if settings.install_path and not any(item.install_path == settings.install_path for item in installations):
        index = release_index_from_path(settings.install_path)
        installations.append(
            CatiaInstallation(
                environment_name=settings.environment_name or "explicit-install-path",
                environment_file=settings.environment_directory / "(not-used)",
                install_path=settings.install_path,
                release_index=index,
                release_label=release_label(index),
                support_tier=support_tier(index, settings.minimum_supported_release_index),
                components=_components(settings.install_path),
            )
        )
    installations.sort(key=lambda item: item.release_index or -1, reverse=True)
    return installations


def choose_installation(settings: Settings, installations: Iterable[CatiaInstallation]) -> CatiaInstallation | None:
    candidates = list(installations)
    if settings.environment_name:
        for item in candidates:
            if item.environment_name.casefold() == settings.environment_name.casefold():
                return item
    if settings.install_path:
        target = settings.install_path.resolve(strict=False)
        for item in candidates:
            if item.install_path.resolve(strict=False) == target:
                return item
    supported = [
        item
        for item in candidates
        if item.release_index is None or item.release_index >= settings.minimum_supported_release_index
    ]
    return (supported or candidates or [None])[0]


def com_registration() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for progid in ("CATIA.Application", "CATIA.Application.1"):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, fr"{progid}\CLSID") as key:
                clsid, _ = winreg.QueryValueEx(key, None)
            result[progid] = {"registered": True, "clsid": str(clsid)}
        except OSError:
            result[progid] = {"registered": False, "clsid": None}
    return result


def inspect_analysis_typelib(path: Path) -> dict[str, Any]:
    """Inspect the installed typelib instead of assuming release-specific methods."""
    if not path.is_file():
        return {"available": False, "path": str(path), "interfaces": {}}
    try:
        import pythoncom  # type: ignore
    except ImportError:
        return {"available": False, "path": str(path), "error": "pywin32 is unavailable", "interfaces": {}}
    typelib = pythoncom.LoadTypeLib(str(path))
    wanted = {
        "AnalysisDocument",
        "AnalysisManager",
        "AnalysisModel",
        "AnalysisCases",
        "AnalysisCase",
        "AnalysisSet",
        "AnalysisEntities",
        "AnalysisEntity",
        "AnalysisMeshManager",
        "AnalysisMeshPart",
        "AnalysisPostManager",
        "AnalysisImage",
    }
    interfaces: dict[str, list[str]] = {}
    for index in range(typelib.GetTypeInfoCount()):
        name = typelib.GetDocumentation(index)[0]
        if name not in wanted:
            continue
        info = typelib.GetTypeInfo(index)
        attributes = info.GetTypeAttr()
        methods: list[str] = []
        for function_index in range(attributes.cFuncs):
            descriptor = info.GetFuncDesc(function_index)
            member_name = info.GetNames(descriptor.memid)[0]
            if member_name not in methods and member_name not in {
                "QueryInterface", "AddRef", "Release", "GetTypeInfoCount", "GetTypeInfo",
                "GetIDsOfNames", "Invoke", "Destructor", "GetMetaObject", "IsA", "IsAKindOf",
                "GetImpl", "SetImpl", "IsNull", "IsEqual", "SurChargeQI", "ChangeComponentState",
            }:
                methods.append(member_name)
        interfaces[name] = methods
    required = {
        "AnalysisManager": {"AnalysisModels", "Import"},
        "AnalysisCase": {"Compute", "ComputeMeshOnly"},
        "AnalysisEntities": {"Add"},
        "AnalysisEntity": {"SetValue"},
    }
    missing = {
        name: sorted(methods - set(interfaces.get(name, [])))
        for name, methods in required.items()
        if methods - set(interfaces.get(name, []))
    }
    return {
        "available": True,
        "path": str(path),
        "interfaces": interfaces,
        "native_analysis_contract_ready": not missing,
        "missing_required_methods": missing,
    }


def environment_report(settings: Settings) -> dict[str, Any]:
    installations = discover_installations(settings)
    selected = choose_installation(settings, installations)
    typelib = (
        inspect_analysis_typelib(selected.install_path / "code" / "bin" / "CATAnalysisTypLib.tlb")
        if selected
        else {"available": False, "interfaces": {}}
    )
    return {
        "platform": os.name,
        "com": com_registration(),
        "minimum_supported_release_index": settings.minimum_supported_release_index,
        "release_policy": (
            "B28/V5-6R2018 and newer are targeted; B33 is the local validation target. "
            "Newer releases retain the full tool surface and are gated by detected interfaces."
        ),
        "selected_installation": selected.to_dict() if selected else None,
        "installations": [item.to_dict() for item in installations],
        "analysis_typelib": typelib,
        "license_note": (
            "Installed files and type libraries do not prove that GPS/GAS/EST licences are available. "
            "A live CATIA Analysis document operation is required to verify licensing."
        ),
    }
