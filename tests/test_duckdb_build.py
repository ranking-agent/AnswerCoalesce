import asyncio
import json
from pathlib import Path

import duckdb
import pytest
from scipy.stats import poisson

from src.components import EnrichmentResult, EnrichmentType, QueryParams
from src.graph_coalescence import build_duckdb, duckdb_store
from src.graph_coalescence.build_duckdb import (
    build_database,
    extract_prov,
    implied_relations,
)
from src.graph_coalescence.graph_coalescer import coalesce_by_graph
from src.scoring import (
    pvalue_to_conductance,
    score_from_conductance,
    score_inference,
)
from src.single_node_coalescer import (
    edge_from_component,
    lookup_single,
    multi_curie_query,
    run_inference_lookup,
)
from tests.conftest import generate_mcq_query


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _build_direction_test_database(tmp_path, monkeypatch):
    nodes = [
        {"id": "DRUG:1", "category": ["biolink:Drug"]},
        {"id": "DRUG:2", "category": ["biolink:Drug"]},
        {"id": "DISEASE:FORWARD", "category": ["biolink:Disease"]},
        {"id": "DISEASE:REVERSE", "category": ["biolink:Disease"]},
        {"id": "DISEASE:SYMMETRIC", "category": ["biolink:Disease"]},
    ]
    sources = [
        {
            "resource_id": "infores:test",
            "resource_role": "primary_knowledge_source",
        }
    ]
    edges = [
        {
            "id": "forward-1",
            "subject": "DRUG:1",
            "predicate": "biolink:treats",
            "object": "DISEASE:FORWARD",
            "sources": sources,
        },
        {
            "id": "forward-2",
            "subject": "DRUG:2",
            "predicate": "biolink:treats",
            "object": "DISEASE:FORWARD",
            "sources": sources,
        },
        {
            "id": "reverse-1",
            "subject": "DISEASE:REVERSE",
            "predicate": "biolink:treats",
            "object": "DRUG:1",
            "sources": sources,
        },
        {
            "id": "reverse-2",
            "subject": "DISEASE:REVERSE",
            "predicate": "biolink:treats",
            "object": "DRUG:2",
            "sources": sources,
        },
        {
            "id": "symmetric-1",
            "subject": "DISEASE:SYMMETRIC",
            "predicate": "biolink:related_to",
            "object": "DRUG:1",
            "sources": sources,
        },
        {
            "id": "symmetric-2",
            "subject": "DISEASE:SYMMETRIC",
            "predicate": "biolink:related_to",
            "object": "DRUG:2",
            "sources": sources,
        },
    ]
    node_file = tmp_path / "direction-nodes.jsonl"
    edge_file = tmp_path / "direction-edges.jsonl"
    database = tmp_path / "direction.duckdb"
    _write_jsonl(node_file, nodes)
    _write_jsonl(edge_file, edges)

    monkeypatch.setattr(build_duckdb, "_predicate_ancestors", lambda predicate: ())
    monkeypatch.setattr(
        build_duckdb,
        "is_symmetric",
        lambda predicate: predicate == "biolink:related_to",
    )
    build_database(node_file, edge_file, database, blocklist=set())
    monkeypatch.setenv("AC_DUCKDB_PATH", str(database))
    duckdb_store.close_connection()


def _mcq_output_ids(response):
    return {
        binding["id"]
        for result in response["message"].get("results", [])
        for binding in result["node_bindings"]["output"]
    }


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
            "relation_implication",
            "relation_hierarchy",
            "fact",
            "evidence",
            "feature",
            "feature_hierarchy",
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
        "relation_implication": 1,
        "relation_hierarchy": 0,
        "fact": 1,
        "evidence": 1,
        "feature": 2,
        "feature_hierarchy": 0,
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


