from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


class ContractError(ValueError):
    """Raised before an operation crosses the MCP/COM boundary."""


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value.strip()


def require_positive(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ContractError(f"{name} must be a positive number")
    return float(value)


@dataclass(frozen=True)
class Operation:
    """A deterministic, auditable command passed to the execution layer."""

    kind: Literal["new_part", "open_document", "save", "export", "inspect"]
    request_id: str
    parameters: dict[str, Any]
