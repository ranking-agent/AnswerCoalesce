import pytest
from src import single_node_coalescer as snc
from src.components import  MCQDefinition
from src.components import Enrichment
from src.single_node_coalescer import create_mcq_trapi_response

import pytest

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

    # Call the function with the mocked data
    mcqdef = MCQDefinition(in_message)

    # Assert that the function output is as expected
    # Group Node
    assert mcqdef.group_node.qnode_id == "n1"
    assert mcqdef.group_node.uuid == "UUID:1"
    assert mcqdef.group_node.curies == ["CURIE:1", "CURIE:2"]
    assert mcqdef.group_node.semantic_type == "biolink:SmallMolecule"
    # New (Enriched) Node
    assert mcqdef.enriched_node.qnode_id == "n2"
    assert mcqdef.enriched_node.semantic_types == ["biolink:Gene"]
    # Edge
    assert mcqdef.edge.qedge_id == "e1"
    assert mcqdef.edge.predicate_only == "biolink:affects"
    assert mcqdef.edge.qualifiers == [{"qualifier_type_id": "biolink:object_aspect_qualifier",
                                       "qualifier_value": "expression"}]
    assert mcqdef.edge.predicate == {"predicate": "biolink:affects", "biolink:object_aspect_qualifier": "expression"}
    assert mcqdef.edge.group_is_subject == True

@pytest.mark.asyncio
async def test_create_or_find_member_of_edges_existing_edges():
    """In this test there is already one member_of edge (for id1) But not for id2"""
    message = {
        "message": {
            "query_graph": {
                "nodes": {
                    "qnode1": {
                        "ids": ["uuid:1234"],
                        "member_ids": ["id1", "id2"],
                        "categories": ["biolink:SmallMolecule"],
                        "set_interpretation": "MANY"
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
                    "predicate": "biolink:member_of",
                    "attributes": [],
                    "sources": []
                }
            }
        }
    }
    }
    mcqdef = MCQDefinition(message)
    result = await snc.create_or_find_member_of_edges_and_nodes(message, mcqdef)
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
    check = Response(**message)

@pytest.mark.asyncio
async def test_full_trapi_generation():
    """In this test there is already one member_of edge (for id1) But not for id2"""
    message = {
        "message": {
            "query_graph": {
                "nodes": {
                    "qnode1": {
                        "ids": ["uuid:1234"],
                        "member_ids": ["id1", "id2"],
                        "categories": ["biolink:SmallMolecule"],
                        "set_interpretation": "MANY"
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
                        "predicate": "biolink:member_of",
                        "attributes": [],
                        "sources": []
                    }
                }
            }
        }
    }
    mcqdef = MCQDefinition(message)
    enrichment = Enrichment(1e-10, "curie:newnode", '{"predicate": "biolink:related_to"}', True,
   100, 10, 1000, ["id1"], "biolink:Gene")
    prov = {'curie:newnode {"predicate": "biolink:related_to"} id1': [{'resource_id': 'infores:whatever', 'resource_role': 'primary_knowledge_source'}]}
    enrichment.add_provenance(prov)
    new_trapi = await create_mcq_trapi_response(message, [enrichment], mcqdef)
    check = Response(**new_trapi)