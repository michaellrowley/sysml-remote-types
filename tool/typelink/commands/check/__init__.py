"""CLI command that validates TypeLink annotations and prints their JSON records."""
import json
import sys

from ... import parser as type_parser, sysml
from .._files import targets


def register(subparsers):
    command = subparsers.add_parser(
        "check", help="validate and list @TypeLink usages (JSON)")
    command.add_argument(
        "files", nargs="+", help="SysML files or directories of SysML files")
    command.set_defaults(command_handler=run)


def run(args):
    """Collect valid links while reporting parse errors for each input file."""
    status, found = 0, []
    for file in (file for path in args.files for file in targets(path)):
        try:
            with open(file) as source:
                found += [
                    {"file": file, "element": link.element,
                     "origin": link.origin, "uri": link.uri}
                    for link in type_parser.parse(source.read())
                ]
        except (type_parser.TypeLinkError, sysml.SysMLSyntaxError) as ex:
            print(f"{file}: {ex}", file=sys.stderr)
            status = 1
    print(json.dumps(found, indent=2))
    return status
