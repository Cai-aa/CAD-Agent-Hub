from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote


SKIP_DIRS = {".git", ".venv", "runs", "private", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {
    ".cs",
    ".csproj",
    ".props",
    ".targets",
    ".xml",
    ".bat",
    ".c",
    ".cmd",
    ".cpp",
    ".h",
    ".html",
    ".java",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".tcl",
    ".txt",
    ".yaml",
    ".yml",
}
BLOCKED_SUFFIXES = {
    ".dll",
    ".pdb",
    ".elk",
    ".zw1",
    ".sqlite3",
    ".mdb",
    ".aedt",
    ".aedtz",
    ".cas",
    ".dat",
    ".dump",
    ".h3d",
    ".hm",
    ".iges",
    ".igs",
    ".lammpstrj",
    ".mechdat",
    ".mph",
    ".mp4",
    ".odb",
    ".rst",
    ".step",
    ".stp",
    ".wbpj",
}
BLOCKED_ENDINGS = (".cas.h5", ".dat.h5", ".msh.h5")
WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z]:\\[^\s\"'<>|*?]+)")
SECRET_PATTERNS = (
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def repo_files(root: Path) -> list[Path]:
    # Audit exactly what Git can publish, including already tracked ignored files.
    # Build products ignored by Git are not public source candidates.
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root, capture_output=True, check=True,
        )
        return sorted({root / name for name in result.stdout.decode("utf-8").split("\0")
                       if name and (root / name).is_file()})
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(root).parts)
    )


def local_link_target(source: Path, raw_target: str) -> Path | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    target = target.split("#", 1)[0].strip()
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    if " " in target and not Path(target).exists():
        target = target.split(" ", 1)[0]
    target = unquote(target)
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    return (source.parent / target).resolve()


def audit(root: Path, max_file_mb: float = 10.0) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    max_bytes = int(max_file_mb * 1024 * 1024)

    for path in repo_files(root):
        relative = path.relative_to(root).as_posix()
        lower_name = path.name.lower()
        if path.stat().st_size > max_bytes:
            errors.append(f"large file exceeds {max_file_mb:g} MB: {relative}")
        elif path.stat().st_size > 1024 * 1024:
            warnings.append(f"large tracked candidate over 1 MB: {relative}")

        if path.suffix.lower() in BLOCKED_SUFFIXES or lower_name.endswith(BLOCKED_ENDINGS):
            errors.append(f"blocked solver/private artifact extension: {relative}")

        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"text file is not UTF-8: {relative}")
            continue

        for match in WINDOWS_PATH.finditer(text):
            errors.append(f"absolute Windows path in {relative}: {match.group(1)[:120]}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"credential-like value in {relative}: {pattern.pattern}")

        if path.suffix.lower() == ".md":
            for raw_target in MARKDOWN_LINK.findall(text):
                target = local_link_target(path, raw_target)
                if target is not None and not target.exists():
                    errors.append(f"broken Markdown link in {relative}: {raw_target}")

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit public repository safety and local Markdown links.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--max-file-mb", type=float, default=10.0)
    args = parser.parse_args()

    root = args.root.resolve()
    errors, warnings = audit(root, args.max_file_mb)
    for item in warnings:
        print(f"WARNING: {item}")
    for item in errors:
        print(f"ERROR: {item}")
    print(f"AUDIT_ERRORS={len(errors)} AUDIT_WARNINGS={len(warnings)}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
