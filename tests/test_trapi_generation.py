import pytest
import copy
from src import single_node_coalescer as snc
from src.components import  MCQDefinition
from src.components import Enrichment
from src.single_node_coalescer import create_mcq_trapi_response
from src.trapi import create_knowledge_graph_edge, add_member_of_klat, EGARTRAPIBuilder, prune_message
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
                           "predicates": ["biolink:affects"],
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
                        "predicates": ["biolink:related_to"]
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
                        "predicates": ["biolink:related_to"]
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
   100, 10, 1000, ["id1"], ["biolink:Gene"])
    prov = {'curie:newnode {"predicate": "biolink:related_to"} id1': [{'resource_id': 'infores:whatever', 'resource_role': 'primary_knowledge_source'}]}
    enrichment.add_provenance(prov)
    new_trapi = await create_mcq_trapi_response(message, [enrichment], mcqdef)
    check = Response(**new_trapi)


def test_create_kge():
    """This wasn't working originally because in a rookie mistake create_knowledge_graph_edge was
    using [] as a default value for atttributes, which is mutable.  As a reminder: mutable default values
    "remember" their state between calls!!!!"""
    new_edge = create_knowledge_graph_edge("curie:source", "curie:target", "biolink:related_to")
    assert len(new_edge["attributes"]) == 0
    new_edge = create_knowledge_graph_edge("curie:source2", "curie:target2", "biolink:related_to")
    assert len(new_edge["attributes"]) == 0

    new_edge = create_knowledge_graph_edge("curie:source", "curie:target", "biolink:related_to")
    assert len(new_edge["attributes"]) == 0
    add_member_of_klat(new_edge)
    assert len(new_edge["attributes"]) == 2
    new_edge = create_knowledge_graph_edge("curie:source2", "curie:target2", "biolink:related_to")
    assert len(new_edge["attributes"]) == 0
    add_member_of_klat(new_edge)
    assert len(new_edge["attributes"]) == 2


