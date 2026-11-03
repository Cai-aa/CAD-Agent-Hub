"""Write Codex TOML without Windows text-mode newline expansion."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import tomllib


def validated_toml_bytes(text: str) -> bytes:
    canonical = text.replace("\r\n", "\n")
    if "\r" in canonical:
        raise ValueError("TOML contains a lone carriage return; leave the live config unchanged")
    payload = canonical.encode("utf-8")
    # Parse exactly what will be written. read_text() can hide malformed CRCRLF.
    tomllib.loads(payload.decode("utf-8"))
    return payload


def write_validated_config(path: Path, text: str, *, expected_original: bytes) -> bytes:
    payload = validated_toml_bytes(text)
    if path.read_bytes() != expected_original:
        raise RuntimeError("Config changed concurrently; refusing to replace it")
    fd, temporary_name = tempfile.mkstemp(prefix="config-", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != expected_original:
            raise RuntimeError("Config changed concurrently; refusing to replace it")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return payload
