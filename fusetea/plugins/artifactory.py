#!/usr/bin/env python3

import functools
import os
import time
import pathlib

from errno import EACCES
from stat import S_IFDIR, S_IFREG
from fusetea.utils.fusecompat import FUSE, FuseOSError, Operations

from fusetea.utils.accesslog import default_log_path, log_entry, open_log
from fusetea.utils.readahead import Readahead
from fusetea.utils.retry import add_retry_arguments, expect_length, request_with_retry
from fusetea.utils.stealthysession import StealthySession, add_user_agent_argument


class Artifactory(Operations):
    def __init__(self, host, repokey, headers=None, access_log=None, timeout=10, retries=5, user_agent=None):
        self.host = host
        self.repokey = repokey
        self.timeout = timeout
        self.retries = retries
        self.session = StealthySession(headers=headers, user_agent=user_agent)
        self._log = open_log("artifactory", access_log)

        self.check_authentication()

        self.cache = {}

    def check_authentication(self):
        url = f"{self.host}ui/api/v1/ui/nativeBrowser/{self.repokey}"
        try:
            self.request(url)
        except FuseOSError as e:
            if e.errno == EACCES:
                print(
                    "[*] Authentication needed. Please authenticate and set the appropriate headers with the --header flag, or implement the authentication and send a Merge Request."
                )
            else:
                print(f"[!] Cannot access {url}: {os.strerror(e.errno)}")
            exit(1)

    def request(self, url, validate=None, **kwargs):
        return request_with_retry(
            self.session,
            "GET",
            url,
            self.timeout,
            self.retries,
            log=self._log,
            label=self.repokey,
            validate=validate,
            **kwargs,
        )

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

        response = self.request(url, validate=valid_json)

        self.update_cache(response.json())

        return [i["name"] for i in response.json()["children"]]

    def read(self, path, size, offset, fh):
        headers = {}
        validate = None

        # do not send the headers if we are asking for the whole file
        if not (offset == 0 and size >= self.cache[path]["st_size"]):
            headers.update(
                {
                    "Range": f"bytes={offset}-{(offset+size)-1}",
                }
            )
            validate = expect_length(min(size, self.cache[path]["st_size"] - offset))

        url = f"{self.host}ui/api/v1/download"
        params = {"repoKey": self.repokey, "path": path, "isNativeBrowsing": "true"}

        response = self.request(
            url,
            validate=validate,
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


def valid_json(response):
    # validate function for request_with_retry: listings must be JSON
    try:
        response.json()["children"]
    except (ValueError, KeyError, TypeError):
        return "invalid JSON listing"
    return None


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
        type=int,
        default=2 * 1024 * 1024,
        help="Readahead cache page size (number of bytes to read ahead)",
    )
    parser.add_argument(
        "--cache-size",
        required=False,
        type=int,
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
    add_user_agent_argument(parser)
    add_retry_arguments(parser)
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
            Artifactory(
                args.host,
                args.repokey,
                headers=args.headers,
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
