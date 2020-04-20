from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping, NoReturn, Optional

from fastapi import APIRouter

from paperback import BaseDocs


class DocsImplemented(BaseDocs):
    requires_dir = False
    DEFAULTS = {}

    def __init__(self, cfg: SimpleNamespace, storage_dir: Path):
        pass
