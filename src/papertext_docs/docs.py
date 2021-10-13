from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from xml.dom import minidom
from xml.etree import ElementTree

import py2neo
from fastapi import APIRouter, HTTPException, status

from paperback.exceptions import PaperBackError
from paperback.exceptions.docs import CorpusDoesntExist, DocumentNameError
from paperback.abc import BaseAuth, BaseDocs
from paperback.abc.models import ReadMinimalCorp

from pyexling import PyExLing

from papertext_docs.tasks import add_document


class DocsImplemented(BaseDocs):
    requires_dir: bool = True
    requires_auth: bool = True
    DEFAULTS: Dict[str, Any] = {
        "processor": {
            "host": "",
            "service": "",
        },
        "db": {
            "scheme": "bolt",
            "username": "neo4j",
            "password": "password",
            "host": "localhost",
            "port": "7687",
        },
    }

    def __init__(
        self, cfg: SimpleNamespace, storage_dir: Path, auth_module: BaseAuth
    ):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.getLogger("paperback").level)
        self.logger.info("initializing papertext_docs module")

        self.logger.debug("using storage dir %s", storage_dir)
        self.logger.debug("using config %s", cfg)
        self.storage_dir: Path = storage_dir
        self.cfg: SimpleNamespace = cfg
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
            scheme=self.cfg.db.scheme,
            user=self.cfg.db.username,
            password=self.cfg.db.password,
            host=self.cfg.db.host,
            port=self.cfg.db.port,
        )
        self.logger.debug("connected to neo4j database")

        self.logger.debug("creating default corpus")
        self.root_corp = self.graph_db.nodes.match(
            "corp", corp_id="root"
        ).first()
        if self.root_corp is None:
            tx = self.graph_db.begin()
            self.root_corp = py2neo.Node(
                "corp", corp_id="root"
            )
            tx.create(
                self.root_corp
            )
            tx.commit()
            self.logger.debug("created default root corpus")
        else:
            self.logger.debug("using already existing root corpus")

        self.logger.debug("syncing with auth module")
        self.sync_modules_on_startup()
        self.logger.debug("synced with auth module")

    async def __async__init__(self):
        await self.sync_modules()
        self.set_constraints()

    def set_constraints(self):
        if len(self.graph_db.schema.get_uniqueness_constraints("org")) == 0:
            self.graph_db.schema.create_uniqueness_constraint("org", "org_id")
        if len(self.graph_db.schema.get_uniqueness_constraints("user")) == 0:
            self.graph_db.schema.create_uniqueness_constraint(
                "user", "user_id"
            )
        if len(self.graph_db.schema.get_uniqueness_constraints("corp")) == 0:
            self.graph_db.schema.create_uniqueness_constraint(
                "corp", "corp_id"
            )
        if len(self.graph_db.schema.get_uniqueness_constraints("doc")) == 0:
            self.graph_db.schema.create_uniqueness_constraint("doc", "doc_id")

    def sync_modules_on_startup(self):
        pass

    async def sync_modules(self):
        org_nodes: Dict[str, py2neo.Node] = {}
        user_nodes: Dict[str, py2neo.Node] = {}

        tx = self.graph_db.begin()
        self.logger.debug("orgs: %s", await self.auth_module.read_orgs())
        for org in await self.auth_module.read_orgs():
            # creating organisation
            org_node = tx.graph.nodes.match(
                "org",
                org_id=org["organisation_id"],
            ).first()
            if org_node is None:
                org_node = py2neo.Node(
                    "org",
                    org_id=org["organisation_id"],
                    org_name=org["organisation_name"],
                )
                tx.create(org_node)
            org_nodes[org["organisation_id"]] = org_node

        self.logger.debug("users: %s", await self.auth_module.read_users())
        for user in await self.auth_module.read_users():
            # creating user
            user_node = tx.graph.nodes.match(
                "user",
                user_id=user["user_id"],
            ).first()
            if user_node is None:
                user_node = py2neo.Node(
                    "user",
                    user_id=user["user_id"],
                    user_name=user["user_name"],
                    email=user["email"],
                    loa=user["level_of_access"],
                )
                tx.create(user_node)
            user_nodes[user["user_id"]] = user_node

            # connect org to user
            user2org_relation = tx.graph.relationships.match(
                nodes=[
                    org_nodes[user["member_of"]],
                    user_node,
                ]
            ).first()

            if user2org_relation is None:
                user2org_relation = py2neo.Relationship(
                    org_nodes[user["member_of"]],
                    "contains",
                    user_node,
                )
                tx.create(user2org_relation)

        tx.commit()

    @staticmethod
    def cleanup_word_attrib(word_attrib: dict[str, Any]) -> dict[str, Any]:
        res = dict(word_attrib)

        for int_field in [
            "idx",
            "dwInfo",
            "dwId",
            "ucType",
            "syntax_parent_idx",
            "begin_offset",
            "end_offset",
        ]:
            if int_field in res.keys():
                res[int_field] = int(res[int_field])

        for bool_field in ["bGeo"]:
            if bool_field in res.keys():
                res[bool_field] = bool(res[bool_field])

        return res

    async def create_doc(
        self,
        creator_id: str,
        creator_type: str,
        doc_id: str,
        text: str,
        private: bool = False,
        parent_corp_id: Optional[str] = None,
        name: Optional[str] = None,
        has_access: Optional[List[str]] = None,
        author: Optional[str] = None,
        created: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:

        # add_document(text)

        tx = self.graph_db.begin()

        docs_with_same_name = tx.graph.nodes.match(
            "document", corp_id=parent_corp_id
        ).first()

        if docs_with_same_name is not None:
            raise DocumentNameError

        if parent_corp_id is not None:
            parent_corp = tx.graph.nodes.match(
                "corp", corp_id=parent_corp_id
            ).first()
            if parent_corp is None:
                raise CorpusDoesntExist
        else:
            parent_corp = self.root_corp
            parent_corp_id = self.root_corp["corp_id"]

        start_time = time.time()
        xml_document = self.processor.txt2xml(text)
        xml_elapsed_time = time.time() - start_time
        self.logger.debug("analyzing took %s", xml_elapsed_time)
        # self.logger.debug(
        # "analyzed text: %s", minidom.parseString(ElementTree.tostring(xml, encoding="unicode")).toprettyxml(indent="\t")
        # )

        if creator_type == "user":
            author = tx.graph.nodes.match(
                "user", user_id=creator_id
            ).first()
            self.logger.debug("selected user: %s", author)

        doc_node = py2neo.Node(
            "document",
            doc_id=doc_id,
            parent_corp_id=parent_corp_id,
            text=text,
            private=private,
            name=name,
            author=author["user_id"],
            created=created,
            tags=tags,
        )
        tx.create(doc_node)

        tx.create(py2neo.Relationship(author, "created", doc_node))

        if parent_corp_id is not None:
            tx.create(py2neo.Relationship(parent_corp, "contains", doc_node))


        for sent in xml_document:
            sent_node = py2neo.Node("sentence", **sent.attrib)

            tx.create(sent_node)
            tx.create(py2neo.Relationship(doc_node, "contains", sent_node))

            word_idx2word_node: dict[int, ElementTree.Element] = {}
            clauses = [child for child in sent if child.tag == "clause"]
            for clause in clauses:
                clause_node = py2neo.Node("clause", **clause.attrib)

                tx.create(clause_node)
                tx.create(
                    py2neo.Relationship(sent_node, "clause_node", clause_node)
                )

                for word in clause:
                    word_node = py2neo.Node(
                        "word",
                        new=True,
                        **self.cleanup_word_attrib(word.attrib),
                    )

                    tx.create(word_node)
                    tx.create(
                        py2neo.Relationship(clause_node, "contains", word_node)
                    )

                    word_idx2word_node[int(word.attrib["idx"])] = word_node

            words = [
                v
                for (k, v) in sorted(
                    word_idx2word_node.items(), key=lambda el: el[0]
                )
            ]

            for i in range(len(words) - 1):
                tx.create(py2neo.Relationship(words[i], "next", words[i + 1]))

            roles = [child for child in sent if child.tag == "role"]
            for role in roles:
                role_node = py2neo.Node("role")
                tx.create(role_node)
                tx.create(
                    py2neo.Relationship(
                        role_node,
                        "predicate",
                        word_idx2word_node[int(role.attrib["word_idx"])],
                    )
                )

                for arg in role:
                    tx.create(
                        py2neo.Relationship(
                            role_node,
                            "argument",
                            word_idx2word_node[int(arg.attrib["word_idx"])],
                            role_id=int(arg.attrib["role_id"]),
                        )
                    )
        tx.run(
            """
            MATCH (s:sentence)-[*2]->(c:word {new:true})
            WITH c,s
            MATCH (s:sentence)-[*2]->(p:word {new:true})
            WHERE c.syntax_parent_idx = p.idx
            CREATE (p)-[:syntax_link{link_name:c.syntax_link_name}]->(c)
            SET c.new = false, p.new = false
            """
        )
        tx.run("MATCH (w:word) REMOVE w.new")
        tx.commit()

    async def read_docs(
        self,
        requester_id: str,
        contains: Optional[str] = None,
        author: Optional[str] = None,
        created_before: Optional[datetime] = None,
        created_after: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        self.logger.debug("reading documents")

        if contains is not None:
            raise PaperBackError(
                status_code=status.HTTP_409_CONFLICT,
                detail="option `contains` is currently unsupported"
            )
        elif author is not None:
            raise PaperBackError(
                status_code=status.HTTP_409_CONFLICT,
                detail="option `author` is currently unsupported"
            )
        elif created_before is not None:
            raise PaperBackError(
                status_code=status.HTTP_409_CONFLICT,
                detail="option `created_before` is currently unsupported"
            )
        elif created_after is not None:
            raise PaperBackError(
                status_code=status.HTTP_409_CONFLICT,
                detail="option `created_after` is currently unsupported"
            )
        elif tags is not None:
            raise PaperBackError(
                status_code=status.HTTP_409_CONFLICT,
                detail="option `tags` is currently unsupported"
            )
        # graph = init_graph(config)
        # if only_inactive:
        #     query = "MATCH (d:document {inactive : false}) RETURN id(d) as doc_id, d.name as name"
        # else:
        #     query = "MATCH (d:document {inactive : true}) RETURN id(d) as doc_id, d.name as name"
        #
        # result = graph.run(query).data()
        #
        # return {'documents': result}

        tx = self.graph_db.begin()
        docs: list[py2neo.Node] = tx.graph.nodes.match("document")
        self.logger.debug("read documents: %s", list(docs))
        self.logger.info("read documents")
        return [dict(d) for d in docs]

    async def read_doc(self, doc_id: str) -> Dict[str, Any]:
        pass

    async def update_doc(
        self,
        doc_id: str,
        owner_id: Optional[str] = None,
        owner_type: Optional[str] = None,
        parent_corp_id: Optional[str] = None,
        text: Optional[str] = None,
        private: Optional[bool] = False,
        name: Optional[str] = None,
        has_access: Optional[List[str]] = None,
        author: Optional[str] = None,
        created: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        pass

    async def delete_doc(self, doc_id: str):
        pass

    async def create_corp(
        self,
        issuer_id: str,
        issuer_type: str,
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

        corp_with_same_id = tx.graph.nodes.match(
            "corp", corp_id=corp_id
        ).first()
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
                "corp", corp_id=corp_id, name=name, private=private
            )
            tx.create(corpus)

        self.logger.debug("created corpus %s", corpus)
        if parent_corp_id is not None:
            parent_corpus = tx.graph.nodes.match(
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

            parent2child_relation = tx.graph.relationships.match(
                nodes=[
                    corpus,
                    parent_corpus,
                ]
            ).first()

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
        if issuer_type == "user":
            issuer_node = tx.graph.nodes.match(
                "user", user_id=issuer_id
            ).first()
        elif issuer_type == "org":
            issuer_node = tx.graph.nodes.match("org", org_id=issuer_id).first()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "end": f"issuer with type {issuer_type} not recognized",
                    "rus": f"создатель с типом {issuer_type} не распознан",
                },
            )

        issuer2corpus = py2neo.Relationship(
            issuer_node,
            "created",
            corpus,
        )
        tx.create(issuer2corpus)

        if len(to_include) != 0:
            # TODO: implement
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "end": f"to_include is not supported yet",
                    "rus": f"to_include ещё не поддерживается",
                },
            )

        tx.commit()
        return corpus

    async def read_corps(
        self,
        requester_id: str,
        parent_corp_id: Optional[str] = None,
        private: bool = False,
        has_access: Optional[List[str]] = None,
    ):
        return [
            ReadMinimalCorp(corp_id="corp_1", name="Первый корпус"),
            ReadMinimalCorp(
                corp_id="pushkin_1", name="Корпус сочинений Пушкина"
            ),
        ]

    async def read_corp(self, corp_id: str) -> Dict[str, Any]:
        pass

    async def update_corp(
        self,
        corp_id: str,
        name: Optional[str] = None,
        parent_corp_id: Optional[str] = None,
        private: bool = False,
        has_access: Optional[List[str]] = None,
        to_include: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        pass

    async def delete_corp(self, corp_id: str):
        pass
