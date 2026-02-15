import os, pytest, json
from fastapi.testclient import TestClient
from reasoner_pydantic import Response as PDResponse

from src.server import APP

client = TestClient(APP)

jsondir = 'InputJson_1.5'


#This test requires too large of a test redis (the load files get bigger than github likes) so we keep it around
# to run locally against prod redises, but we use the mark to not run it on github actions
@pytest.mark.nongithub
def test_drugs_to_disease_inference():
    in_message = {
        "message": {
            "query_graph": {
                "nodes": {
                    "n0": {
                        "categories": [
                            "biolink:Drug"
                        ]
                    },
                    "n1": {
                        "ids": [
                            "MONDO:0004975"
                        ],
                        "categories": [
                            "biolink:Disease"
                        ]
                    }
                },
                "edges": {
                    "e0": {
                        "subject": "n0",
                        "object": "n1",
                        "predicates": [
                            "biolink:treats"
                        ],
                        "knowledge_type": "inferred",
                        "attribute_constraints": [],
                        "qualifier_constraints": []
                    }
                }
            }
        },
        "parameters": {
            "pvalue_threshold": 0.00001,
            "max_rules": 10,
            "predicate_constraint_style": "exclude",
            "predicate_constraints": [
                "biolink:causes",
                "biolink:biomarker_for",
                "biolink:contraindicated_for",
                "biolink:contraindicated_in",
                "biolink:contributes_to",
                "biolink:has_adverse_event",
                "biolink:causes_adverse_event",
                "biolink:similar_to",
                "biolink:treats_or_applied_or_studied_to_treat",
                "biolink:subclass_of"
            ]
        }
    }
    jret = run_test(in_message)
    assert (len(jret["message"]) == 4)  # 4 because of the additional parameter: auxilliary_Graph


@pytest.mark.nongithub
def test_genes_to_disease_inference():
    # Sample lookup query with inferred knowledge_type
    # It does both property and graph enrichment
    in_message = {
        "parameters": {
            "pvalue_threshold": 1e-5,
            "result_length": 100,
            "predicates_to_exclude": [
                "biolink:causes", "biolink:biomarker_for", "biolink:contraindicated_for", "biolink:contraindicated_in",
                "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event",
                "biolink:similar_to",
                "treats_or_applied_or_studied_to_treat", "biolink:subclass_of"
            ]
        },
        "message": {
            "query_graph": {
                "nodes": {
                    "chemical": {
                        "categories": [
                            "biolink:Drug"
                        ],
                        "is_set": False,
                        "constraints": []
                    },
                    "disease": {
                        "ids": [
                            "MONDO:0004975"
                        ],
                        "is_set": False,
                        "constraints": []
                    }
                },
                "edges": {
                    "e00": {
                        "subject": "chemical",
                        "object": "disease",
                        "predicates": [
                            "biolink:treats"
                        ],
                        "knowledge_type": "inferred",
                        "attribute_constraints": [],
                        "qualifier_constraints": []
                    }
                }
            }
        }
    }

    jret = run_test(in_message)
    assert (len(jret["message"]) == 4)  # 4 because of the additional parameter: auxilliary_Graph
    confirm_qg_nodes(in_message, jret, is_source_ids=False)


@pytest.mark.nongithub
def test_phenotype_to_genes_inference():
    in_message = {
        "message": {
            "query_graph": {
                "nodes": {
                    "input": {
                        "categories": [
                            "biolink:PhenotypicFeature"
                        ],
                        "ids": [
                            "HP:0003637"
                        ]
                    },
                    "output": {
                        "categories": [
                            "biolink:Gene"
                        ]
                    }
                },
                "edges": {
                    "edge_0": {
                        "subject": "output",
                        "object": "input",
                        "predicates": [
                            "biolink:affects"
                        ],
                        "knowledge_type": "inferred"
                    }
                }
            }
        },
        "parameters": {
            "pvalue_threshold": 1e-03,
            "max_results": 1000,
            "predicate_constraints": []
        }
    }

    jret = run_test(in_message)
    assert (len(jret["message"]) == 4)  # 4 because of the additional parameter: auxilliary_Graph
    confirm_qg_nodes(in_message, jret, is_source_ids=False)


