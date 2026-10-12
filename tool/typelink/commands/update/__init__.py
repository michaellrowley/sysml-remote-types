"""CLI adapter for installing the latest published main-branch version."""
import sys

from ... import update


def register(subparsers):
    command = subparsers.add_parser(
        "update", help="install the latest version from the main branch")
    command.set_defaults(command_handler=run)


def run(args):
    """Install the latest revision and report the short revision identifier."""
    try:
        revision = update.install_latest()
    except update.UpdateError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    print(f"Updated typelink from {update.BRANCH} ({revision[:12]}).")
    return 0
