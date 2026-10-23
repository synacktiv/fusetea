import time
from errno import EACCES, EIO, ENOENT

import requests
from fusepy import FuseOSError

from fusetea.utils.accesslog import log_entry


def request_with_retry(session, method, url, timeout, retries, log=None, label=None, validate=None, **kwargs):
    """Send an HTTP request, retrying transient failures.

    Servers may answer with errors (e.g. 503), truncated content or stall: an
    invalid response must never be returned as data. Connection errors,
    timeouts, 429/5xx and responses rejected by validate (a function returning
    an error message or None) are retried with an exponential backoff, then
    EIO is raised. Other HTTP errors are mapped to an errno at once."""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(0.5 * 2 ** (attempt - 1), 8))
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as e:
            # connection errors and timeouts (including while reading the body)
            error = f"{type(e).__name__}: {e}"
        else:
            status = response.status_code
            if status in (401, 403):
                raise FuseOSError(EACCES)
            if status == 404:
                raise FuseOSError(ENOENT)
            if status == 429 or status >= 500:
                error = f"HTTP {status}"
            elif status >= 400:
                raise FuseOSError(EIO)
            else:
                error = validate(response) if validate else None
                if error is None:
                    return response
        if log:
            log_entry(
                log,
                "retry" if attempt < retries else "error",
                label=label,
                url=url,
                params=kwargs.get("params"),
                attempt=attempt + 1,
                error=error,
            )
    raise FuseOSError(EIO)


def expect_length(length):
    """validate function for request_with_retry checking the body size"""

    def validate(response):
        if len(response.content) != length:
            return f"expected {length} bytes, got {len(response.content)}"
        return None

    return validate


def add_retry_arguments(parser):
    parser.add_argument(
        "--timeout",
        required=False,
        type=float,
        default=10,
        help="Timeout of HTTP requests in seconds, a stalled request is retried (default: 10)",
    )
    parser.add_argument(
        "--retries",
        required=False,
        type=int,
        default=5,
        help="Number of retries of a failed HTTP request, with exponential backoff (default: 5)",
    )
