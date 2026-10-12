import argparse
import sys

from . import commands


def build_parser():
    parser = argparse.ArgumentParser(prog="typelink")
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    commands.register_all(subparsers)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.command_handler(args)
    except (ValueError, OSError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
