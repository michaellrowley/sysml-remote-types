"""CLI command that generates source headers from SysML models."""
import re
import sys
from pathlib import Path

from ... import emit, fetch, headers, kaitai, parser, sysml
from .._files import targets


def _top_level_items(text):
    tree = sysml.parse(text)
    items = []
    for context in sysml.find_all(tree, sysml.P.ItemDefinitionContext):
        if sysml.ancestor(context.parentCtx, sysml.P.ItemDefinitionContext) is not None:
            continue
        declaration = sysml.find_first(context, sysml.P.DefinitionDeclarationContext)
        name = sysml.decl_name(declaration)
        packages = []
        parent = context.parentCtx
        while parent is not None:
            if isinstance(parent, sysml.P.PackageContext):
                package = parent.packageDeclaration()
                if package and package.identification():
                    packages.append(sysml.decl_name(package))
            parent = parent.parentCtx
        selector = "::".join(list(reversed(packages)) + [name])
        items.append(selector)
    return items


def _schema_path(header_path, item, multiple):
    stem = header_path.stem
    if multiple:
        suffix = re.sub(r"[^A-Za-z0-9_]+", "_", item).strip("_").lower()
        stem += "_" + (suffix or "item")
    return header_path.with_name(stem).with_suffix(".ksy")


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
        "--skip-kaitai", action="store_true",
        help="disable the default Kaitai schema generation stage")
    command.add_argument(
        "--max-bytes", type=int, default=fetch.DEFAULT_MAX_BYTES,
        help="refuse linked resources larger than this (default: %(default)s)")
    command.add_argument(
        "--clone-repo", action="store_true",
        help="clone GitHub repositories temporarily to resolve types across files")
    command.set_defaults(command_handler=run)


def run(args):
    """Run expansion, Kaitai generation, then header generation for each model."""
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
            header_path = (
                (output_dir / Path(file).relative_to(Path(args.file))).with_suffix(".hpp")
                if output_dir else Path(file).with_suffix(".hpp")
            )
            if not directory and args.output:
                header_path = Path(args.output)
            schemas = []
            if not args.skip_kaitai:
                items = _top_level_items(text)
                for item in items:
                    schemas.append((
                        _schema_path(header_path, item, len(items) > 1),
                        kaitai.generate(text, item=item)))
            output = headers.generate(text, language=args.language)
            for schema_path, schema in schemas:
                schema_path.parent.mkdir(parents=True, exist_ok=True)
                schema_path.write_text(schema)
            if output_dir:
                header_path.parent.mkdir(parents=True, exist_ok=True)
                header_path.write_text(output)
            elif directory:
                header_path.write_text(output)
            elif args.output:
                header_path.parent.mkdir(parents=True, exist_ok=True)
                header_path.write_text(output)
            else:
                sys.stdout.write(output)
        except (parser.TypeLinkError, sysml.SysMLSyntaxError, kaitai.KaitaiError,
                headers.HeaderError, ValueError, OSError) as ex:
            if not directory:
                raise
            print(f"{file}: {ex}", file=sys.stderr)
            status = 1
    return status
