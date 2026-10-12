"""Auto-discovered CLI command packages."""
from importlib import import_module
from pkgutil import iter_modules


def register_all(subparsers):
    """Load each command package and give it the shared argparse subparsers."""
    for module in sorted(iter_modules(__path__), key=lambda item: item.name):
        if not module.ispkg or module.name.startswith("_"):
            continue
        command = import_module(f"{__name__}.{module.name}")
        command.register(subparsers)
