from pathlib import Path
from sys import path as sys_path

from .docs import DocsImplemented

src_path = Path(__file__) / ".." / ".."
src_path = src_path.resolve()

source_path = src_path / ".."
source_path = source_path.resolve()

pyexling_path = source_path / "pyexling" / "src"

sys_path.append(str(pyexling_path))

from pyexling import PyExLing  # noqa

__version__ = "0.1.0"
