"""Install the latest main-branch checkout without relying on the current tree."""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY_URL = "https://github.com/michaellrowley/sysml-remote-types.git"
BRANCH = "main"


class UpdateError(Exception):
    """An update command failed."""


def _run(command, **kwargs):
    try:
        return subprocess.run(command, check=True, **kwargs)
    except subprocess.CalledProcessError as ex:
        raise UpdateError(f"command failed with exit code {ex.returncode}: "
                          f"{' '.join(command)}") from ex
    except OSError as ex:
        raise UpdateError(f"could not run {command[0]}: {ex}") from ex


def install_latest():
    """Clone main temporarily and install from a persistent, revision-keyed checkout."""
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    cache_root = cache_home / "typelink" / "checkouts"
    cache_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="typelink-update-", dir=cache_root) as temp:
        checkout = Path(temp) / "repo"
        _run([
            "git", "clone", "--depth", "1", "--branch", BRANCH, "--single-branch",
            "--recurse-submodules", REPOSITORY_URL, str(checkout),
        ])
        result = _run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            capture_output=True, text=True)
        revision = result.stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise UpdateError(f"git returned an invalid revision: {revision!r}")

        persistent_checkout = cache_root / revision
        if not persistent_checkout.exists():
            try:
                checkout.replace(persistent_checkout)
            except FileExistsError:
                if not persistent_checkout.is_dir():
                    raise

    _run([
        sys.executable, "-m", "pip", "install", "--force-reinstall", "--editable",
        str(persistent_checkout / "tool"),
    ])
    return revision
