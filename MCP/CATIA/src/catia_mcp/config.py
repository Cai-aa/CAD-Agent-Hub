from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_paths(name: str, fallback: tuple[Path, ...]) -> tuple[Path, ...]:
    raw = os.getenv(name)
    if not raw:
        return fallback
    return tuple(Path(value.strip()) for value in raw.split(os.pathsep) if value.strip())


@dataclass(frozen=True)
class Settings:
    """Runtime settings; every path can be overridden without changing code."""

    workspace: Path
    allowed_roots: tuple[Path, ...]
    environment_name: str | None
    environment_directory: Path
    install_path: Path | None
    visible: bool
    operation_timeout_seconds: float
    startup_timeout_seconds: float
    operation_cache_size: int
    minimum_supported_release_index: int
    allow_legacy_release: bool

    @classmethod
    def from_env(cls) -> "Settings":
        workspace = Path(os.getenv("CATIA_MCP_WORKSPACE", str(Path.cwd() / "workspace")))
        default_roots = (workspace,)
        install_raw = os.getenv("CATIA_MCP_INSTALL_PATH")
        return cls(
            workspace=workspace,
            allowed_roots=_env_paths("CATIA_MCP_ALLOWED_ROOTS", default_roots),
            environment_name=os.getenv("CATIA_MCP_ENV_NAME") or None,
            environment_directory=Path(
                os.getenv("CATIA_MCP_ENV_DIR", r"C:\ProgramData\DassaultSystemes\CATEnv")
            ),
            install_path=Path(install_raw) if install_raw else None,
            visible=_env_bool("CATIA_MCP_VISIBLE", True),
            operation_timeout_seconds=float(os.getenv("CATIA_MCP_OPERATION_TIMEOUT_SECONDS", "300")),
            startup_timeout_seconds=float(os.getenv("CATIA_MCP_STARTUP_TIMEOUT_SECONDS", "120")),
            operation_cache_size=int(os.getenv("CATIA_MCP_OPERATION_CACHE_SIZE", "128")),
            minimum_supported_release_index=int(os.getenv("CATIA_MCP_MIN_RELEASE_INDEX", "28")),
            allow_legacy_release=_env_bool("CATIA_MCP_ALLOW_LEGACY", False),
        )
