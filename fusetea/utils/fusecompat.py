# Seen @ https://packages.debian.org/trixie/python3-fusepy
# Due to a name clash with the existing API-incompatible python-fuse package, the importable module name for fusepy in Debian is 'fusepy' instead of upstream's 'fuse'.
# This is a hack to support pipx/uv installations and .deb ones
try:
    from fusepy import FUSE, Operations, LoggingMixIn
except ImportError:
    from fuse import FUSE, Operations, LoggingMixIn

__all__ = ["FUSE", "Operations", "LoggingMixIn"]
