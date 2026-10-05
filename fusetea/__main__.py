import pkgutil
import importlib
import argparse
import urllib3

urllib3.disable_warnings()

import fusetea.plugins


def iter_namespace(ns_pkg):
    return pkgutil.iter_modules(ns_pkg.__path__, ns_pkg.__name__ + ".")


def main():
    discovered_plugins = {
        name: importlib.import_module(name)
        for finder, name, ispkg in iter_namespace(fusetea.plugins)
    }

    parser = argparse.ArgumentParser(prog="fusetea")
    parser.add_argument("--log-file", help="log file path")
    parser.add_argument(
        "--do-not-allow-other",
        action="store_true",
        help="do not allow other users to access mounted directories",
        default=False,
    )
    subparsers = parser.add_subparsers(help="subcommand help", required=True)

    for name, plugin in discovered_plugins.items():
        plugin.add_subparser(subparsers)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
