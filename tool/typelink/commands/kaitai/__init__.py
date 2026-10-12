import sys
from pathlib import Path

from ... import emit, fetch, kaitai, parser, sysml
from ...model import ImportError_
from .._files import targets


def register(subparsers):
    command = subparsers.add_parser(
        "kaitai", help="generate Kaitai Struct YAML from SysML files or directories")
    command.add_argument("file", help="SysML file or directory of SysML files")
    command.add_argument("--item", help="item definition to use as the Kaitai root")
    command.add_argument(
        "-o", "--output",
        help="write here instead of stdout (directory targets use an output directory)")
    command.add_argument(
        "--expanded", action="store_true",
        help="skip @TypeLink resolution for imported SysMLv2 input")
    command.add_argument(
        "--max-bytes", type=int, default=fetch.DEFAULT_MAX_BYTES,
        help="refuse linked resources larger than this (default: %(default)s)")
    command.add_argument(
        "--clone-repo", action="store_true",
        help="clone GitHub repositories temporarily to resolve types across files")
    command.add_argument(
        "--endian", choices=("le", "be"), default="le",
        help="byte order when not defined by the layout (default: %(default)s)")
    command.add_argument(
        "--bit-endian", choices=("le", "be"), default="le",
        help="bit order for packed and offset-based fields; tagged wire uses be "
             "(default: %(default)s)")
    command.add_argument(
        "--integer-signedness", choices=("signed", "unsigned"), default="unsigned",
        help="default for Integer fields without metadata (default: %(default)s)")
    command.set_defaults(command_handler=run)


def run(args):
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
            out = kaitai.generate(
                text, item=args.item, endian=args.endian,
                bit_endian=args.bit_endian,
                integer_signedness=args.integer_signedness)
            if output_dir:
                relative = Path(file).relative_to(Path(args.file))
                output = (output_dir / relative).with_suffix(".ksy")
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(out)
            elif directory:
                Path(file).with_suffix(".ksy").write_text(out)
            elif args.output:
                with open(args.output, "w") as output:
                    output.write(out)
            else:
                sys.stdout.write(out)
        except (parser.TypeLinkError, sysml.SysMLSyntaxError, kaitai.KaitaiError,
                ImportError_, ValueError, OSError) as ex:
            if not directory:
                raise
            print(f"{file}: {ex}", file=sys.stderr)
            status = 1
    return status
