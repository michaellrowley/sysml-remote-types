import argparse
import json
import sys
from pathlib import Path

from . import emit, fetch, kaitai, parser, spec, sysml, update
from .model import ImportError_


def _targets(path):
    target = Path(path)
    if target.is_dir():
        return [
            str(candidate)
            for candidate in sorted(target.rglob("*"))
            if candidate.is_file() and candidate.suffix.lower() == ".sysml"
        ]
    return [path]


def main(argv=None):
    models = list(spec.load_types()["data_models"])
    ap = argparse.ArgumentParser(prog="typelink")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate and list @TypeLink usages (JSON)")
    c.add_argument("files", nargs="+", help="SysML files or directories of SysML files")
    e = sub.add_parser(
        "expand", help="flesh out @TypeLink items (directory targets are expanded in place)")
    e.add_argument("file", help="SysML file or directory of SysML files")
    e.add_argument("-o", "--output", help="write here instead of stdout (file targets only)")
    e.add_argument("--data-model", choices=models, help="C/C++ data model (default from spec)")
    e.add_argument("--max-bytes", type=int, default=fetch.DEFAULT_MAX_BYTES,
                   help="refuse linked resources larger than this (default: %(default)s)")
    e.add_argument("--clone-repo", action="store_true",
                   help="clone GitHub repositories temporarily to resolve types across files")
    k = sub.add_parser(
        "kaitai", help="generate Kaitai Struct YAML from SysML files or directories")
    k.add_argument("file", help="SysML file or directory of SysML files")
    k.add_argument("--item", help="item definition to use as the Kaitai root")
    k.add_argument("-o", "--output",
                   help="write here instead of stdout (directory targets use an output directory)")
    k.add_argument("--expanded", action="store_true",
                   help="skip @TypeLink resolution for imported SysMLv2 input")
    k.add_argument("--max-bytes", type=int, default=fetch.DEFAULT_MAX_BYTES,
                   help="refuse linked resources larger than this (default: %(default)s)")
    k.add_argument("--clone-repo", action="store_true",
                   help="clone GitHub repositories temporarily to resolve types across files")
    k.add_argument("--endian", choices=("le", "be"), default="le",
                   help="byte order when not defined by the layout (default: %(default)s)")
    k.add_argument("--bit-endian", choices=("le", "be"), default="le",
                   help="bit order for packed and offset-based fields; tagged wire uses be "
                   "(default: %(default)s)")
    k.add_argument("--integer-signedness", choices=("signed", "unsigned"),
                   default="unsigned",
                   help="default for Integer fields without metadata (default: %(default)s)")
    sub.add_parser("sync-spec", help="embed spec files into spec/RFC.md")
    sub.add_parser("update", help="install the latest version from the main branch")
    args = ap.parse_args(argv)

    if args.cmd == "sync-spec":
        spec.sync_rfc()
        return 0
    try:
        if args.cmd == "update":
            revision = update.install_latest()
            print(f"Updated typelink from {update.BRANCH} ({revision[:12]}).")
            return 0
        if args.cmd == "expand":
            directory = Path(args.file).is_dir()
            if directory and args.output:
                raise ValueError("--output cannot be used with a directory target")
            files = _targets(args.file)
            status = 0
            for file in files:
                try:
                    with open(file) as fh:
                        out = emit.expand(fh.read(), args.data_model,
                                          max_bytes=args.max_bytes,
                                          clone_repo=args.clone_repo,
                                          warn=lambda m: print(
                                              "warning:", m, file=sys.stderr))
                    if args.output:
                        with open(args.output, "w") as fh:
                            fh.write(out)
                    elif directory:
                        with open(file, "w") as fh:
                            fh.write(out)
                    else:
                        sys.stdout.write(out)
                except (parser.TypeLinkError, sysml.SysMLSyntaxError,
                        ImportError_, ValueError, OSError) as ex:
                    if not directory:
                        raise
                    print(f"{file}: {ex}", file=sys.stderr)
                    status = 1
            return status
        if args.cmd == "kaitai":
            directory = Path(args.file).is_dir()
            output_dir = Path(args.output) if directory and args.output else None
            if output_dir and output_dir.exists() and not output_dir.is_dir():
                raise ValueError("--output must be a directory for a directory target")
            status = 0
            for file in _targets(args.file):
                try:
                    with open(file) as fh:
                        text = fh.read()
                    if not args.expanded:
                        text = emit.expand(
                            text, max_bytes=args.max_bytes,
                            clone_repo=args.clone_repo,
                            warn=lambda m: print("warning:", m, file=sys.stderr))
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
                        with open(args.output, "w") as fh:
                            fh.write(out)
                    else:
                        sys.stdout.write(out)
                except (parser.TypeLinkError, sysml.SysMLSyntaxError,
                        kaitai.KaitaiError, ImportError_, ValueError, OSError) as ex:
                    if not directory:
                        raise
                    print(f"{file}: {ex}", file=sys.stderr)
                    status = 1
            return status
        status, found = 0, []
        for f in (file for path in args.files for file in _targets(path)):
            try:
                with open(f) as fh:
                    found += [{"file": f, "element": l.element, "origin": l.origin, "uri": l.uri}
                              for l in parser.parse(fh.read())]
            except (parser.TypeLinkError, sysml.SysMLSyntaxError) as ex:
                print(f"{f}: {ex}", file=sys.stderr)
                status = 1
        print(json.dumps(found, indent=2))
        return status
    except (parser.TypeLinkError, sysml.SysMLSyntaxError, kaitai.KaitaiError,
            update.UpdateError,
            ImportError_, ValueError, OSError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
