import logging
from dataclasses import dataclass, field
import time
from typing import Any, cast, Dict, List, Tuple, Union

from py2neo import Node, Relationship
from pyexling import PyExLing
from titanis import Titanis

from papertext_docs.abc import Analyzer
from papertext_docs.types import AnalyzerResult


class TitanisWrapper(Analyzer):
    @dataclass
    class Span:
        left: int
        right: int

        def __contains__(
            self, other: Union["TitanisWrapper.Span", Tuple[int, int], int]
        ):
            if isinstance(other, TitanisWrapper.Span):
                return (self.left <= other.left) and (other.right <= self.right)
            elif isinstance(other, tuple):
                return (self.left <= other[0]) and (other[1] <= self.right)
            elif isinstance(other, int):
                return (self.left <= other) and (other <= self.right)

        def as_dict(self) -> Dict[str, int]:
            return {
                "left": self.left,
                "right": self.right,
            }

    def merge_dict_values(*args):
        assert len(args) > 1
        #     print(args)
        return {key: sum([a[key] for a in args], []) for key in args[0]}

    @dataclass
    class Text:
        text: str
        sentences: List["TitanisWrapper.Sentence"] = field(default_factory=list)

        def as_dict(self) -> Dict[str, Any]:
            return {
                "text": self.text,
                "sentences": [s.as_dict() for s in self.sentences],
            }

        def get_py2neo_ents(self) -> AnalyzerResult:
            text_node = Node("Text", text=self.text)

            sentence_ents: List[AnalyzerResult] = [
                s.get_py2neo_ents() for s in self.sentences
            ]

            return {
                "nodes": [text_node]
                + [node for s in sentence_ents for node in s["nodes"]],
                "relationships": [
                    Relationship(text_node, "contains", s["nodes"][0])
                    for s in sentence_ents
                ]
                + [rel for s in sentence_ents for rel in s["relationships"]],
                "commands_to_run": []
            }

    @dataclass
    class Sentence:
        text: str
        token_span: "TitanisWrapper.Span"
        words: List["TitanisWrapper.Word"] = field(default_factory=list)
        clauses: List["TitanisWrapper.Clause"] = field(default_factory=list)
        links: List["TitanisWrapper.Link"] = field(default_factory=list)

        def as_dict(self) -> Dict[str, Any]:
            return {
                "text": self.text,
                "token_span": self.token_span.as_dict(),
                "words": [word.as_dict() for word in self.words],
                "clauses": [clause.as_dict() for clause in self.clauses],
                "links": [link.as_dict() for link in self.links],
            }

        def get_py2neo_ents(self) -> Dict[str, List[Any]]:
            sentence_node = Node(
                "Sentence", text=self.text, token_span=self.token_span.as_dict()
            )

            word_nodes: List[Node] = [w.get_py2neo_node() for w in self.words]

            clause_ents: List[Tuple[Node, List[Relationship]]] = [
                ce.get_py2neo_ents(word_nodes) for ce in self.clauses
            ]

            return {
                "nodes": [sentence_node] + word_nodes + [ce[0] for ce in clause_ents],
                "relationships": (
                    [Relationship(sentence_node, "contains", w) for w in word_nodes]
                    + [Relationship(word_nodes[i], "next", word_nodes[i+1]) for i in range(len(word_nodes)-1)]
                    + [rel for ce in clause_ents for rel in ce[1]]
                    + [link.get_py2neo_relationship(word_nodes) for link in self.links]
                ),
            }

    @dataclass
    class Word:
        text: str
        span: "TitanisWrapper.Span"

        def as_dict(self) -> Dict[str, Any]:
            return {
                "text": self.text,
                "span": self.span.as_dict(),
            }

        def get_py2neo_node(self) -> Node:
            return Node("word", text=self.text, span=self.span.as_dict())

    @dataclass
    class Clause:
        text: str
        word_idxs: List[int]

        def as_dict(self) -> Dict[str, Any]:
            return {
                "text": self.text,
                "word_idxs": self.word_idxs,
            }

        def get_py2neo_ents(
            self, word_nodes: List[Node]
        ) -> Tuple[Node, List[Relationship]]:
            clause_node = Node("Clause", text=self.text)
            return clause_node, [
                Relationship(clause_node, "contains", word_nodes[wi])
                for wi in self.word_idxs
            ]

    @dataclass
    class Link:
        start: int
        end: int
        link_name: str = ""

        def as_dict(self) -> Dict[str, Any]:
            return {
                "start": self.start,
                "end": self.end,
                "link_name": self.link_name,
            }

        def get_py2neo_relationship(self, word_nodes: List[Node]) -> Relationship:
            return Relationship(
                word_nodes[self.start], self.link_name, word_nodes[self.end]
            )

    def __init__(self, host: str = ""):
        self.host = host

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.getLogger("paperback").level)
        self.logger.info("using titanis analyzer with `%s` host" % host)

        self.titanis = Titanis(
            host=self.host,  # use  if the containers are running on a remote server
            # psy_cues=True,                  # Рассчитывать психолингвистические/морфологические маркеры
            # psy_cues_normalization='words', # Условия нормализации для психолингвистических/морфологических маркеров
            # psy_dict=True,                  # Расчет словарных маркеров
            # psy_dict_normalization='words',
            # syntax=True,                    # Расчет синтаксических признаков
            # frustration_clf=True,
            # discourse=True,
            # discourse_long_text_only=True,
            # rosenzweig=True,
            # depression_clf=True,
            # elapsed_time=True,
            # udpipe=True,
            # mystem=True,
            # srl=True,
            rst=True,
        )

    def process(self, text: str, parent_node: Node) -> AnalyzerResult:
        titanis_result: Dict[Any, Any] = cast(Dict[Any, Any], self.titanis(text))

        sentences: List[TitanisWrapper.Sentence] = []
        for sentence_span, sentence_syntax in zip(
            titanis_result["Mystem"]["sentences"],
            titanis_result["UDPipe"]["syntax_dep_tree_ud"],
        ):
            sent_tokens = titanis_result["Mystem"]["tokens"][
                sentence_span.begin: sentence_span.end
            ]

            words: List[TitanisWrapper.Word] = [
                TitanisWrapper.Word(
                    text=token.text,
                    span=TitanisWrapper.Span(token.begin, token.end),
                )
                for token in sent_tokens
            ]

            clauses: List[TitanisWrapper.Clause] = []
            for du in titanis_result["RST"]["rst"]:
                # print(du)
                du_span = TitanisWrapper.Span(du.start, du.end)  # in chars

                if du.relation == "elementary":

                    acceptable_words: List[int] = []
                    for idx, word in enumerate(words):
                        if word.span in du_span:
                            acceptable_words.append(idx)
                    if acceptable_words:
                        clauses.append(
                            TitanisWrapper.Clause(
                                text=du.text,
                                word_idxs=acceptable_words,
                            )
                        )
                else:
                    raise ValueError(f"unknown relation {du.relation}")

            links: List[TitanisWrapper.Link] = [
                TitanisWrapper.Link(start=w.parent, end=idx, link_name=w.link_name)
                for idx, w in enumerate(sentence_syntax)
                if w.parent != -1
            ]

            sentences.append(
                TitanisWrapper.Sentence(
                    text=" ".join([t.text for t in sent_tokens]),
                    token_span=TitanisWrapper.Span(
                        sentence_span.begin, sentence_span.end
                    ),
                    words=words,
                    clauses=clauses,
                    links=links,
                )
            )
        text = TitanisWrapper.Text(
            text=titanis_result["UDPipe"]["text"],
            sentences=sentences,
        )
        get_py2neo_ents = text.get_py2neo_ents()
        # TODO: add connection to parent node
        return get_py2neo_ents


