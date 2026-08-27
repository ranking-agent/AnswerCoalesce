import asyncio
import json
from pathlib import Path

import duckdb
import pytest
from scipy.stats import poisson

from src.graph_coalescence import duckdb_store
from src.graph_coalescence.build_duckdb import build_database, extract_prov
from src.graph_coalescence.graph_coalescer import coalesce_by_graph
from src.single_node_coalescer import multi_curie_query
from tests.conftest import generate_mcq_query


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_duckdb_builder_creates_normalized_graph(tmp_path):
    test_data = Path(__file__).parent / "GraphParseTestData"
    database = tmp_path / "answer-coalesce.duckdb"
    build_database(
        test_data / "nodes.jsonl",
        test_data / "edges.jsonl",
        database,
        blocklist=set(),
    )

    connection = duckdb.connect(str(database), read_only=True)
    counts = {
        table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in (
            "node",
            "relation",
            "fact",
            "evidence",
            "membership",
            "category_count",
            "feature_stats",
        )
    }
    relation = connection.execute(
        "SELECT predicate_json, is_symmetric FROM relation"
    ).fetchone()
    connection.close()

    assert counts == {
        "node": 2,
        "relation": 1,
        "fact": 1,
        "evidence": 1,
        "membership": 2,
        "category_count": 15,
        "feature_stats": 25,
    }
    assert json.loads(relation[0]) == {
        "predicate": "biolink:related_to",
        "species_context_qualifier": "NCBITaxon:9606",
    }
    assert relation[1] is True


def test_duplicate_evidence_does_not_inflate_enrichment(tmp_path, monkeypatch):
    nodes = [
        {"id": "GENE:1", "name": "one", "category": ["biolink:NamedThing", "biolink:Gene"]},
        {"id": "GENE:2", "name": "two", "category": ["biolink:NamedThing", "biolink:Gene"]},
        {"id": "GENE:3", "name": "three", "category": ["biolink:NamedThing", "biolink:Gene"]},
        {"id": "DISEASE:1", "name": "disease", "category": ["biolink:NamedThing", "biolink:Disease"]},
    ]
    sources = [
        {
            "resource_id": "infores:primary",
            "resource_role": "primary_knowledge_source",
        }
    ]
    edges = [
        {
            "id": "edge-1",
            "subject": "GENE:1",
            "predicate": "biolink:associated_with",
            "object": "DISEASE:1",
            "sources": sources,
        },
        {
            "id": "edge-2",
            "subject": "GENE:1",
            "predicate": "biolink:associated_with",
            "object": "DISEASE:1",
            "sources": [
                {
                    "resource_id": "infores:other-primary",
                    "resource_role": "primary_knowledge_source",
                }
            ],
        },
        {
            "id": "edge-3",
            "subject": "GENE:2",
            "predicate": "biolink:associated_with",
            "object": "DISEASE:1",
            "sources": sources,
        },
        {
            "id": "edge-4",
            "subject": "GENE:1",
            "predicate": "biolink:causes",
            "object": "DISEASE:1",
            "sources": sources,
        },
        {
            "id": "edge-5",
            "subject": "GENE:1",
            "predicate": "biolink:related_to",
            "object": "DISEASE:1",
            "sources": sources,
        },
        {
            "id": "edge-6",
            "subject": "GENE:2",
            "predicate": "biolink:related_to",
            "object": "DISEASE:1",
            "sources": sources,
        },
    ]
    node_file = tmp_path / "nodes.jsonl"
    edge_file = tmp_path / "edges.jsonl"
    database = tmp_path / "answer-coalesce.duckdb"
    _write_jsonl(node_file, nodes)
    _write_jsonl(edge_file, edges)
    build_database(node_file, edge_file, database, blocklist=set())

    monkeypatch.setenv("AC_DUCKDB_PATH", str(database))
    duckdb_store.close_connection()
    enrichments = asyncio.run(
        coalesce_by_graph(
            ["GENE:1", "GENE:2"],
            "biolink:Gene",
            node_constraints=["biolink:Disease"],
            predicate_constraints=[{"predicate": "biolink:associated_with"}],
            predicate_constraint_style="include",
        )
    )

    assert len(enrichments) == 1
    enrichment = enrichments[0]
    assert enrichment.counts == [2, 2, 3]
    assert enrichment.p_value == pytest.approx(poisson.sf(1, 4 / 3))
    assert len(enrichment.links) == 3
    primary_sources = [
        link.prov[0]["resource_id"] for link in enrichment.links
    ]
    assert primary_sources == [
        "infores:primary",
        "infores:other-primary",
        "infores:primary",
    ]

    message = generate_mcq_query(
        "biolink:Gene",
        "biolink:Disease",
        ["GENE:1", "GENE:2"],
        "biolink:associated_with",
        params={"pvalue_threshold": 1.0, "max_results": 10},
    )
    response = asyncio.run(multi_curie_query(message, message["parameters"]))
    source_edges = [
        edge
        for edge in response["message"]["knowledge_graph"]["edges"].values()
        if edge["predicate"] == "biolink:associated_with"
        and not edge["subject"].startswith("uuid:")
        and not edge["object"].startswith("uuid:")
    ]
    assert len(source_edges) == 3
    assert all(
        sum(
            source["resource_role"] == "primary_knowledge_source"
            for source in edge["sources"]
        ) == 1
        for edge in source_edges
    )

    related_without_hierarchy, _ = duckdb_store.enrichment_candidates(
        ["GENE:1", "GENE:2"],
        "biolink:Gene",
        node_constraints=["biolink:Disease"],
        predicate_constraints=["biolink:causes"],
        predicate_constraint_style="exclude",
    )
    related_with_hierarchy, _ = duckdb_store.enrichment_candidates(
        ["GENE:1", "GENE:2"],
        "biolink:Gene",
        node_constraints=["biolink:Disease"],
        predicate_constraints=["biolink:causes"],
        predicate_constraint_style="exclude",
        hierarchy_exclusion_pairs=[
            ("biolink:causes", "biolink:related_to"),
        ],
    )
    assert any(
        json.loads(candidate.predicate_json)["predicate"] == "biolink:related_to"
        for candidate in related_without_hierarchy
    )
    assert all(
        json.loads(candidate.predicate_json)["predicate"] != "biolink:related_to"
        for candidate in related_with_hierarchy
    )