def create_edgar_message():
    """
    Create EDGAR message with proper edge naming conventions.
    Keep Result 1 (score 0.869), prune Result 2 (score 0.450).
    """
    return {
        "message": {
            "query_graph": {
                "nodes": {
                    "disease": {"ids": ["MONDO:0004975"]},
                    "chemical": {"categories": ["biolink:ChemicalEntity"]}
                },
                "edges": {
                    "e00": {"subject": "chemical", "object": "disease"}
                }
            },
            "knowledge_graph": {
                "nodes": {
                    # Shared node
                    "MONDO:0004975": {"name": "Alzheimer disease", "categories": ["biolink:Disease"]},

                    # Result 1 nodes (KEEP)
                    "CHEBI:6123": {"name": "Levodopa", "categories": ["biolink:ChemicalEntity"]},
                    "CHEBI_ROLE_neurotransmitter_agent": {"name": "neurotransmitter agent",
                                                          "categories": ["biolink:ChemicalRole"]},
                    "uuid:1": {"name": "Neurotransmitter Set", "categories": ["biolink:ChemicalEntity"],
                               "is_set": True},
                    "CHEBI:8888": {"name": "Member1", "categories": ["biolink:ChemicalEntity"]},
                    "CHEBI:8707": {"name": "Member2", "categories": ["biolink:ChemicalEntity"]},

                    # Result 2 nodes (PRUNE)
                    "CHEBI:9999": {"name": "Drug2", "categories": ["biolink:ChemicalEntity"]},
                    "PATHWAY:123": {"name": "Pathway", "categories": ["biolink:Pathway"]},
                    "uuid:2": {"name": "Pathway Set", "categories": ["biolink:Pathway"], "is_set": True},
                },
                "edges": {
                    # ===== RESULT 1 (KEEP) =====

                    # Main inferred edge
                    "CHEBI:6123_Inferred_to_biolink:treats_MONDO:0004975": {
                        "subject": "CHEBI:6123",
                        "object": "MONDO:0004975",
                        "predicate": "biolink:treats",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": [
                            {"attribute_type_id": "biolink:support_graphs", "value": "n_Inferred_SG:_CHEBI:6123_to_MONDO:0004975"}
                        ]
                    },

                    # Main SG edges
                    "CHEBI:6123_biolink:has_chemical_role_CHEBI_ROLE_neurotransmitter_agent": {
                        "subject": "CHEBI:6123",
                        "object": "CHEBI_ROLE_neurotransmitter_agent",
                        "predicate": "biolink:has_chemical_role",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": []
                    },
                    "e_CHEBI_ROLE_neurotransmitter_agent_biolink:similar_to_uuid:1": {
                        "subject": "CHEBI_ROLE_neurotransmitter_agent",
                        "object": "uuid:1",
                        "predicate": "biolink:similar_to",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": [
                            {"attribute_type_id": "biolink:support_graphs",
                             "value": ["SG:_CHEBI:8888_lookup", "SG:_CHEBI:8707_lookup"]}
                        ]
                    },
                    "uuid:1_biolink:treats_MONDO:0004975": {
                        "subject": "uuid:1",
                        "object": "MONDO:0004975",
                        "predicate": "biolink:treats",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": []
                    },

                    # Nested SG edges
                    "CHEBI:8888_biolink:member_of_uuid:1": {
                        "subject": "CHEBI:8888",
                        "object": "uuid:1",
                        "predicate": "biolink:member_of",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": []
                    },
                    "CHEBI:8888_biolink:has_chemical_role_CHEBI_ROLE_neurotransmitter_agent": {
                        "subject": "CHEBI:8888",
                        "object": "CHEBI_ROLE_neurotransmitter_agent",
                        "predicate": "biolink:has_chemical_role",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": []
                    },
                    "CHEBI:8707_biolink:member_of_uuid:1": {
                        "subject": "CHEBI:8707",
                        "object": "uuid:1",
                        "predicate": "biolink:member_of",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": []
                    },

                    # ===== RESULT 2 (PRUNE) =====

                    "CHEBI:9999_Inferred_to_biolink:treats_MONDO:0004975": {
                        "subject": "CHEBI:9999",
                        "object": "MONDO:0004975",
                        "predicate": "biolink:treats",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": [
                            {"attribute_type_id": "biolink:support_graphs", "value": "n_Inferred_SG:_CHEBI:9999_to_MONDO:0004975"}
                        ]
                    },
                    "CHEBI:9999_biolink:participates_in_PATHWAY:123": {
                        "subject": "CHEBI:9999",
                        "object": "PATHWAY:123",
                        "predicate": "biolink:participates_in",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": []
                    },
                    "e_PATHWAY:123_biolink:similar_to_uuid:2": {
                        "subject": "PATHWAY:123",
                        "object": "uuid:2",
                        "predicate": "biolink:similar_to",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": []
                    },
                    "uuid:2_biolink:treats_MONDO:0004975": {
                        "subject": "uuid:2",
                        "object": "MONDO:0004975",
                        "predicate": "biolink:treats",
                        "sources": [
                            {"resource_id": "infores:answercoalesce", "resource_role": "primary_knowledge_source"}],
                        "attributes": []
                    }
                }
            },
            "auxiliary_graphs": {
                # Result 1 aux graphs (KEEP)
                "n_Inferred_SG:_CHEBI:6123_to_MONDO:0004975": {
                    "edges": [
                        "CHEBI:6123_biolink:has_chemical_role_CHEBI_ROLE_neurotransmitter_agent",
                        "e_CHEBI_ROLE_neurotransmitter_agent_biolink:similar_to_uuid:1",
                        "uuid:1_biolink:treats_MONDO:0004975"
                    ],
                    "attributes": []
                },
                "SG:_CHEBI:8888_lookup": {
                    "edges": [
                        "CHEBI:8888_biolink:member_of_uuid:1",
                        "CHEBI:8888_biolink:has_chemical_role_CHEBI_ROLE_neurotransmitter_agent"
                    ],
                    "attributes": []
                },
                "SG:_CHEBI:8707_lookup": {
                    "edges": [
                        "CHEBI:8707_biolink:member_of_uuid:1"
                    ],
                    "attributes": []
                },

                # Result 2 aux graphs (PRUNE)
                "n_Inferred_SG:_CHEBI:9999_to_MONDO:0004975": {
                    "edges": [
                        "CHEBI:9999_biolink:participates_in_PATHWAY:123",
                        "e_PATHWAY:123_biolink:similar_to_uuid:2",
                        "uuid:2_biolink:treats_MONDO:0004975"
                    ],
                    "attributes": []
                }
            },
            "results": []
        }
    }