def test_mcq_enforces_asymmetric_direction_and_allows_symmetric(
    tmp_path,
    monkeypatch,
):
    _build_direction_test_database(tmp_path, monkeypatch)

    forward_message = generate_mcq_query(
        "biolink:Drug",
        "biolink:Disease",
        ["DRUG:1", "DRUG:2"],
        "biolink:treats",
        input_is_subject=True,
        params={"pvalue_threshold": 1.0, "max_results": 10},
    )
    forward_response = asyncio.run(
        multi_curie_query(forward_message, forward_message["parameters"])
    )
    assert _mcq_output_ids(forward_response) == {"DISEASE:FORWARD"}

    reverse_message = generate_mcq_query(
        "biolink:Drug",
        "biolink:Disease",
        ["DRUG:1", "DRUG:2"],
        "biolink:treats",
        input_is_subject=False,
        params={"pvalue_threshold": 1.0, "max_results": 10},
    )
    reverse_response = asyncio.run(
        multi_curie_query(reverse_message, reverse_message["parameters"])
    )
    assert _mcq_output_ids(reverse_response) == {"DISEASE:REVERSE"}

    for input_is_subject in (True, False):
        symmetric_message = generate_mcq_query(
            "biolink:Drug",
            "biolink:Disease",
            ["DRUG:1", "DRUG:2"],
            "biolink:related_to",
            input_is_subject=input_is_subject,
            params={"pvalue_threshold": 1.0, "max_results": 10},
        )
        symmetric_response = asyncio.run(
            multi_curie_query(
                symmetric_message,
                symmetric_message["parameters"],
            )
        )
        assert _mcq_output_ids(symmetric_response) == {
            "DISEASE:SYMMETRIC"
        }

    duckdb_store.close_connection()


def test_edgar_initial_lookup_enforces_direction_and_allows_symmetric(
    tmp_path,
    monkeypatch,
):
    _build_direction_test_database(tmp_path, monkeypatch)
    treats = json.dumps({"predicate": "biolink:treats"}, sort_keys=True)
    related_to = json.dumps(
        {"predicate": "biolink:related_to"},
        sort_keys=True,
    )

    forward = lookup_single(
        "DRUG:1",
        treats,
        True,
        "biolink:Disease",
    )
    reverse = lookup_single(
        "DRUG:1",
        treats,
        False,
        "biolink:Disease",
    )
    symmetric_forward = lookup_single(
        "DRUG:1",
        related_to,
        True,
        "biolink:Disease",
    )
    symmetric_reverse = lookup_single(
        "DRUG:1",
        related_to,
        False,
        "biolink:Disease",
    )

    assert forward.link_ids == ["DISEASE:FORWARD"]
    assert reverse.link_ids == ["DISEASE:REVERSE"]
    assert symmetric_forward.link_ids == ["DISEASE:SYMMETRIC"]
    assert symmetric_reverse.link_ids == ["DISEASE:SYMMETRIC"]
    assert forward.lookup_links[0].link_edge.source == "DRUG:1"
    assert forward.lookup_links[0].link_edge.target == "DISEASE:FORWARD"
    assert reverse.lookup_links[0].link_edge.source == "DISEASE:REVERSE"
    assert reverse.lookup_links[0].link_edge.target == "DRUG:1"
    duckdb_store.close_connection()