def test_reciprocal_symmetric_facts_have_unique_membership(tmp_path):
    nodes = [
        {"id": "GENE:1", "category": ["biolink:Gene"]},
        {"id": "GENE:2", "category": ["biolink:Gene"]},
    ]
    sources = [
        {
            "resource_id": "infores:primary",
            "resource_role": "primary_knowledge_source",
        }
    ]
    edges = [
        {
            "id": "edge-1",
            "subject": "GENE:1",
            "predicate": "biolink:related_to",
            "object": "GENE:2",
            "sources": sources,
        },
        {
            "id": "edge-2",
            "subject": "GENE:2",
            "predicate": "biolink:related_to",
            "object": "GENE:1",
            "sources": sources,
        },
    ]
    node_file = tmp_path / "nodes.jsonl"
    edge_file = tmp_path / "edges.jsonl"
    database = tmp_path / "answer-coalesce.duckdb"
    _write_jsonl(node_file, nodes)
    _write_jsonl(edge_file, edges)
    build_database(node_file, edge_file, database, blocklist=set())

    connection = duckdb.connect(str(database), read_only=True)
    assert connection.execute("SELECT count(*) FROM fact").fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM evidence").fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM membership").fetchone()[0] == 2
    connection.close()


def test_robokop_provenance_is_preserved():
    edge = {
        "biolink:primary_knowledge_source": "infores:primary",
        "biolink:aggregator_knowledge_source": ["infores:aggregator"],
    }
    assert extract_prov(edge) == edge


def test_translator_provenance_is_preserved():
    sources = [
        {
            "id": "infores:primary",
            "category": ["biolink:RetrievalSource"],
            "resource_id": "infores:primary",
            "resource_role": "primary_knowledge_source",
            "source_record_urls": ["https://example.org/record/1"],
        },
        {
            "id": "infores:supporting",
            "category": ["biolink:RetrievalSource"],
            "resource_id": "infores:supporting",
            "resource_role": "supporting_data_source",
            "upstream_resource_ids": ["infores:primary"],
        },
    ]
    assert extract_prov(
        {
            "id": "edge-1",
            "subject": "SUBJECT:1",
            "predicate": "biolink:related_to",
            "object": "OBJECT:1",
            "sources": sources,
        }
    ) == sources


@pytest.mark.parametrize(
    "sources",
    [
        [],
        [{"resource_id": "infores:x", "resource_role": "aggregator_knowledge_source"}],
        [
            {"resource_id": "infores:one", "resource_role": "primary_knowledge_source"},
            {"resource_id": "infores:two", "resource_role": "primary_knowledge_source"},
        ],
    ],
)
def test_translator_provenance_requires_exactly_one_primary_source(sources):
    with pytest.raises(ValueError, match="exactly one primary_knowledge_source"):
        extract_prov(
            {
                "id": "invalid-edge",
                "subject": "SUBJECT:1",
                "predicate": "biolink:related_to",
                "object": "OBJECT:1",
                "sources": sources,
            }
        )


def test_translator_primary_source_requires_resource_id():
    with pytest.raises(ValueError, match="without a resource_id"):
        extract_prov(
            {
                "id": "invalid-edge",
                "subject": "SUBJECT:1",
                "predicate": "biolink:related_to",
                "object": "OBJECT:1",
                "sources": [{"resource_role": "primary_knowledge_source"}],
            }
        )
