"""Shared file selection for commands that accept SysML files or directories."""
from pathlib import Path


def targets(path):
    """Return one input file, or recursively sorted SysML files under a directory."""
    target = Path(path)
    if target.is_dir():
        # Sorting makes multi-file output and diagnostics deterministic.
        return [
            str(candidate)
            for candidate in sorted(target.rglob("*"))
            if candidate.is_file() and candidate.suffix.lower() == ".sysml"
        ]
    return [path]
