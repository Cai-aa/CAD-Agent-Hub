from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable


class ContractError(ValueError):
    """Raised before an invalid request crosses the MCP/COM boundary."""


def require_text(value: Any, name: str, *, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    result = value.strip()
    if len(result) > max_length:
        raise ContractError(f"{name} must be at most {max_length} characters")
    return result


def require_positive(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ContractError(f"{name} must be a positive number")
    return float(value)


def require_finite(value: Any, name: str) -> float:
    import math

    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ContractError(f"{name} must be a finite number")
    return float(value)


def require_index(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ContractError(f"{name} must be an integer >= 1")
    return value


def require_choice(value: Any, name: str, choices: Iterable[str]) -> str:
    result = require_text(value, name).lower()
    allowed = {item.lower() for item in choices}
    if result not in allowed:
        raise ContractError(f"{name} must be one of: {', '.join(sorted(allowed))}")
    return result


def require_safe_name(value: Any, name: str = "name") -> str:
    result = require_text(value, name, max_length=128)
    if not re.fullmatch(r"[^\\/:*?\"<>|\r\n]+", result):
        raise ContractError(f"{name} contains characters that are invalid in CATIA names")
    return result


def resolve_within(path: str | Path, roots: Iterable[Path], *, must_exist: bool = False) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    resolved_roots = tuple(Path(root).expanduser().resolve(strict=False) for root in roots)
    if not resolved_roots:
        raise ContractError("no allowed filesystem roots are configured")
    if not any(_is_relative_to(candidate, root) for root in resolved_roots):
        rendered = "; ".join(str(root) for root in resolved_roots)
        raise ContractError(f"path is outside the configured CATIA MCP roots: {rendered}")
    if must_exist and not candidate.exists():
        raise ContractError(f"path does not exist: {candidate}")
    return candidate


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
