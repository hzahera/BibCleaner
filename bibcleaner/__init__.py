from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bib-cleaner-tool")
except PackageNotFoundError:  # running from source without an install
    __version__ = "0.0.0+dev"

from .bibcleaner import process_bibliography, process_bibliography_content

__all__ = ["__version__", "process_bibliography", "process_bibliography_content"]
