from typing import List, TypedDict, Optional

from py2neo import Node, Relationship


CypherQuery = str


class AnalyzerResult(TypedDict):
    nodes: List[Node]
    relationships: List[Relationship]
    commands_to_run: List[CypherQuery]
