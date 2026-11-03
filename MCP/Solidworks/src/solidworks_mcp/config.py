from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime options for the interactive SolidWorks agent."""

    part_template: Path = Path(
        os.getenv(
            "SOLIDWORKS_PART_TEMPLATE",
            "C:/ProgramData/SolidWorks/SOLIDWORKS 2025/templates/gb_part.prtdot",
        )
    )
    assembly_template: Path = Path(
        os.getenv(
            "SOLIDWORKS_ASSEMBLY_TEMPLATE",
            "C:/ProgramData/SolidWorks/SOLIDWORKS 2025/templates/gb_assembly.asmdot",
        )
    )
    visible: bool = os.getenv("SOLIDWORKS_VISIBLE", "true").lower() == "true"
    operation_cache_size: int = int(os.getenv("SOLIDWORKS_OPERATION_CACHE_SIZE", "128"))
    operation_timeout_seconds: float = float(
        os.getenv("SOLIDWORKS_OPERATION_TIMEOUT_SECONDS", "180")
    )
    interactive_mode: bool = (
        os.getenv("SOLIDWORKS_INTERACTIVE_MODE", "true").lower() == "true"
    )
    single_document_mode: bool = (
        os.getenv("SOLIDWORKS_SINGLE_DOCUMENT_MODE", "false").lower() == "true"
    )
    verify_feature_tree: bool = True
    operation_journal_path: Path | None = field(
        default_factory=lambda: Path(
            os.getenv(
                "SOLIDWORKS_OPERATION_JOURNAL",
                str(
                    Path(os.getenv("LOCALAPPDATA", str(Path.home() / ".local/share")))
                    / "SolidWorksAgentMCP/operations.sqlite3"
                ),
            )
        )
    )
    redraw_after_operation: bool = (
        os.getenv("SOLIDWORKS_REDRAW_AFTER_OPERATION", "false").lower() == "true"
    )
