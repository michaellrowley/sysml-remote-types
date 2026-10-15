"""CLI command that generates source headers from SysML models."""
import sys
from pathlib import Path

from ... import emit, fetch, headers, parser, sysml
from .._files import targets


def register(subparsers):
    command = subparsers.add_parser(
        "header", help="generate source headers from SysML structure and behavior")
    command.add_argument("file", help="SysML file or directory of SysML files")
    command.add_argument(
        "--language", choices=headers.languages(), default="cpp",
        help="header language backend (default: %(default)s)")
    command.add_argument(
        "-o", "--output",
        help="write here instead of stdout (directory targets use an output directory)")
    command.add_argument(
        "--expanded", action="store_true",
        help="skip @TypeLink resolution for already-expanded SysML input")
    command.add_argument(
        "--max-bytes", type=int, default=fetch.DEFAULT_MAX_BYTES,
        help="refuse linked resources larger than this (default: %(default)s)")
    command.add_argument(
        "--clone-repo", action="store_true",
        help="clone GitHub repositories temporarily to resolve types across files")
    command.set_defaults(command_handler=run)


def run(args):
    """Generate headers, mirroring relative paths for directory output."""
    directory = Path(args.file).is_dir()
    output_dir = Path(args.output) if directory and args.output else None
    if output_dir and output_dir.exists() and not output_dir.is_dir():
        raise ValueError("--output must be a directory for a directory target")
    status = 0
    for file in targets(args.file):
        try:
            with open(file) as source:
                text = source.read()
            if not args.expanded:
                text = emit.expand(
                    text, max_bytes=args.max_bytes, clone_repo=args.clone_repo,
                    warn=lambda message: print("warning:", message, file=sys.stderr))
            output = headers.generate(text, language=args.language)
            if output_dir:
                relative = Path(file).relative_to(Path(args.file))
                destination = (output_dir / relative).with_suffix(".hpp")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(output)
            elif directory:
                Path(file).with_suffix(".hpp").write_text(output)
            elif args.output:
                Path(args.output).write_text(output)
            else:
                sys.stdout.write(output)
        except (parser.TypeLinkError, sysml.SysMLSyntaxError, headers.HeaderError,
                ValueError, OSError) as ex:
            if not directory:
                raise
            print(f"{file}: {ex}", file=sys.stderr)
            status = 1
    return status
