#!/usr/bin/env python3

import pathlib
from errno import ENOENT, ENOTDIR
from urllib.parse import unquote, urljoin, urlsplit

from fusepy import FUSE, FuseOSError
from bs4 import BeautifulSoup

from fusetea.utils.accesslog import log_entry
from fusetea.utils.httpresource import (
    HTTPResource,
    add_common_arguments,
    dir_attrs,
    is_dir,
)
from fusetea.utils.readahead import Readahead


class Folder(HTTPResource):
    def __init__(self, url, headers=None, user=None, password=None, access_log=None, timeout=10, retries=5, user_agent=None):
        super().__init__("folder", url, headers, user, password, access_log, timeout, retries, user_agent)

        self.urls["/"] = url
        self.cache["/"] = dir_attrs()
        # directory listings already fetched (FUSE path -> entries)
        self.listings = {}

        self.startup(self.list_directory, "/")

    def parse_listing(self, path, url, html):
        # works with apache2 and nginx listings: every link pointing to a
        # direct child of the directory is an entry, this skips parent
        # directory, sorting links (?C=N;O=D) and links outside of the listing
        base = urlsplit(url)
        entries = []

        soup = BeautifulSoup(html, "lxml")
        for link in soup.find_all("a", href=True):
            target = urljoin(url, link["href"])
            parsed = urlsplit(target)
            if (
                parsed.query
                or parsed.fragment
                or (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc)
                or not parsed.path.startswith(base.path)
            ):
                continue

            relative = parsed.path[len(base.path) :]
            name = unquote(relative.rstrip("/"))
            if not name or "/" in name or name in entries:
                continue

            entries.append(name)
            child = str(pathlib.PurePath(path) / name)
            self.urls[child] = target
            if relative.endswith("/"):
                self.cache[child] = dir_attrs()
            # file attributes are fetched by getattr, listings do not contain
            # exact sizes (e.g. "1.2K" for apache2)

        return entries

    def list_directory(self, path):
        response = self.request("GET", self.urls[path])
        # follow redirections (e.g. missing trailing slash) so that relative
        # links are resolved against the right URL
        self.urls[path] = response.url
        self.listings[path] = self.parse_listing(path, response.url, response.text)
        log_entry(self._log, "readdir", label=self.label, path=path, entries=self.listings[path])
        return self.listings[path]

    def readdir(self, path, fh):
        if path not in self.listings:
            if path not in self.urls:
                raise FuseOSError(ENOENT)
            self.list_directory(path)
        return [".", ".."] + self.listings[path]

    def getattr(self, path, fh=None):
        if path in self.cache:
            return self.cache[path]

        parent = str(pathlib.PurePath(path).parent)
        if path not in self.urls and parent not in self.listings:
            # path accessed before its parent directory was listed
            if not is_dir(self.getattr(parent)):
                raise FuseOSError(ENOTDIR)
            self.list_directory(parent)

        if path not in self.urls:
            raise FuseOSError(ENOENT)
        if path not in self.cache:
            self.cache[path] = self.stat_url(self.urls[path])
        return self.cache[path]


def add_subparser(subparsers):
    parser = subparsers.add_parser("folder", help="Directory listing plugin (apache2, nginx)")

    parser.add_argument(
        "url", help="URL to the directory listing (e.g. https://files.corp.local/pub/)"
    )
    parser.add_argument("mount", help="Mount point")
    add_common_arguments(parser, "folder")
    parser.set_defaults(func=run)


def run(args):
    if args.url[-1] != "/":
        args.url += "/"

    FUSE(
        Readahead(
            Folder(
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
