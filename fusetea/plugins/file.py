#!/usr/bin/env python3

import sys
import pathlib
from errno import ENOENT
from urllib.parse import unquote, urlsplit

from fusepy import FUSE, FuseOSError

from fusetea.utils.httpresource import HTTPResource, add_common_arguments, dir_attrs
from fusetea.utils.readahead import Readahead


class File(HTTPResource):
    def __init__(self, url, headers=None, user=None, password=None, access_log=None, timeout=10, retries=5, user_agent=None):
        super().__init__("file", url, headers, user, password, access_log, timeout, retries, user_agent)

        # the file is exposed at the root of the mount point, with the name
        # found in the URL
        self.path = "/" + unquote(pathlib.PurePosixPath(urlsplit(url).path).name)

        self.urls[self.path] = url
        self.cache["/"] = dir_attrs()
        self.cache[self.path] = self.startup(self.stat_url, url)

    def readdir(self, path, fh):
        if path != "/":
            raise FuseOSError(ENOENT)
        return [".", "..", self.path[1:]]

    def getattr(self, path, fh=None):
        if path not in self.cache:
            raise FuseOSError(ENOENT)
        return self.cache[path]


def add_subparser(subparsers):
    parser = subparsers.add_parser("file", help="Standalone file plugin")

    parser.add_argument(
        "url", help="URL to the file (e.g. https://files.corp.local/disk.vmdk)"
    )
    parser.add_argument("mount", help="Mount point")
    add_common_arguments(parser, "file")
    parser.set_defaults(func=run)


def run(args):
    if not pathlib.PurePosixPath(urlsplit(args.url).path).name:
        print("[!] The URL must point to a file", file=sys.stderr)
        exit(1)

    FUSE(
        Readahead(
            File(
                args.url,
                headers=args.headers,
                user=args.user,
                password=args.password,
                access_log=args.access_log,
                timeout=args.timeout,
                retries=args.retries,
                user_agent=args.user_agent,
            ),
            args.page_size,
            args.cache_size,
        ),
        args.mount,
        foreground=True,
        nothreads=False,
        allow_other=not args.do_not_allow_other,
    )
