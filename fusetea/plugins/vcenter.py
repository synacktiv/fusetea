#!/usr/bin/env python3

import time
import pathlib

from errno import ENOENT
from stat import S_IFDIR, S_IFREG

from fusetea.utils.fusecompat import FUSE, FuseOSError, Operations
from bs4 import BeautifulSoup
import requests
import requests.auth

from fusetea.utils.accesslog import default_log_path, log_entry, open_log
from fusetea.utils.readahead import Readahead
from fusetea.utils.stealthysession import StealthySession, add_user_agent_argument
from fusetea.utils.exceptions import InvalidCredentialsException
from fusetea.utils.retry import add_retry_arguments, expect_length, request_with_retry



class VCenter(Operations):
    def __init__(self, host, headers=None, user=None, password=None, access_log=None, timeout=10, retries=5, user_agent=None):
        self.host = host
        self.timeout = timeout
        self.retries = retries
        self.session = StealthySession(headers=headers, user_agent=user_agent)
        self._log = open_log("vcenter", access_log)

        self.user = user
        self.password = password

        self.check_authentication()

        self.cache = {}
        # datacenter paths as returned by vCenter, which may include parent
        # folders (e.g. "Europe/EU-1"), populated lazily by list_datacenters
        self.datacenters = None

    def extract_csrf_token(self, response):
        soup = BeautifulSoup(response, "lxml")
        token = soup.select_one('[name="VMware-CSRF-Token"]')
        return token["value"]

    def check_authentication(self):
        response = self.session.get(self.host + "folder")
        if response.status_code == 401:
            # perform authentication and display cookies
            if self.user and self.password:
                self.session.auth = requests.auth.HTTPBasicAuth(
                    self.user, self.password
                )
        elif response.status_code == 200 and "Authentication Required" in response.text:
            self.csrf_token = self.extract_csrf_token(response.text)
            data = {
                "VMware-CSRF-Token": self.csrf_token,
                "user": self.user,
                "password": self.password,
                "submit": "Log in",
            }
            response = self.session.post(self.host + "folder", data=data)
            if response.status_code == 200 and "Authentication Required" in response.text:
                raise InvalidCredentialsException("Invalid credentials")


    def get_datacenters(self):
        if self.datacenters is None:
            self.list_datacenters()
        return self.datacenters

    def split_path(self, path):
        # datacenters can be nested in folders, so they span a variable number
        # of path components: /<folder>/.../<datacenter>/<datastore>/<path>
        # returns (None, None, "") if path is above any datacenter
        parts = pathlib.PurePath(path).parts[1:]
        for datacenter in self.get_datacenters():
            dc_parts = tuple(datacenter.split("/"))
            if parts[: len(dc_parts)] == dc_parts:
                rest = parts[len(dc_parts) :]
                datastore = rest[0] if rest else None
                return datacenter, datastore, "/".join(rest[1:])
        return None, None, ""

    def list_folder(self, path):
        # lists the children of a folder containing datacenters
        parts = pathlib.PurePath(path).parts[1:]
        children = []
        for datacenter in self.get_datacenters():
            dc_parts = tuple(datacenter.split("/"))
            if len(dc_parts) > len(parts) and dc_parts[: len(parts)] == parts:
                child = dc_parts[len(parts)]
                if child not in children:
                    children.append(child)
        return children

    def request(self, url, params=None, headers=None, expected_length=None):
        if not self.session.auth:
            # we are performing AD authentication, CSRF token needed (do not ask me why)
            method = "POST"
            kwargs = {"data": {"VMware-CSRF-Token": self.csrf_token}}
        else:
            # this can happen when performing local authentication
            method = "GET"
            kwargs = {}
        return request_with_retry(
            self.session,
            method,
            url,
            self.timeout,
            self.retries,
            log=self._log,
            label=self.host,
            validate=expect_length(expected_length) if expected_length is not None else None,
            headers=headers,
            params=params,
            verify=False,
            **kwargs,
        )

    def read(self, path, size, offset, fh):
        datacenter, datastore, path_within_datastore = self.split_path(path)

        headers = {}
        expected_length = None

        # do not send the headers if we are asking for the whole file
        if not (offset == 0 and size >= self.cache[path]["st_size"]):
            headers.update(
                {
                    "Range": f"bytes={offset}-{(offset+size)-1}",
                }
            )
            expected_length = min(size, self.cache[path]["st_size"] - offset)

        url = self.host + "folder" + "/" + path_within_datastore
        params = {"dcPath": datacenter, "dsName": datastore}

        response = self.request(url, params=params, headers=headers, expected_length=expected_length)

        log_entry(self._log, "read", label=self.host, path=path, offset=offset, size=size)
        return response.content

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

    def parse_generic_listing(self, response, datacenter=None):
        # the lxml parser is faster according to the docs
        # thanks gemini
        filenames = []

        soup = BeautifulSoup(response, "lxml")
        listing = soup.find_all("table")
        if len(listing) < 2:
            return filenames
        for row in listing[1].find_all("tr"):
            if row.find("th"):
                # headers
                continue

            cells = row.find_all("td")

            filename = cells[0].find("a").text.strip()
            filenames.append(filename)

            if datacenter:
                filename = f"/{datacenter}/{filename}"

            # datacenter and datastores are considered as folders
            self.cache[filename] = dict(
                st_mode=(S_IFDIR | 0o755),
                st_ctime=0,
                st_mtime=0,
                st_atime=0,
                st_nlink=2,
            )

        return filenames

    def parse_datastore_listing(self, response, datacenter, datastore, path):
        # the lxml parser is faster according to the docs
        # thanks gemini
        filenames = []

        soup = BeautifulSoup(response, "lxml")
        listing = soup.find_all("table")
        if len(listing) < 2:
            return filenames
        skipped_first = False
        for row in listing[1].find_all("tr"):
            if row.find("th"):
                # skip headers
                continue

            if not skipped_first:
                # skip first entry (return to parent directory)
                skipped_first = True
                continue

            cells = row.find_all("td")

            filename = cells[0].find("a").text.strip()
            is_dir = filename.endswith("/")

            # we must remove the trailing slash to prevent readdir from failing
            filename = filename.rstrip("/")
            filenames.append(filename)

            if path:
                full_path = f"/{datacenter}/{datastore}/{path}/{filename}"
            else:
                full_path = f"/{datacenter}/{datastore}/{filename}"

            if is_dir:
                # we need to remove the ending slash so that readdir is happy
                self.cache[full_path] = dict(
                    st_mode=(S_IFDIR | 0o755),
                    st_ctime=0,
                    st_mtime=0,
                    st_atime=0,
                    st_nlink=2,
                )
            else:
                size = int(cells[2].text.strip())
                self.cache[full_path] = dict(
                    st_mode=(S_IFREG | 0o755),
                    st_ctime=0,
                    st_size=size,
                    st_mtime=0,
                    st_atime=0,
                    st_nlink=1,
                )

        return filenames

    def list_datacenters(self):
        # lists all datacenters
        response = self.request(self.host + "folder")
        self.datacenters = self.parse_generic_listing(response.text)
        return self.datacenters

    def list_datastores(self, datacenter):
        # lists all datastores within a datacenter
        params = {"dcPath": datacenter}
        response = self.request(self.host + "folder", params=params)
        return self.parse_generic_listing(response.text, datacenter=datacenter)

    def list_datastore(self, datacenter, datastore, path_within_datastore):
        # lists a specific datastore
        params = {"dcPath": datacenter, "dsName": datastore}
        response = self.request(
            self.host + "folder" + "/" + path_within_datastore, params=params
        )
        return self.parse_datastore_listing(
            response.text, datacenter, datastore, path_within_datastore
        )

    def readdir(self, path, fh):
        contents = [".", ".."]
        if path == "/":
            # refresh the datacenters list
            self.list_datacenters()
        datacenter, datastore, path_within_datastore = self.split_path(path)
        if datacenter is None:
            contents.extend(self.list_folder(path))
        elif datastore is None:
            contents.extend(self.list_datastores(datacenter))
        else:
            contents.extend(
                self.list_datastore(datacenter, datastore, path_within_datastore)
            )
        log_entry(self._log, "readdir", label=self.host, path=path, entries=contents[2:])
        return contents

    def getattr(self, path, fh=None):
        datacenter, datastore, path_within_datastore = self.split_path(path)
        if datacenter is None and path != "/" and not self.list_folder(path):
            raise FuseOSError(ENOENT)
        if not path_within_datastore:
            # root, folder, datacenter or datastore, always a directory
            return dict(
                st_mode=(S_IFDIR | 0o755),
                st_ctime=0,
                st_mtime=0,
                st_atime=0,
                st_nlink=2,
            )
        else:
            if not path in self.cache:
                # path accessed before its parent was listed, list the parent
                # to populate the cache
                parent = "/".join(path_within_datastore.split("/")[:-1])
                self.list_datastore(datacenter, datastore, parent)
            if not path in self.cache:
                raise FuseOSError(ENOENT)
            return self.cache[path]


def add_subparser(subparsers):
    parser = subparsers.add_parser("vcenter", help="vCenter plugin")

    parser.add_argument(
        "host", help="URL to vSphere (e.g. https://vcenter.corp.local/)"
    )
    parser.add_argument("mount", help="Mount point")
    parser.add_argument("--user", required=False, help="Username")
    parser.add_argument("--password", required=False, help="Password")
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
        help=f"Log file for open/read/readdir operations (default: {default_log_path('vcenter')})",
    )
    parser.set_defaults(func=run)


def run(args):
    if args.host[-1] != "/":
        args.host += "/"

    # logging.basicConfig(level=logging.DEBUG)

    FUSE(
        Readahead(
            VCenter(
                args.host,
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
