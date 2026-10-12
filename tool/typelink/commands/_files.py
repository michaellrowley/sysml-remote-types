from pathlib import Path


def targets(path):
    target = Path(path)
    if target.is_dir():
        return [
            str(candidate)
            for candidate in sorted(target.rglob("*"))
            if candidate.is_file() and candidate.suffix.lower() == ".sysml"
        ]
    return [path]
