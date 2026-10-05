import argparse
import json
import sys
from dataclasses import asdict

from . import parser, spec


def main(argv=None):
    ap = argparse.ArgumentParser(prog="typelink")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate and list @TypeLink usages (JSON)")
    c.add_argument("files", nargs="+")
    sub.add_parser("sync-spec", help="embed spec/typelink.sysml into spec/RFC.md")
    args = ap.parse_args(argv)
    if args.cmd == "sync-spec":
        spec.sync_rfc()
        return 0
    status, out = 0, []
    for f in args.files:
        try:
            with open(f) as fh:
                out += [dict(asdict(l), file=f) for l in parser.parse(fh.read())]
        except parser.TypeLinkError as e:
            print(f"{f}: {e}", file=sys.stderr)
            status = 1
    print(json.dumps(out, indent=2))
    return status


if __name__ == "__main__":
    sys.exit(main())
