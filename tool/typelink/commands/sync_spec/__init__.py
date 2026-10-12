from ... import spec


def register(subparsers):
    command = subparsers.add_parser(
        "sync-spec", help="embed spec files into spec/RFC.md")
    command.set_defaults(command_handler=run)


def run(args):
    spec.sync_rfc()
    return 0