class PyExLingWrapper(Analyzer):
    def __init__(self, host: str, service: str):
        self.pyexling = PyExLing(host, service)

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.getLogger("paperback").level)
        self.logger.info("using pyexling analyzer with `%s` host and `%s` service" % (host, service))

    @staticmethod
    def cleanup_word_attrib(word_attrib: Dict[str, Any]) -> Dict[str, Any]:
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

    def process(self, text: str, parent_node: Node) -> AnalyzerResult:
        self.logger.debug("starting to analyzer text")
        start_time = time.time()
        xml_document = self.pyexling.txt2xml(text)
        xml_elapsed_time = time.time() - start_time
        self.logger.debug("analyzing took %s", xml_elapsed_time)

        # if parent_corp_id is not None:
        #     tx.create(py2neo.Relationship(parent_corp, "contains", doc_node))

        res: AnalyzerResult = {
            "nodes": [],
            "relationships": [],
        }

        text_node = Node("Text", text=text)
        res["nodes"].append(text_node)

        for sent in xml_document:
            sent_node = Node("sentence", **sent.attrib)
            res["nodes"].append(sent_node)
            sent_rel = Relationship(text_node, "contains", sent_node)
            res["relationships"].append(sent_rel)

            word_idx2word_node: Dict[int, Node] = {}

            for clause in [child for child in sent if child.tag == "clause"]:
                clause_node = Node("Clause", **clause.attrib)
                res["nodes"].append(clause_node)

                # new rel type, prev. - `clause_node`
                clause_rel = Relationship(sent_node, "contains", clause_node)
                res["relationships"].append(clause_rel)

                for word in clause:
                    attribs = self.cleanup_word_attrib(word.attrib)
                    word_node = Node(
                        "Word",
                        new=True,
                        **attribs,
                    )
                    res["nodes"].append(word_node)

                    word_rel = Relationship(clause_node, "contains", word_node)
                    res["relationships"].append(word_rel)

                    word_idx2word_node[attribs["idx"]] = word_node

            words = [
                v for (_, v) in sorted(word_idx2word_node.items(), key=lambda k, _: k)
            ]

            for i in range(len(words) - 1):
                res["relationships"].append(Relationship(words[i], "next", words[i + 1]))

            for role in [child for child in sent if child.tag == "role"]:
                role_node = Node("role")
                res["nodes"].append(role_node)
                role_rel = Relationship(
                    role_node,
                    "predicate",
                    word_idx2word_node[int(role.attrib["word_idx"])],
                )
                res["relationships"].append(role_rel)

                for arg in role:
                    arg_rel = Relationship(
                        role_node,
                        "argument",
                        word_idx2word_node[int(arg.attrib["word_idx"])],
                        role_id=int(arg.attrib["role_id"]),
                    )
                    res["relationships"].append(arg_rel)
        res["commands_to_run"] = [
            """
            MATCH (s:sentence)-[*2]->(c:word {new:true})
            WITH c,s
            MATCH (s:sentence)-[*2]->(p:word {new:true})
            WHERE c.syntax_parent_idx = p.idx
            CREATE (p)-[:syntax_link{link_name:c.syntax_link_name}]->(c)
            SET c.new = false, p.new = false
            """, "MATCH (w:word) REMOVE w.new"
        ]

        return res
