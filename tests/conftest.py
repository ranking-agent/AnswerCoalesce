import pytest


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
