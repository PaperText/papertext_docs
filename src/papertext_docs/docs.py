from abc import ABC
from types import SimpleNamespace
from typing import Any, Dict, List, Callable, ClassVar, Optional
from datetime import datetime
from pathlib import Path
import logging
from xml.etree import ElementTree
import py2neo

from fastapi import APIRouter, HTTPException, status
from pyexling import PyExLing

from paperback.abc import BaseDocs, BaseAuth
from paperback.abc.models import UserInfo


class DocsImplemented(BaseDocs):
    requires_dir: bool = True
    requires_auth: bool = True
    DEFAULTS: Dict[str, Any] = {
        "processor": {
            "host": "",
            "service": ""
        },
        "graph_db": {
            "host": "localhost",
            "port": "7687",
            "scheme": "bolt",
            "auth": {
                "user": "neo4j",
                "password": "",
            }
        }
    }

    def __init__(self, cfg: SimpleNamespace, storage_dir: Path, auth_module: BaseAuth):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.getLogger("paperback").level)
        self.logger.info("initializing papertext_docs module")

        self.cfg: SimpleNamespace = cfg
        self.storage_dir: Path = storage_dir
        # TODO: add check for configuration,
        #  i.e. that hash.algo lib and token.curve lib are present
        self.auth_module = auth_module

        self.docs_backup_folder = self.storage_dir / "docs.bak"
        self.docs_backup_folder.mkdir(parents=True, exist_ok=True)

        self.logger.debug("connecting to pyexling")
        self.processor = PyExLing(cfg.processor.host, cfg.processor.service)
        # TODO: add check that connection is working
        #   i.e. try to convert string
        self.logger.debug("connected to pyexling")

        self.logger.debug("connecting to neo4j database")
        self.graph_db = py2neo.Graph(
            host=self.cfg.graph_db.host,
            port=self.cfg.graph_db.port,
            scheme=self.cfg.graph_db.scheme,
            user=self.cfg.graph_db.auth.user,
            password=self.cfg.graph_db.auth.password,
        )
        self.logger.debug("connected to neo4j database")

        self.logger.debug("syncing to auth module")
        self.sync_modules()
        self.logger.debug("synced to auth module")

    def sync_modules(self):
        if len(self.graph_db.schema.get_uniqueness_constraints("org")) == 0:
            self.graph_db.schema.create_uniqueness_constraint("org", "org_id")
        if len(self.graph_db.schema.get_uniqueness_constraints("user")) == 0:
            self.graph_db.schema.create_uniqueness_constraint("user", "user_id")
        if len(self.graph_db.schema.get_uniqueness_constraints("corp")) == 0:
            self.graph_db.schema.create_uniqueness_constraint("corp", "corp_id")
        if len(self.graph_db.schema.get_uniqueness_constraints("doc")) == 0:
            self.graph_db.schema.create_uniqueness_constraint("doc", "doc_id")

    async def create_doc(
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
        xml = self.processor.txt2xml(text)

    async def read_docs(
            self,
            contains: Optional[str] = None,
            author: Optional[str] = None,
            created_before: Optional[datetime] = None,
            created_after: Optional[datetime] = None,
            tags: Optional[List[str]] = None
    ):
        pass

    async def create_corp(
        self,
        issuer: UserInfo,
        corp_id: str,
        name: Optional[str] = None,
        parent_corp_id: Optional[str] = None,
        private: bool = False,
        has_access: Optional[List[str]] = None,
        to_include=None,
    ) -> Dict[str, Any]:
        if to_include is None:
            to_include = []

        tx = self.graph_db.begin()
        corp_with_same_id = self.graph_db.nodes.match("corp", corp_id=corp_id).first()
        if corp_with_same_id is not None:
            tx.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "end": f"corpus with id {corp_id} already exists",
                    "rus": f"корпус с id {corp_id} уже существует",
                },
            )
        else:
            corpus = py2neo.Node(
                "corp",
                corp_id=corp_id,
                name=name,
                private=private
            )
            tx.create(corpus)

        self.logger.debug("created corpus %s", corpus)
        if parent_corp_id is not None:
            parent_corpus = self.graph_db.nodes.match(
                "corp",
                corp_id=parent_corp_id,
            ).first()
            if parent_corpus is None:
                tx.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "end": f"parent corpus with id {parent_corp_id} doesn't exists",
                        "rus": f"родительский корпус с id {parent_corp_id} не существует",
                    },
                )

            parent2child_relation = self.graph_db.relationships.match(nodes=[
                corpus,
                parent_corpus,
            ]).first()

            if parent2child_relation is not None:
                tx.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "end": f"connection between parent corpus with id {parent_corp_id} and corpus with id {corp_id} "
                               "already exists",
                        "rus": f"связь между родительским корпусов с id {parent_corp_id} и корпусов с id {corp_id} "
                               "уже существует",
                    },
                )
            else:
                self.logger.debug("parent corpus %s", parent_corpus)
                parent2child = py2neo.Relationship(
                    parent_corpus,
                    "contains",
                    corpus,
                )
                tx.create(parent2child)
                self.logger.debug(f"{parent2child=}")

        tx.commit()
        return corpus

    async def read_corps(self, corp_id: str, name: Optional[str] = None, parent_corp_id: Optional[str] = None,
                         private: bool = False, has_access: Optional[List[str]] = None, to_include=None):
        pass
