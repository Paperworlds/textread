from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("textread")
except PackageNotFoundError:
    __version__ = "unknown"