def test_edgar_initial_lookup_requires_and_preserves_query_qualifiers(
    tmp_path,
    monkeypatch,
):
    nodes = [
        {"id": "GENE:1", "category": ["biolink:Gene"]},
        {"id": "CHEM:MATCH", "category": ["biolink:ChemicalEntity"]},
        {"id": "CHEM:UNQUALIFIED", "category": ["biolink:ChemicalEntity"]},
        {"id": "CHEM:WRONG_DIRECTION", "category": ["biolink:ChemicalEntity"]},
    ]
    sources = [
        {
            "resource_id": "infores:test",
            "resource_role": "primary_knowledge_source",
        }
    ]
    query_relation = {
        "predicate": "biolink:affects",
        "qualified_predicate": "biolink:causes",
        "object_aspect_qualifier": "activity_or_abundance",
        "object_direction_qualifier": "decreased",
    }
    matching_relation = {
        **query_relation,
        "anatomical_context_qualifier": ["UBERON:0000955", "UBERON:0002037"],
    }
    edges = [
        {
            "id": "matching",
            "subject": "CHEM:MATCH",
            "object": "GENE:1",
            **matching_relation,
            "sources": sources,
        },
        {
            "id": "unqualified",
            "subject": "CHEM:UNQUALIFIED",
            "predicate": "biolink:affects",
            "object": "GENE:1",
            "sources": sources,
        },
        {
            "id": "wrong-direction",
            "subject": "CHEM:WRONG_DIRECTION",
            "object": "GENE:1",
            **{
                **matching_relation,
                "object_direction_qualifier": "increased",
            },
            "sources": sources,
        },
    ]
    node_file = tmp_path / "qualified-nodes.jsonl"
    edge_file = tmp_path / "qualified-edges.jsonl"
    database = tmp_path / "qualified.duckdb"
    _write_jsonl(node_file, nodes)
    _write_jsonl(edge_file, edges)

    build_database(node_file, edge_file, database, blocklist=set())
    monkeypatch.setenv("AC_DUCKDB_PATH", str(database))
    duckdb_store.close_connection()

    predicate_parts = json.dumps(query_relation, sort_keys=True)
    lookup = lookup_single(
        "GENE:1",
        predicate_parts,
        False,
        "biolink:ChemicalEntity",
    )

    assert lookup.link_ids == ["CHEM:MATCH"]
    direct_edge = edge_from_component(lookup.lookup_links[0].link_edge)
    assert direct_edge["predicate"] == "biolink:affects"
    assert direct_edge["qualifiers"] == [
        {
            "qualifier_type_id": "biolink:anatomical_context_qualifier",
            "qualifier_value": "UBERON:0000955",
        },
        {
            "qualifier_type_id": "biolink:anatomical_context_qualifier",
            "qualifier_value": "UBERON:0002037",
        },
        {
            "qualifier_type_id": "biolink:object_aspect_qualifier",
            "qualifier_value": "activity_or_abundance",
        },
        {
            "qualifier_type_id": "biolink:object_direction_qualifier",
            "qualifier_value": "decreased",
        },
        {
            "qualifier_type_id": "biolink:qualified_predicate",
            "qualifier_value": "biolink:causes",
        },
    ]
    duckdb_store.close_connection()


def test_implied_relations_match_old_orion_expansion(monkeypatch):
    monkeypatch.setattr(
        build_duckdb,
        "_predicate_ancestors",
        lambda predicate: (
            "biolink:associated_with",
            "biolink:related_to",
        ),
    )
    monkeypatch.setattr(
        build_duckdb,
        "_qualifier_ancestors",
        lambda value, enum_name: {
            ("expression", build_duckdb.ASPECT_ENUM): (
                "expression",
                "activity_or_abundance",
            ),
            ("increased", build_duckdb.DIRECTION_ENUM): (
                "increased",
                "changed",
            ),
        }[(value, enum_name)],
    )

    concrete = {
        "predicate": "biolink:affects",
        "qualified_predicate": "biolink:causes",
        "object_aspect_qualifier": "expression",
        "object_direction_qualifier": "increased",
        "species_context_qualifier": "NCBITaxon:9606",
    }
    expanded = {
        json.dumps(relation, sort_keys=True)
        for relation in implied_relations(concrete)
    }

    expected = set()
    for aspect in ("expression", "activity_or_abundance"):
        for direction in (None, "increased", "changed"):
            relation = concrete.copy()
            relation["object_aspect_qualifier"] = aspect
            if direction is None:
                relation.pop("object_direction_qualifier")
            else:
                relation["object_direction_qualifier"] = direction
            expected.add(json.dumps(relation, sort_keys=True))
    expected.update(
        {
            json.dumps(
                {
                    "predicate": "biolink:affects",
                    "species_context_qualifier": "NCBITaxon:9606",
                },
                sort_keys=True,
            ),
            json.dumps(
                {
                    "predicate": "biolink:associated_with",
                    "species_context_qualifier": "NCBITaxon:9606",
                },
                sort_keys=True,
            ),
            json.dumps(
                {
                    "predicate": "biolink:related_to",
                    "species_context_qualifier": "NCBITaxon:9606",
                },
                sort_keys=True,
            ),
        }
    )

    assert expanded == expected