def create_edgar_results():
    return {
        "result_1": {
            "node_bindings": {
                "disease": [{"id": "MONDO:0004975"}],
                "chemical": [{"id": "CHEBI:6123"}]
            },
            "analyses": [{
                "edge_bindings": {"e00": [{"id": "CHEBI:6123_Inferred_to_biolink:treats_MONDO:0004975"}]},
                "score": 0.869
            }]
        },
        "result_2": {
            "node_bindings": {
                "disease": [{"id": "MONDO:0004975"}],
                "chemical": [{"id": "CHEBI:9999"}]
            },
            "analyses": [{
                "edge_bindings": {"e00": [{"id": "CHEBI:9999_Inferred_to_biolink:treats_MONDO:0004975"}]},
                "score": 0.450
            }]
        }
    }


def test_prune_to_top_result():
    """Keep top 1 result, prune everything else"""
    message = create_edgar_message()
    results = create_edgar_results()

    builder = EGARTRAPIBuilder(message)

    print(f"\nBefore pruning:")
    print(f"  Nodes: {len(builder.kg_nodes)}")
    print(f"  Edges: {len(builder.kg_edges)}")
    print(f"  Aux graphs: {len(builder.aux_graphs)}")

    # Keep only top 1
    sorted_results = sorted(results.values(), key=lambda x: x["analyses"][0]["score"], reverse=True)[:1]

    builder.results.clear()
    builder.results.extend(sorted_results)
    import json
    with open("sample_edgar_results.json", "w") as f:
        json.dump(builder.message, f, indent=2)
    prune_message(builder, sorted_results)

    with open("sampleafterprune.json", "w") as f:
        json.dump(builder.message, f, indent=2)

    print(f"\nAfter pruning:")
    print(f"  Nodes: {len(builder.kg_nodes)}")
    print(f"  Edges: {len(builder.kg_edges)}")
    print(f"  Aux graphs: {len(builder.aux_graphs)}")

    # === Assertions ===

    # KEEP: Result 1 nodes
    assert "CHEBI:6123" in builder.kg_nodes
    assert "CHEBI_ROLE_neurotransmitter_agent" in builder.kg_nodes
    assert "uuid:1" in builder.kg_nodes
    assert "CHEBI:8888" in builder.kg_nodes
    assert "CHEBI:8707" in builder.kg_nodes
    assert "MONDO:0004975" in builder.kg_nodes  # Shared

    # PRUNE: Result 2 nodes
    assert "CHEBI:9999" not in builder.kg_nodes
    assert "PATHWAY:123" not in builder.kg_nodes
    assert "uuid:2" not in builder.kg_nodes

    # KEEP: Result 1 edges
    assert "CHEBI:6123_Inferred_to_biolink:treats_MONDO:0004975" in builder.kg_edges
    assert "CHEBI:6123_biolink:has_chemical_role_CHEBI_ROLE_neurotransmitter_agent" in builder.kg_edges
    assert "e_CHEBI_ROLE_neurotransmitter_agent_biolink:similar_to_uuid:1" in builder.kg_edges
    assert "uuid:1_biolink:treats_MONDO:0004975" in builder.kg_edges
    assert "CHEBI:8888_biolink:member_of_uuid:1" in builder.kg_edges
    assert "CHEBI:8888_biolink:has_chemical_role_CHEBI_ROLE_neurotransmitter_agent" in builder.kg_edges
    assert "CHEBI:8707_biolink:member_of_uuid:1" in builder.kg_edges

    # PRUNE: Result 2 edges
    assert "CHEBI:9999_Inferred_to_biolink:treats_MONDO:0004975" not in builder.kg_edges
    assert "CHEBI:9999_biolink:participates_in_PATHWAY:123" not in builder.kg_edges
    assert "e_PATHWAY:123_biolink:similar_to_uuid:2" not in builder.kg_edges
    assert "uuid:2_biolink:treats_MONDO:0004975" not in builder.kg_edges

    # KEEP: Result 1 aux graphs
    assert "n_Inferred_SG:_CHEBI:6123_to_MONDO:0004975" in builder.aux_graphs
    assert "SG:_CHEBI:8888_lookup" in builder.aux_graphs
    assert "SG:_CHEBI:8707_lookup" in builder.aux_graphs

    # PRUNE: Result 2 aux graphs
    assert "n_Inferred_SG:_CHEBI:9999_to_MONDO:0004975" not in builder.aux_graphs

    print("\n✓ Test PASSED")
    print(f"  ✓ Kept Result 1: CHEBI:6123 → MONDO:0004975 (score 0.869)")
    print(f"  ✓ Pruned Result 2: CHEBI:9999 → MONDO:0004975 (score 0.450)")
    print(
        f"  ✓ Final counts: {len(builder.kg_nodes)} nodes, {len(builder.kg_edges)} edges, {len(builder.aux_graphs)} aux graphs")