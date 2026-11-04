"""Non-overwriting saves and retained backups for explicitly requested overwrite."""

from __future__ import annotations
import contextlib
import os
from pathlib import Path
import shutil
import uuid
from .contracts import ContractError
from .safety import SafetyError


@contextlib.contextmanager
def protected_output(target: Path, overwrite: bool = False):
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(target.name + ".swmcp.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise SafetyError(
            "OUTPUT_BUSY", f"Output is reserved by another operation: {target}"
        ) from exc
    os.close(descriptor)
    existed, backup = target.exists(), None
    try:
        if existed:
            if not overwrite:
                raise ContractError(
                    f"Output already exists; choose a new path or explicitly set overwrite=true: {target}"
                )
            if not target.is_file():
                raise ContractError("Output must be a regular file")
            backup_dir = target.parent / ".swmcp-backups"
            backup_dir.mkdir(exist_ok=True)
            backup = backup_dir / (uuid.uuid4().hex + "_" + target.name)
            shutil.copy2(target, backup)
        try:
            yield backup
            if not target.is_file() or target.stat().st_size == 0:
                raise SafetyError("SAVE_EMPTY", "Save did not produce a non-empty file")
        except BaseException:
            if backup:
                restore = target.with_name(uuid.uuid4().hex + ".restore")
                shutil.copy2(backup, restore)
                os.replace(restore, target)
            elif not existed and target.is_file():
                target.unlink()
            raise
    finally:
        lock.unlink(missing_ok=True)
