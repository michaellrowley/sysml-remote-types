import argparse
import json
import sys

from . import emit, fetch, kaitai, parser, spec, sysml
from .model import ImportError_


def main(argv=None):
    models = list(spec.load_types()["data_models"])
    ap = argparse.ArgumentParser(prog="typelink")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate and list @TypeLink usages (JSON)")
    c.add_argument("files", nargs="+")
    e = sub.add_parser("expand", help="flesh out items carrying @TypeLink from the linked type")
    e.add_argument("file")
    e.add_argument("-o", "--output", help="write here instead of stdout")
    e.add_argument("--data-model", choices=models, help="C/C++ data model (default from spec)")
    e.add_argument("--max-bytes", type=int, default=fetch.DEFAULT_MAX_BYTES,
                   help="refuse linked resources larger than this (default: %(default)s)")
    e.add_argument("--clone-repo", action="store_true",
                   help="clone GitHub repositories temporarily to resolve types across files")
    k = sub.add_parser("kaitai", help="generate Kaitai Struct YAML from a SysMLv2 item")
    k.add_argument("file")
    k.add_argument("--item", help="item definition to use as the Kaitai root")
    k.add_argument("-o", "--output", help="write here instead of stdout")
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
    args = ap.parse_args(argv)

    if args.cmd == "sync-spec":
        spec.sync_rfc()
        return 0
    try:
        if args.cmd == "expand":
            with open(args.file) as fh:
                out = emit.expand(fh.read(), args.data_model, max_bytes=args.max_bytes,
                                  clone_repo=args.clone_repo,
                                  warn=lambda m: print("warning:", m, file=sys.stderr))
            if args.output:
                with open(args.output, "w") as fh:
                    fh.write(out)
            else:
                sys.stdout.write(out)
            return 0
        if args.cmd == "kaitai":
            with open(args.file) as fh:
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
            if args.output:
                with open(args.output, "w") as fh:
                    fh.write(out)
            else:
                sys.stdout.write(out)
            return 0
        status, found = 0, []
        for f in args.files:
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
            ImportError_, ValueError, OSError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