def test_implied_predicate_membership_uses_concrete_evidence(
    tmp_path,
    monkeypatch,
):
    nodes = [
        {
            "id": "GENE:1",
            "category": ["biolink:NamedThing", "biolink:Gene"],
        },
        {
            "id": "GENE:2",
            "category": ["biolink:NamedThing", "biolink:Gene"],
        },
        {
            "id": "GENE:3",
            "category": ["biolink:NamedThing", "biolink:Gene"],
        },
        {
            "id": "DISEASE:1",
            "category": ["biolink:NamedThing", "biolink:Disease"],
        },
    ]
    edges = [
        {
            "id": "causal-edge",
            "subject": "GENE:1",
            "predicate": "biolink:causes",
            "object": "DISEASE:1",
            "sources": [
                {
                    "resource_id": "infores:causal-source",
                    "resource_role": "primary_knowledge_source",
                }
            ],
        },
        {
            "id": "related-edge",
            "subject": "GENE:2",
            "predicate": "biolink:related_to",
            "object": "DISEASE:1",
            "sources": [
                {
                    "resource_id": "infores:related-source",
                    "resource_role": "primary_knowledge_source",
                }
            ],
        },
    ]
    node_file = tmp_path / "nodes.jsonl"
    edge_file = tmp_path / "edges.jsonl"
    database = tmp_path / "answer-coalesce.duckdb"
    _write_jsonl(node_file, nodes)
    _write_jsonl(edge_file, edges)

    monkeypatch.setattr(
        build_duckdb,
        "_predicate_ancestors",
        lambda predicate: (
            (
                "biolink:related_to_at_instance_level",
                "biolink:related_to",
            )
            if predicate == "biolink:causes"
            else ()
        ),
    )
    monkeypatch.setattr(
        build_duckdb,
        "is_symmetric",
        lambda predicate: predicate == "biolink:related_to",
    )
    build_database(node_file, edge_file, database, blocklist=set())

    database_connection = duckdb.connect(str(database), read_only=True)
    counts = {
        table: database_connection.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0]
        for table in (
            "relation",
            "relation_implication",
            "relation_hierarchy",
            "fact",
            "evidence",
            "feature_hierarchy",
        )
    }
    assert counts == {
        "relation": 2,
        "relation_implication": 3,
        "relation_hierarchy": 1,
        "fact": 2,
        "evidence": 2,
        "feature_hierarchy": 1,
    }
    database_connection.close()

    monkeypatch.setenv("AC_DUCKDB_PATH", str(database))
    duckdb_store.close_connection()
    candidates, total_node_count = duckdb_store.enrichment_candidates(
        ["GENE:1", "GENE:2"],
        "biolink:Gene",
        node_constraints=["biolink:Disease"],
        predicate_constraints=["biolink:related_to"],
        predicate_constraint_style="include",
    )

    assert total_node_count == 3
    assert len(candidates) == 1
    assert candidates[0].support_count == 2
    assert candidates[0].background_count == 2
    assert set(candidates[0].linked_curies) == {"GENE:1", "GENE:2"}

    relation_json = json.dumps(
        {"predicate": "biolink:related_to"},
        separators=(",", ":"),
    )
    provenance = duckdb_store.get_edge_provenance(
        [("GENE:1", relation_json, "DISEASE:1")]
    )
    assert provenance[("GENE:1", relation_json, "DISEASE:1")] == [
        [
            {
                "resource_id": "infores:causal-source",
                "resource_role": "primary_knowledge_source",
            }
        ]
    ]

    summaries = duckdb_store.graph_inference_summaries(
        [
            {
                "rule_id": 1,
                "enriched_curie": "DISEASE:1",
                "predicate_json": relation_json,
                "p_value": 0.01,
                "is_source": True,
            }
        ],
        "biolink:Gene",
    )
    assert {
        (summary.inferred_curie, summary.inference_count)
        for summary in summaries
    } == {
        ("GENE:1", 1),
        ("GENE:2", 1),
    }
    duckdb_store.close_connection()


