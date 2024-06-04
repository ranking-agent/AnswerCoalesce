from src.server import is_multi_curie_query, is_infer_query
from reasoner_pydantic import Response as PDResponse
import pytest


@pytest.mark.asyncio
async def test_multi_curie_input():
    """Given a valid multi-curie query, make sure that server.is_multi_curie_query returns True,
    and is_infer_query returns False."""
    trapi = {
        "message": {
            "query_graph": {
                "nodes": {
                    "n0": {
                        "categories": ["biolink:Gene"],
                    },
                    "n1": {
                        "categories": ["biolink:Gene"],
                        "ids": ["uuid:1234"],
                        "member_ids": ["NCBIGene:1018", "NCBIGene:1019"],
                        "set_interpretation": "MANY"
                    }
                },
                "edges": {
                    "e0": {
                        "subject": "n0",
                        "object": "n1",
                        "predicate": "biolink:interacts_with"
                    }
                }
            }
        }
    }
    #First make sure that the test case is valid trapi
    assert PDResponse(**trapi)
    #Now check our ability to discern what kind of query we have
    assert await is_multi_curie_query(trapi)
    assert not await is_infer_query(trapi)


@pytest.mark.asyncio
async def test_infer_input():
    """Given a valid EDGAR query, make sure that server.is_multi_curie_query returns FALSe,
    and is_infer_query returns TRUE."""
    trapi = {
        "message": {
            "query_graph": {
                "nodes": {
                    "n0": {
                        "categories": ["biolink:ChemicalEntity"],
                    },
                    "n1": {
                        "categories": ["biolink:Disease"],
                        "ids": ["MONDO:0004979"],
                    }
                },
                "edges": {
                    "e0": {
                        "subject": "n0",
                        "object": "n1",
                        "predicate": "biolink:treats",
                        "knowledge_type": "inferred"
                    }
                }
            }
        }
    }
    #First make sure that the test case is valid trapi
    assert PDResponse(**trapi)
    #Now check our ability to discern what kind of query we have
    assert not await is_multi_curie_query(trapi)
    assert await is_infer_query(trapi)