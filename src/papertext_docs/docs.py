from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional, NoReturn, Mapping, Any

from fastapi import APIRouter
from paperback import BaseDocs


class DocsImplemented(BaseDocs):
    requires_dir = True

    def __init__(self, cfg: SimpleNamespace, storage_dir: Path):
        pass