def test_hierarchy_pruning_precedes_top_k(tmp_path, monkeypatch):
    nodes = [
        {
            "id": f"GENE:{index}",
            "category": ["biolink:NamedThing", "biolink:Gene"],
        }
        for index in range(1, 5)
    ] + [
        {
            "id": f"DISEASE:{index}",
            "category": ["biolink:NamedThing", "biolink:Disease"],
        }
        for index in range(1, 3)
    ]
    sources = [
        {
            "resource_id": "infores:primary",
            "resource_role": "primary_knowledge_source",
        }
    ]
    edges = [
        {
            "id": "cause-1",
            "subject": "GENE:1",
            "predicate": "biolink:causes",
            "object": "DISEASE:1",
            "sources": sources,
        },
        {
            "id": "cause-2",
            "subject": "GENE:2",
            "predicate": "biolink:causes",
            "object": "DISEASE:1",
            "sources": sources,
        },
        {
            "id": "related-1",
            "subject": "GENE:3",
            "predicate": "biolink:related_to",
            "object": "DISEASE:1",
            "sources": sources,
        },
        {
            "id": "treat-1",
            "subject": "GENE:1",
            "predicate": "biolink:treats",
            "object": "DISEASE:2",
            "sources": sources,
        },
        {
            "id": "treat-2",
            "subject": "GENE:3",
            "predicate": "biolink:treats",
            "object": "DISEASE:2",
            "sources": sources,
        },
    ]
    node_file = tmp_path / "nodes.jsonl"
    edge_file = tmp_path / "edges.jsonl"
    database = tmp_path / "answer-coalesce.duckdb"
    _write_jsonl(node_file, nodes)
    _write_jsonl(edge_file, edges)

    monkeypatch.setattr(
        build_duckdb,
        "_predicate_ancestors",
        lambda predicate: (
            ("biolink:related_to",)
            if predicate in {"biolink:causes", "biolink:treats"}
            else ()
        ),
    )
    monkeypatch.setattr(
        build_duckdb,
        "is_symmetric",
        lambda predicate: predicate == "biolink:related_to",
    )
    build_database(node_file, edge_file, database, blocklist=set())

    database_connection = duckdb.connect(str(database), read_only=True)
    assert database_connection.execute(
        "SELECT count(*) FROM relation_hierarchy"
    ).fetchone()[0] == 2
    assert database_connection.execute(
        "SELECT count(*) FROM feature_hierarchy"
    ).fetchone()[0] == 2
    database_connection.close()

    monkeypatch.setenv("AC_DUCKDB_PATH", str(database))
    duckdb_store.close_connection()
    candidates, _ = duckdb_store.enrichment_candidates(
        ["GENE:1", "GENE:2"],
        "biolink:Gene",
        node_constraints=["biolink:Disease"],
        filter_predicate_hierarchies=True,
        max_results=2,
    )

    assert [
        (
            candidate.neighbor_curie,
            json.loads(candidate.predicate_json)["predicate"],
        )
        for candidate in candidates
    ] == [
        ("DISEASE:1", "biolink:causes"),
        ("DISEASE:2", "biolink:treats"),
    ]

    candidates, _ = duckdb_store.enrichment_candidates(
        ["GENE:1", "GENE:2"],
        "biolink:Gene",
        node_constraints=["biolink:Disease"],
        filter_predicate_hierarchies=True,
        exclude_ids={"DISEASE:1"},
        max_results=1,
    )
    assert [
        (
            candidate.neighbor_curie,
            json.loads(candidate.predicate_json)["predicate"],
        )
        for candidate in candidates
    ] == [("DISEASE:2", "biolink:treats")]
    duckdb_store.close_connection()


def test_runtime_rejects_incompatible_schema(tmp_path, monkeypatch):
    database = tmp_path / "old-schema.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute(
        """
        CREATE TABLE metadata (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL);
        INSERT INTO metadata VALUES ('schema_version', '6');
        """
    )
    connection.close()

    monkeypatch.setenv("AC_DUCKDB_PATH", str(database))
    duckdb_store.close_connection()
    with pytest.raises(RuntimeError, match="schema version 6"):
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
