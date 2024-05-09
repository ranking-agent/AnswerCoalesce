import pytest
from src import single_node_coalescer as snc

import pytest
from src.trapi import get_mcq_components

from reasoner_pydantic import Response
@pytest.mark.asyncio
async def test_get_mcq_components():
    # Mocking the input message
    in_message = {
        "message": {
            "query_graph": {
                "nodes": {
                    "n1": {"set_interpretation": "MANY",
                           "member_ids": ["CURIE:1", "CURIE:2"],
                           "categories":["biolink:SmallMolecule"],
                           "ids": ["UUID:1"]},
                    "n2": {"categories": ["biolink:Gene"]}
                },
                "edges": {
                    "e1": {"subject": "n1",
                           "predicate": "biolink:affects",
                           "object": "n2",
                           "qualifiers_constraints": [
                               {"qualifier_set": [
                                   {"qualifier_type_id": "biolink:object_aspect_qualifier",
                                    "qualifier_value": "expression"}
                               ]
                            }
                           ]
                       }
                    }
                }
            }
    }
    # First, did we make a valid query_graph?
    response = Response(**in_message)
    # Expected output after parsing
    expected_output = {
        "group_node": {"curies": ["CURIE:1", "CURIE:2"], "qnode_id": "n1", "uuid": "UUID:1", "semantic_type": "biolink:SmallMolecule"},
        "enriched_node": {"qnode_id": "n2", "semantic_types": ["biolink:Gene"]},
        "edge": {"predicate": {"predicate": "biolink:affects", "biolink:object_aspect_qualifier": "expression"},
                "qedge_id": "e1", "group_is_subject": True}
    }

    # Call the function with the mocked data
    result = await get_mcq_components(in_message)

    # Assert that the function output is as expected
    assert result == expected_output

@pytest.mark.asyncio
async def test_create_or_find_member_of_edges_existing_edges():
    """In this test there is already one member_of edge (for id1) But not for id2"""
    message = {
        "message": {
            "query_graph": {
                "nodes": {
                    "qnode1": {
                        "ids": ["uuid:1234"],
                        "member_ids": ["id1", "id2"]
                    },
                    "qnode2": {
                        "categories": ["biolink:Gene"]
                    }
                },
                "edges": {
                    "edge1": {
                        "subject": "qnode1",
                        "object": "qnode2",
                        "predicate": "biolink:related_to"
                }
            }
        },
        "knowledge_graph": {
            "edges": {
                "edge1": {
                    "subject": "id1",
                    "object": "uuid:1234",
                    "predicate": "biolink:member_of"
                }
            }
        }
    }
    }
    result = await snc.create_or_find_member_of_edges(message, "qnode1")
    # assert that result contains keys for both id1 and id2
    assert "id1" in result
    assert "id2" in result
    # assert that the edge for id1 was not created
    assert result["id1"] == "edge1"
    # assert that the value of id2 in result is in the knowledge_graph edges
    assert result["id2"] in message["message"]["knowledge_graph"]["edges"]
    # assert that the edge for id2 has the correct subject, object, and predicate
    assert message["message"]["knowledge_graph"]["edges"][result["id2"]]["subject"] == "id2"
    assert message["message"]["knowledge_graph"]["edges"][result["id2"]]["object"] == "uuid:1234"
    assert message["message"]["knowledge_graph"]["edges"][result["id2"]]["predicate"] == "biolink:member_of"
