import threading
from collections import OrderedDict
from concurrent.futures import Future

from fusetea.utils.fusecompat import Operations, LoggingMixIn


class Readahead(LoggingMixIn, Operations):
    def __init__(self, plugin, page_size=2 * 1024 * 1024, cache_size=100):
        # caching parameters
        self.page_size = page_size
        self.cache_size = cache_size
        self.plugin = plugin

        # LRU cache of pages: (path, page offset, page size) -> data
        self._pages = OrderedDict()
        # pages being downloaded: (path, page offset, page size) -> Future
        # FUSE runs concurrent reads (e.g. kernel readahead) that often ask for
        # the same page, they wait for the first download instead of
        # downloading the page again
        self._pending = {}
        self._lock = threading.Lock()

    def fetch_page(self, path, read_size, page_offset, fh):
        key = (path, page_offset, read_size)

        with self._lock:
            if key in self._pages:
                self._pages.move_to_end(key)
                return self._pages[key]
            future = self._pending.get(key)
            downloader = future is None
            if downloader:
                future = self._pending[key] = Future()

        if not downloader:
            return future.result()

        try:
            data = self.plugin.read(path, read_size, page_offset, fh)
        except BaseException as e:
            with self._lock:
                del self._pending[key]
            future.set_exception(e)
            raise

        with self._lock:
            del self._pending[key]
            # do not keep incomplete pages, they will be downloaded again
            if len(data) == read_size:
                self._pages[key] = data
                while len(self._pages) > self.cache_size:
                    self._pages.popitem(last=False)
        future.set_result(data)
        return data

    def read(self, path, size, offset, fh):
        if size == 0:
            return b""

        # Safely fetch file size
        file_size = self.plugin.cache.get(path, {}).get("st_size", 0)

        # Standard EOF behavior
        if offset >= file_size:
            return b""

        start_page_idx = offset // self.page_size
        end_page_idx = (offset + size - 1) // self.page_size

        data = bytearray()

        for page_idx in range(start_page_idx, end_page_idx + 1):
            page_offset = page_idx * self.page_size

            # If we hit the end of the file, stop fetching pages
            if page_offset >= file_size:
                break

            read_size = min(self.page_size, file_size - page_offset)

            # Fetch the data and append it
            data += self.fetch_page(path, read_size, page_offset, fh)

        # Calculate exact slice within the concatenated pages
        relative_offset = offset % self.page_size
        return bytes(data[relative_offset : relative_offset + size])

    def readdir(self, path, fh):
        return self.plugin.readdir(path, fh)

    def getattr(self, path, fh=None):
        return self.plugin.getattr(path, fh)

    def open(self, path, flags):
        return self.plugin.open(path, flags)
