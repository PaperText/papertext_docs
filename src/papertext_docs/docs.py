from abc import ABC
from types import SimpleNamespace
from typing import Any, Dict, List, Callable, ClassVar, Optional
from datetime import datetime
from pathlib import Path
import logging
from xml.etree import ElementTree

from fastapi import APIRouter
from pyexling import PyExLing

from paperback.abc import BaseDocs


class DocsImplemented(BaseDocs):
    requires_dir: bool = True
    DEFAULTS: Dict[str, Any] = {
        "processor": {
            "host": "",
            "service": ""
        }
    }

    def __init__(self, cfg: SimpleNamespace, storage_dir: Path):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.getLogger("paperback").level)
        self.logger.info("initializing papertext_docs module")

        self.cfg: SimpleNamespace = cfg
        self.storage_dir: Path = storage_dir
        # TODO: add check for configuration,
        #  i.e. that hash.algo lib and token.curve lib are present

        self.docs_backup_folder = self.storage_dir / "docs.bak"
        self.docs_backup_folder.mkdir(parents=True, exist_ok=True)

        self.processor = PyExLing(cfg.processor.host, cfg.processor.service)
        # TODO: add check that connection is working
        #   i.e. try to convert string

    async def create_docs(
            self,
            doc_id: str,
            parent_corp_id: str,
            text: str,
            private: bool = False,
            name: Optional[str] = None,
            has_access: Optional[List[str]] = None,
            author: Optional[str] = None,
            created: Optional[datetime] = None,
            tags: Optional[List[str]] = None,
    ):
        print(self.processor.process("Привет, мир"))
