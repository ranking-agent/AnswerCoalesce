import asyncio
import json
from pathlib import Path

import duckdb
import pytest
from scipy.stats import poisson

from src.graph_coalescence import duckdb_store
from src.graph_coalescence.build_duckdb import build_database, extract_prov
from src.graph_coalescence.graph_coalescer import coalesce_by_graph
from src.components import EnrichmentResult, EnrichmentType, QueryParams
from src.scoring import (
    pvalue_to_conductance,
    score_from_conductance,
    score_inference,
)
from src.single_node_coalescer import (
    multi_curie_query,
    run_inference_lookup,
)
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
            "feature",
            "membership",
            "category_count",
            "feature_stats",
        )
    }
    relation = connection.execute(
        "SELECT predicate_json, is_symmetric FROM relation"
    ).fetchone()

    assert counts == {
        "node": 2,
        "relation": 1,
        "fact": 1,
        "evidence": 1,
        "feature": 2,
        "membership": 2,
        "category_count": 15,
        "feature_stats": 25,
    }
    assert json.loads(relation[0]) == {
        "predicate": "biolink:related_to",
        "species_context_qualifier": "NCBITaxon:9606",
    }
    assert relation[1] is True
    assert connection.execute(
        """
        SELECT count(*)
        FROM membership
        JOIN node ON node.node_id = membership.member_node_id
        JOIN feature USING (feature_id)
        """
    ).fetchone()[0] == counts["membership"]
    connection.close()


def test_runtime_rejects_incompatible_schema(tmp_path, monkeypatch):
    database = tmp_path / "old-schema.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        """
        CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL);
        INSERT INTO metadata VALUES ('schema_version', '3');
        """
    )
    connection.close()

    monkeypatch.setenv("AC_DUCKDB_PATH", str(database))
    duckdb_store.close_connection()
    with pytest.raises(RuntimeError, match="schema version 3"):
        duckdb_store.connection()
    duckdb_store.close_connection()


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


def test_edgar_ranks_before_hydrating_inference_evidence(tmp_path, monkeypatch):
    nodes = [
        {"id": "PATHWAY:1", "category": ["biolink:Pathway"]},
        {"id": "PATHWAY:2", "category": ["biolink:Pathway"]},
        {"id": "GENE:A", "category": ["biolink:Gene"]},
        {"id": "GENE:B", "category": ["biolink:Gene"]},
        {"id": "GENE:C", "category": ["biolink:Gene"]},
    ]
    sources = [
        {
            "resource_id": "infores:primary",
            "resource_role": "primary_knowledge_source",
        }
    ]
    edges = [
        {
            "id": "edge-a-1",
            "subject": "GENE:A",
            "predicate": "biolink:causes",
            "object": "PATHWAY:1",
            "sources": sources,
        },
        {
            "id": "edge-a-2",
            "subject": "GENE:A",
            "predicate": "biolink:causes",
            "object": "PATHWAY:1",
            "sources": sources,
        },
        {
            "id": "edge-b-1",
            "subject": "GENE:B",
            "predicate": "biolink:causes",
            "object": "PATHWAY:1",
            "sources": sources,
        },
        {
            "id": "edge-b-2",
            "subject": "GENE:B",
            "predicate": "biolink:causes",
            "object": "PATHWAY:2",
            "sources": sources,
        },
        {
            "id": "edge-c-1",
            "subject": "GENE:C",
            "predicate": "biolink:causes",
            "object": "PATHWAY:2",
            "sources": sources,
        },
        {
            "id": "edge-c-2",
            "subject": "GENE:C",
            "predicate": "biolink:causes",
            "object": "PATHWAY:2",
            "species_context_qualifier": "NCBITaxon:9606",
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
    predicate = json.dumps({"predicate": "biolink:causes"}, separators=(",", ":"))
    enrichments = [
        EnrichmentResult(
            enrichment_type=EnrichmentType.GRAPH,
            enriched_id="PATHWAY:1",
            enriched_name="pathway one",
            enriched_types=("biolink:Pathway",),
            predicate=predicate,
            p_value=1e-10,
            linked_curies=frozenset(),
            counts=(0, 0, 0),
            is_source=False,
        ),
        EnrichmentResult(
            enrichment_type=EnrichmentType.GRAPH,
            enriched_id="PATHWAY:2",
            enriched_name="pathway two",
            enriched_types=("biolink:Pathway",),
            predicate=predicate,
            p_value=1e-6,
            linked_curies=frozenset(),
            counts=(0, 0, 0),
            is_source=False,
        ),
    ]
    params = QueryParams(
        curie="DISEASE:1",
        predicate_parts=json.dumps({"predicate": "biolink:related_to"}),
        is_source=False,
        input_qnode="disease",
        output_qnode="gene",
        output_semantic_type="biolink:Gene",
        input_semantic_type="biolink:Disease",
        qedge_id="e0",
    )

    summaries = duckdb_store.graph_inference_summaries(
        [
            {
                "rule_id": index,
                "enriched_curie": enrichment.enriched_id,
                "predicate_json": enrichment.predicate,
                "is_source": enrichment.is_source,
                "p_value": enrichment.p_value,
            }
            for index, enrichment in enumerate(enrichments)
        ],
        "biolink:Gene",
    )
    by_curie = {summary.inferred_curie: summary for summary in summaries}
    assert by_curie["GENE:A"].inference_count == 2
    assert by_curie["GENE:B"].inference_count == 2
    assert by_curie["GENE:C"].inference_count == 2
    assert by_curie["GENE:A"].total_conductance == pytest.approx(
        2 * pvalue_to_conductance([1e-10])[0]
    )
    assert by_curie["GENE:A"].first_seen_order < by_curie["GENE:B"].first_seen_order

    graph_inferred, property_inferred, metadata = asyncio.run(
        run_inference_lookup(
            enrichments,
            params,
            max_results=1,
        )
    )

    assert property_inferred == {}
    assert metadata == {
        "candidate_count": 3,
        "selected_count": 1,
        "graph_inferences_before_selection": 6,
        "property_inferences_before_selection": 0,
    }
    assert len(graph_inferred) == 1
    selected_enrichment, selected_lookup = graph_inferred[0]
    assert selected_enrichment.enriched_id == "PATHWAY:1"
    assert [link.link_id for link in selected_lookup.lookup_links] == [
        "GENE:A",
        "GENE:A",
    ]
    duckdb_store.close_connection()


def test_inference_conductance_preserves_elrond_score():
    p_values = [0.0, 1e-20, 1e-6]
    total_conductance = sum(pvalue_to_conductance(p_values))

    assert score_from_conductance(total_conductance) == pytest.approx(
        score_inference(p_values)
    )


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