@pytest.mark.nongithub
def test_disease_to_phenotypes_inference():
    in_message = {
        "message": {
            "query_graph": {
                "nodes": {
                    "input": {
                        "categories": [
                            "biolink:Disease"
                        ],
                        "ids": [
                            "MONDO:0005147"
                        ]
                    },
                    "output": {
                        "categories": [
                            "biolink:PhenotypicFeature"
                        ]
                    }
                },
                "edges": {
                    "edge_0": {
                        "subject": "input",
                        "object": "output",
                        "predicates": [
                            "biolink:has_phenotype"
                        ],
                        "knowledge_type": "inferred"
                    }
                }
            }
        },
        "parameters": {
            "pvalue_threshold": 1e-05,
            "max_results": 100,
            "predicate_constraints": []
        }
    }

    jret = run_test(in_message)
    assert (len(jret["message"]) == 4)  # 4 because of the additional parameter: auxilliary_Graph
    confirm_qg_nodes(in_message, jret, is_source_ids=True)

@pytest.mark.nongithub
def test_genes_to_chemical_mcq():
    in_message = {
        "message": {
            "query_graph": {
                "nodes": {
                    "input": {
                        "categories": [
                            "biolink:Gene"
                        ],
                        "ids": [
                            "uuid:1"
                        ],
                        "member_ids": [
                            "NCBIGene:5297",
                            "NCBIGene:5298",
                            "NCBIGene:5290"
                        ],
                        "set_interpretation": "MANY"
                    },
                    "output": {
                        "categories": [
                            "biolink:ChemicalEntity"
                        ]
                    }
                },
                "edges": {
                    "edge_0": {
                        "subject": "input",
                        "object": "output",
                        "predicates": [
                            "biolink:related_to"
                        ]
                    }
                }
            }
        }
    }
    jret = run_test(in_message)
    assert (len(jret["message"]) == 4)  # 4 because of the additional parameter: auxilliary_Graph
    confirm_qg_nodes(in_message, jret, is_source_ids=True)

@pytest.mark.nongithub
def test_phenotype_to_gene_mcq_no_enrichment():
    in_message = {
        "message": {
            "query_graph": {
                "nodes": {
                    "input": {
                        "categories": [
                            "biolink:PhenotypicFeature"
                        ],
                        "ids": [
                            "uuid:1"
                        ],
                        "member_ids": [
                            "HP:0000729",
                            "HP:0012758",
                            "HP:0001249",
                            "HP:0001629",
                            "HP:0001999",
                            "HP:0002705",
                            "HP:0000426",
                            "HP:0000586",
                            "HP:0010490"
                        ],
                        "set_interpretation": "MANY"
                    },
                    "output": {
                        "categories": [
                            "biolink:Gene"
                        ]
                    }
                },
                "edges": {
                    "edge_0": {
                        "subject": "input",
                        "object": "output",
                        "predicates": [
                            "biolink:genetically_associated_with"
                        ]
                    }
                }
            }
        }
    }
    jret = run_test(in_message)
    assert (len(jret["message"]) == 2)  # 2 because only Query Graph and Knowledge graph exist with no enrichment


def run_test(in_message):
    assert PDResponse.parse_obj(in_message)
    response = client.post('/query', json=in_message)
    # was the request successful
    assert (response.status_code == 200)
    # convert the response to a json object
    jret = json.loads(response.content)
    return jret


def confirm_qg_nodes(in_message, jret, is_source_ids=False):
    message = jret['message']
    kgnodes = message["knowledge_graph"]["nodes"]
    kgedges = message["knowledge_graph"]["edges"]
    result0 = message['results'][0]
    assert len(result0['node_bindings']) == 2

    if is_source_ids:
        input_ids_from = "subject"
        output_cat_from = "object"
    else:
        input_ids_from = "object"
        output_cat_from = "subject"

    query_graph = in_message['message']['query_graph']
    for qgedge_id, qgedge in query_graph['edges'].items():
        inferred_edges = result0["analyses"][0]["edge_bindings"][qgedge_id][0]["id"]
        the_edge = kgedges[inferred_edges]
        assert query_graph['nodes'][qgedge[input_ids_from]]['ids'][0] == the_edge[input_ids_from]
        assert query_graph['nodes'][qgedge[output_cat_from]]['categories'][0] in \
               kgnodes[the_edge[output_cat_from]]['categories']