import pytest
from src import single_node_coalescer as snc

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
