import argparse
import json
import sys

from . import emit, fetch, parser, spec, sysml
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
    sub.add_parser("sync-spec", help="embed spec files into spec/RFC.md")
    args = ap.parse_args(argv)

    if args.cmd == "sync-spec":
        spec.sync_rfc()
        return 0
    try:
        if args.cmd == "expand":
            with open(args.file) as fh:
                out = emit.expand(fh.read(), args.data_model, max_bytes=args.max_bytes,
                                  warn=lambda m: print("warning:", m, file=sys.stderr))
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
    except (parser.TypeLinkError, sysml.SysMLSyntaxError, ImportError_, ValueError, OSError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
