"""Machine paths are private configuration, never MCP request parameters."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
import os
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent.parent


def _absolute(value: str, name: str) -> Path:
    if not isinstance(value, str) or not value.strip() or '<' in value or '>' in value:
        raise ValueError(f'{name} must be an explicit absolute local path')
    path = Path(value).expanduser()
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError(f'{name} must be an absolute local path')
    return path.resolve()


@dataclass(frozen=True)
class Settings:
    workspace: Path
    eplan_exe: Path | None = None
    help_roots: tuple[Path, ...] = ()
    profile: str = 'review'
    timeout_seconds: float = 65.0
    expected_build: str = '2.9.4.14642'


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    values = {}
    if os.environ.get('EPLAN_MCP_CONFIG'):
        config = _absolute(os.environ['EPLAN_MCP_CONFIG'], 'EPLAN_MCP_CONFIG')
        values = json.loads(config.read_text(encoding='utf-8-sig'))
        if not isinstance(values, dict) or values.get('schema_version') != 1:
            raise ValueError('Unsupported EPLAN configuration schema; expected 1')
        unknown = set(values) - {'schema_version', 'workspace', 'eplan_exe', 'help_roots',
                                 'profile', 'timeout_seconds', 'expected_build'}
        if unknown:
            raise ValueError('Unknown EPLAN configuration keys: ' + ', '.join(sorted(unknown)))
    workspace = os.environ.get('EPLAN_MCP_WORKSPACE') or values.get('workspace')
    exe = os.environ.get('EPLAN_EXE') or values.get('eplan_exe')
    profile = os.environ.get('EPLAN_MCP_PROFILE') or values.get('profile', 'review')
    if profile not in {'review', 'trial'}:
        raise ValueError('EPLAN_MCP_PROFILE must be review or trial')
    timeout = float(values.get('timeout_seconds', 65))
    if not math.isfinite(timeout) or not 0.1 <= timeout <= 180:
        raise ValueError('timeout_seconds must be finite and between 0.1 and 180')
    roots = values.get('help_roots', [])
    if not isinstance(roots, list) or len(roots) > 8:
        raise ValueError('help_roots must contain at most eight local directories')
    return Settings(
        workspace=_absolute(workspace, 'workspace') if workspace else SOURCE_ROOT / 'private',
        eplan_exe=_absolute(exe, 'eplan_exe') if exe else None,
        help_roots=tuple(_absolute(p, 'help_roots') for p in roots),
        profile=profile, timeout_seconds=timeout,
        expected_build=str(values.get('expected_build', '2.9.4.14642')),
    )


def workspace_root() -> Path:
    return load_settings().workspace


def source_root() -> Path:
    return SOURCE_ROOT
