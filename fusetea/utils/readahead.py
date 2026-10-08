from functools import lru_cache
from fusetea.utils.fusecompat import Operations, LoggingMixIn


class Readahead(LoggingMixIn, Operations):
    def __init__(self, plugin, page_size=2 * 1024 * 1024, cache_size=100):
        # caching parameters
        self.page_size = page_size
        self.cache_size = cache_size
        self.plugin = plugin

        # Cache the bound method
        self.cached_read_function = lru_cache(maxsize=self.cache_size)(plugin.read)

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
            data += self.cached_read_function(path, read_size, page_offset, fh)

        # Calculate exact slice within the concatenated pages
        relative_offset = offset % self.page_size
        return bytes(data[relative_offset : relative_offset + size])

    def readdir(self, path, fh):
        return self.plugin.readdir(path, fh)

    def getattr(self, path, fh=None):
        return self.plugin.getattr(path, fh)

    def open(self, path, flags):
        return self.plugin.open(path, flags)
