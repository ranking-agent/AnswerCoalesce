from src.server import is_multi_curie_query, is_infer_query
from reasoner_pydantic import Response as PDResponse
import pytest

from tests.conftest import generate_infer_query, generate_mcq_query


@pytest.mark.asyncio
async def test_multi_curie_input():
    trapi = generate_mcq_query(
        "biolink:Gene", "biolink:Gene",
        ["NCBIGene:1018", "NCBIGene:1019"],
        "biolink:interacts_with", input_is_subject=False
    )
    assert PDResponse(**trapi)
    assert await is_multi_curie_query(trapi)
    assert not await is_infer_query(trapi)


@pytest.mark.asyncio
async def test_infer_input():
    trapi = generate_infer_query(
        "biolink:Disease", "biolink:ChemicalEntity",
        "MONDO:0004979", "biolink:treats",
        input_is_subject=False
    )
    assert PDResponse(**trapi)
    assert not await is_multi_curie_query(trapi)
    assert await is_infer_query(trapi)
