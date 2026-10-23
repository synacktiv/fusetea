import os
import stat
import sys
import email.utils
from errno import EACCES, EIO
from stat import S_IFDIR, S_IFREG

import requests
import requests.auth
from fusepy import FuseOSError, Operations

from fusetea.utils.accesslog import default_log_path, log_entry, open_log
from fusetea.utils.retry import add_retry_arguments, request_with_retry
from fusetea.utils.stealthysession import StealthySession, add_user_agent_argument


def dir_attrs(mtime=0):
    return dict(
        st_mode=(S_IFDIR | 0o755),
        st_ctime=mtime,
        st_mtime=mtime,
        st_atime=mtime,
        st_nlink=2,
    )


def file_attrs(size, mtime=0):
    return dict(
        st_mode=(S_IFREG | 0o755),
        st_ctime=mtime,
        st_size=size,
        st_mtime=mtime,
        st_atime=mtime,
        st_nlink=1,
    )


def is_dir(attrs):
    return stat.S_ISDIR(attrs["st_mode"])


class HTTPResource(Operations):
    """Base class for plugins serving files from a plain web server
    supporting Range requests. Subclasses fill self.urls (FUSE path -> URL)
    and self.cache (FUSE path -> attributes)."""

    def __init__(self, plugin, label, headers=None, user=None, password=None, access_log=None, timeout=10, retries=5, user_agent=None):
        self.label = label
        self.timeout = timeout
        self.retries = retries
        self.session = StealthySession(headers=headers, user_agent=user_agent)
        if user is not None:
            self.session.auth = requests.auth.HTTPBasicAuth(user, password or "")
        # compressed responses would break both Content-Length and Range
        # offsets, ask for the raw content unless the user decided otherwise
        if not any(h.split(":", 1)[0].strip().lower() == "accept-encoding" for h in headers or []):
            self.session.headers["Accept-Encoding"] = "identity"
        self._log = open_log(plugin, access_log)

        self.cache = {}
        self.urls = {}

    def startup(self, func, *args):
        # run the first request of the plugin, exiting nicely on failure
        try:
            return func(*args)
        except FuseOSError as e:
            print(f"[!] Cannot access {self.label}: {os.strerror(e.errno)}", file=sys.stderr)
            if e.errno == EACCES:
                print(
                    "[*] Authentication needed. Use --user/--password for basic authentication or --header",
                    file=sys.stderr,
                )
            exit(1)
        except requests.RequestException as e:
            print(f"[!] Cannot access {self.label}: {e}", file=sys.stderr)
            exit(1)

    def request(self, method, url, validate=None, **kwargs):
        return request_with_retry(
            self.session,
            method,
            url,
            self.timeout,
            self.retries,
            log=self._log,
            label=self.label,
            validate=validate,
            **kwargs,
        )

    def stat_url(self, url):
        response = self.request("HEAD", url, allow_redirects=True)
        size = response.headers.get("Content-Length")
        if size is None:
            # no size in HEAD response, ask for the first byte instead
            response = self.request("GET", url, headers={"Range": "bytes=0-0"}, stream=True)
            response.close()
            if response.status_code == 206:
                size = response.headers.get("Content-Range", "").rsplit("/", 1)[-1]
            else:
                size = response.headers.get("Content-Length")
        if size is None or not size.isdigit():
            raise FuseOSError(EIO)

        mtime = 0
        last_modified = response.headers.get("Last-Modified")
        if last_modified:
            try:
                mtime = email.utils.parsedate_to_datetime(last_modified).timestamp()
            except (TypeError, ValueError):
                pass
        return file_attrs(int(size), mtime)

    def read(self, path, size, offset, fh):
        headers = {}
        file_size = self.cache[path]["st_size"]

        # do not send the headers if we are asking for the whole file
        if not (offset == 0 and size >= file_size):
            headers.update(
                {
                    "Range": f"bytes={offset}-{(offset+size)-1}",
                }
            )

        def validate(response):
            # 206 is the requested range, 200 the whole file (no Range sent,
            # or not supported by the server)
            expected = min(size, file_size - offset) if response.status_code == 206 else file_size
            if len(response.content) != expected:
                return f"expected {expected} bytes, got {len(response.content)}"
            return None

        response = self.request("GET", self.urls[path], validate=validate, headers=headers)

        log_entry(self._log, "read", label=self.label, path=path, offset=offset, size=size)
        if response.status_code == 206 or not headers:
            return response.content
        # the server ignored the Range header and sent the whole file
        return response.content[offset : offset + size]


def add_common_arguments(parser, plugin):
    parser.add_argument("-u", "--user", required=False, help="Username (basic authentication)")
    parser.add_argument("-p", "--password", required=False, help="Password (basic authentication)")
    parser.add_argument(
        "-H",
        "--header",
        required=False,
        help="Header to send (e.g. 'Cookie: session=...'), can be repeated",
        action="append",
        dest="headers",
    )
    add_user_agent_argument(parser)
    add_retry_arguments(parser)
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
        "--access-log",
        default=None,
        metavar="FILE",
        help=f"Log file for open/read/readdir operations (default: {default_log_path(plugin)})",
    )
