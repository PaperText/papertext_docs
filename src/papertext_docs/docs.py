from types import SimpleNamespace
from typing import Any, Mapping, Callable, NoReturn, Optional
from pathlib import Path

from fastapi import APIRouter

from paperback.abc import BaseDocs


class DocsImplemented(BaseDocs):
    requires_dir = False
    DEFAULTS = {}

    def __init__(self, cfg: SimpleNamespace, storage_dir: Path):
        pass
