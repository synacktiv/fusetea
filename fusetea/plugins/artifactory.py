#!/usr/bin/env python3

import functools
import time
import pathlib

from stat import S_IFDIR, S_IFREG
from fusepy import FUSE, Operations

from fusetea.utils.accesslog import default_log_path, log_entry, open_log
from fusetea.utils.readahead import Readahead
from fusetea.utils.stealthysession import StealthySession


class Artifactory(Operations):
    def __init__(self, host, repokey, headers=None, access_log=None):
        self.host = host
        self.repokey = repokey
        self.session = StealthySession(headers=headers)
        self._log = open_log("artifactory", access_log)

        self.check_authentication()

        self.cache = {}

    def check_authentication(self):
        url = f"{self.host}ui/api/v1/ui/nativeBrowser/{self.repokey}"
        response = self.session.get(url)
        if response.status_code == 401:
            print(
                "[*] Authentication needed. Please authenticate and set the appropriate headers with the --header flag, or implement the authentication and send a Merge Request."
            )
            exit(1)

    def update_cache(self, data):
        now = time.time()
        path = pathlib.Path(f'/{data["path"]}/')

        self.cache[str(path.resolve())] = dict(
            st_mode=(S_IFDIR | 0o755),
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
            st_nlink=2,
        )

        for child in data["children"]:
            if child["folder"]:
                self.cache[str((path / child["name"]).resolve())] = dict(
                    st_mode=(S_IFDIR | 0o755),
                    st_ctime=child["lastModified"],
                    st_mtime=child["lastModified"],
                    st_atime=child["lastModified"],
                    st_nlink=2,
                )
            else:
                self.cache[str((path / child["name"]).resolve())] = dict(
                    st_mode=(S_IFREG | 0o755),
                    st_ctime=child["lastModified"],
                    st_size=child["size"],
                    st_mtime=child["lastModified"],
                    st_atime=child["lastModified"],
                    st_nlink=1,
                )

    @functools.cache
    def http_readdir(self, path):
        url = f"{self.host}ui/api/v1/ui/nativeBrowser/{self.repokey}{path}"

        response = self.session.get(url)

        self.update_cache(response.json())

        return [i["name"] for i in response.json()["children"]]

    def read(self, path, size, offset, fh):
        headers = {}

        # do not send the headers if we are asking for the whole file
        if not (offset == 0 and size >= self.cache[path]["st_size"]):
            headers.update(
                {
                    "Range": f"bytes={offset}-{(offset+size)-1}",
                }
            )

        url = f"{self.host}ui/api/v1/download"
        params = {"repoKey": self.repokey, "path": path, "isNativeBrowsing": "true"}

        response = self.session.get(
            url,
            headers=headers,
            params=params,
            verify=False,
        )

        log_entry(self._log, "read", label=self.repokey, path=path, offset=offset, size=size)
        return response.content

    def readdir(self, path, fh):
        cached = path in self.cache
        entries = self.http_readdir(path)
        if not cached:
            log_entry(self._log, "readdir", label=self.repokey, path=path, entries=entries)
        return [".", ".."] + entries

    def getattr(self, path, fh=None):
        if path not in self.cache.keys():
            self.http_readdir(path)
        return self.cache[path]


def add_subparser(subparsers):
    parser = subparsers.add_parser("artifactory", help="Artifactory plugin")
    parser.add_argument(
        "host", help="URL to artifactory (e.g. https://artifactory.corp.local/)"
    )
    parser.add_argument("repokey", help="Repository to mount (e.g. libs-release-local)")
    parser.add_argument("mount", help="Mount point")
    parser.add_argument(
        "--page-size",
        required=False,
        default=2 * 1024 * 1024,
        help="Readahead cache page size (number of bytes to read ahead)",
    )
    parser.add_argument(
        "--cache-size",
        required=False,
        default=100,
        help="Readahead cache size (number of pages)",
    )
    parser.add_argument(
        "--header",
        required=False,
        help="Headers to send",
        action="append",
        dest="headers",
    )
    parser.add_argument(
        "--access-log",
        default=None,
        metavar="FILE",
        help=f"Log file for open/read/readdir operations (default: {default_log_path('artifactory')})",
    )
    parser.set_defaults(func=run)


def run(args):
    if args.host[-1] != "/":
        args.host += "/"

    FUSE(
        Readahead(
            Artifactory(args.host, args.repokey, headers=args.headers, access_log=args.access_log),
            args.page_size,
            args.cache_size,
        ),
        args.mount,
        foreground=True,
        nothreads=False,
        allow_other=not args.do_not_allow_other,
    )
