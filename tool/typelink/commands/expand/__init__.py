"""CLI command that expands linked source types into SysML metadata."""
import sys
from pathlib import Path

from ... import emit, fetch, parser, spec, sysml
from ...model import ImportError_
from .._files import targets


def register(subparsers):
    """Register expansion options; data-model choices come from the shared spec."""
    command = subparsers.add_parser(
        "expand", help="flesh out @TypeLink items (directory targets are expanded in place)")
    command.add_argument(
        "file", help="SysML file or directory of SysML files")
    command.add_argument(
        "-o", "--output", help="write here instead of stdout (file targets only)")
    command.add_argument(
        "--data-model", choices=list(spec.load_types()["data_models"]),
        help="C/C++ data model (default from spec)")
    command.add_argument(
        "--max-bytes", type=int, default=fetch.DEFAULT_MAX_BYTES,
        help="refuse linked resources larger than this (default: %(default)s)")
    command.add_argument(
        "--clone-repo", action="store_true",
        help="clone GitHub repositories temporarily to resolve types across files")
    command.set_defaults(command_handler=run)


def run(args):
    """Expand one file or process a directory as a best-effort batch."""
    directory = Path(args.file).is_dir()
    if directory and args.output:
        raise ValueError("--output cannot be used with a directory target")
    status = 0
    for file in targets(args.file):
        try:
            with open(file) as source:
                out = emit.expand(
                    source.read(), args.data_model, max_bytes=args.max_bytes,
                    clone_repo=args.clone_repo,
                    warn=lambda message: print("warning:", message, file=sys.stderr))
            if args.output:
                with open(args.output, "w") as output:
                    output.write(out)
            elif directory:
                with open(file, "w") as output:
                    output.write(out)
            else:
                sys.stdout.write(out)
        except (parser.TypeLinkError, sysml.SysMLSyntaxError,
                ImportError_, ValueError, OSError) as ex:
            if not directory:
                raise
            # A bad file should not prevent other files in a directory from expanding.
            print(f"{file}: {ex}", file=sys.stderr)
            status = 1
    return status
