import os

import pytest

from src.graph_coalescence.build_duckdb import build_database
from src.graph_coalescence.duckdb_store import close_connection


@pytest.fixture(scope="session", autouse=True)
def duckdb_graph(tmp_path_factory):
    test_data = os.path.join(os.path.dirname(__file__), "GraphParseTestData")
    database = tmp_path_factory.mktemp("duckdb") / "answer-coalesce-test.duckdb"
    build_database(
        os.path.join(test_data, "nodes.jsonl"),
        os.path.join(test_data, "edges.jsonl"),
        database,
        blocklist=set(),
    )
    previous_path = os.environ.get("AC_DUCKDB_PATH")
    os.environ["AC_DUCKDB_PATH"] = str(database)
    close_connection()
    yield database
    close_connection()
    if previous_path is None:
        os.environ.pop("AC_DUCKDB_PATH", None)
    else:
        os.environ["AC_DUCKDB_PATH"] = previous_path


def generate_infer_query(input_type, output_type, input_curie, predicate,
                         input_is_subject=True, params=None, qualifier_constraints=None):
    edge = {
        "subject": "input" if input_is_subject else "output",
        "object": "output" if input_is_subject else "input",
        "predicates": [predicate],
        "knowledge_type": "inferred"
    }
    if qualifier_constraints:
        edge["qualifier_constraints"] = qualifier_constraints
    envelope = {
        "message": {
            "query_graph": {
                "nodes": {
                    "input": {"categories": [input_type], "ids": [input_curie]},
                    "output": {"categories": [output_type]}
                },
                "edges": {"edge_0": edge}
            }
        }
    }
    if params:
        envelope["parameters"] = params
    return envelope


def generate_mcq_query(input_type, output_type, member_ids, predicate,
                       input_is_subject=True, params=None, qualifier_constraints=None):
    edge = {
        "subject": "input" if input_is_subject else "output",
        "object": "output" if input_is_subject else "input",
        "predicates": [predicate]
    }
    if qualifier_constraints:
        edge["qualifier_constraints"] = qualifier_constraints
    envelope = {
        "message": {
            "query_graph": {
                "nodes": {
                    "input": {
                        "categories": [input_type],
                        "ids": ["uuid:1"],
                        "member_ids": member_ids,
                        "set_interpretation": "MANY"
                    },
                    "output": {"categories": [output_type]}
                },
                "edges": {"edge_0": edge}
            }
        }
    }
    if params:
        envelope["parameters"] = params
    return envelope
