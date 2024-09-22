import os, pytest, json
from fastapi.testclient import TestClient
from reasoner_pydantic import Response as PDResponse

from src.server import APP

client = TestClient(APP)

jsondir= 'InputJson_1.5'


#This test requires too large of a test redis (the load files get bigger than github likes) so we keep it around
# to run locally against prod redises, but we use the mark to not run it on github actions
@pytest.mark.nongithub
def test_disease_to_drugs_inference():
    # Sample lookup query with inferred knowledge_type
    # It does both property and graph enrichment
    in_message = {
        "parameters": {
            "pvalue_threshold": 1e-5,
            "result_length": 100,
            "predicates_to_exclude": [
                "biolink:causes", "biolink:biomarker_for", "biolink:contraindicated_for", "biolink:contraindicated_in",
                "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"
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
                            "MONDO:0004979"
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

    assert PDResponse.parse_obj(in_message)

    response = client.post('/query', json=in_message)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    # with open("MONDO0004979Drugfilterred.json", "w") as json_file:
    #     json.dump(jret, json_file, indent=4)

    message = jret['message']

    assert(len(message) == 4) # 4 because of the additional parameter: auxilliary_Graph
    kgnodes = message["knowledge_graph"]["nodes"]
    kgedges = message["knowledge_graph"]["edges"]
    result0 = message['results'][0]
    assert len(result0['node_bindings']) == 2
    for qgedge_id, qgedge in in_message['message']['query_graph']['edges'].items():
        inferred_edges = result0["analyses"][0]["edge_bindings"][qgedge_id][0]["id"]
        the_edge = kgedges[inferred_edges]
        assert in_message['message']['query_graph']['nodes'][qgedge["object"]]['ids'][0] == the_edge["object"]
        assert in_message['message']['query_graph']['nodes'][qgedge["subject"]]['categories'][0] in kgnodes[the_edge["subject"]]['categories']

@pytest.mark.nongithub
def test_gene_to_diseases_inference():
    # Sample lookup query with inferred knowledge_type
    # It does both property and graph enrichment
    in_message = {
        "parameters": {},
        "message": {
            "query_graph": {
                "nodes": {
                    "gene": {
                        "categories": [
                            "biolink:Gene"
                        ],
                        "is_set": False,
                        "constraints": []
                    },
                    "disease": {
                        "ids": [
                            "DOID:0050430"
                        ],
                        "is_set": False,
                        "constraints": []
                    }
                },
                "edges": {
                    "e00": {
                        "subject": "gene",
                        "object": "disease",
                        "predicates": [
                            "biolink:genetically_associated_with"
                        ],
                        "knowledge_type": "inferred",
                        "attribute_constraints": [],
                        "qualifier_constraints": []
                    }
                }
            }
        }
    }

    assert PDResponse.parse_obj(in_message)
    response = client.post('/query', json=in_message)
    # was the request successful
    assert(response.status_code == 200)
    # convert the response to a json object
    jret = json.loads(response.content)
    message = jret['message']
    assert(len(message) == 4) # 4 because of the additional parameter: auxilliary_Graph
    kgnodes = message["knowledge_graph"]["nodes"]
    kgedges = message["knowledge_graph"]["edges"]
    result0 = message['results'][0]
    assert len(result0['node_bindings']) == 2
    for qgedge_id, qgedge in in_message['message']['query_graph']['edges'].items():
        inferred_edges = result0["analyses"][0]["edge_bindings"][qgedge_id][0]["id"]
        the_edge = kgedges[inferred_edges]
        assert in_message['message']['query_graph']['nodes'][qgedge["object"]]['ids'][0] == the_edge["object"]
        assert in_message['message']['query_graph']['nodes'][qgedge["subject"]]['categories'][0] in kgnodes[the_edge["subject"]]['categories']

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
            "result_length": 1000,
            "predicates_to_exclude": []
          }
    }
    assert PDResponse.parse_obj(in_message)

    response = client.post('/query', json=in_message)

    # was the request successful
    assert (response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)
    message = jret['message']

    assert (len(message) == 4)  # 4 because of the additional parameter: auxilliary_Graph
    kgnodes = message["knowledge_graph"]["nodes"]
    kgedges = message["knowledge_graph"]["edges"]
    result0 = message['results'][0]
    assert len(result0['node_bindings']) == 2
    for qgedge_id, qgedge in in_message['message']['query_graph']['edges'].items():
        inferred_edges = result0["analyses"][0]["edge_bindings"][qgedge_id][0]["id"]
        the_edge = kgedges[inferred_edges]
        assert in_message['message']['query_graph']['nodes'][qgedge["object"]]['ids'][0] == the_edge["object"]
        assert in_message['message']['query_graph']['nodes'][qgedge["subject"]]['categories'][0] in \
               kgnodes[the_edge["subject"]]['categories']

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
        "result_length": 100,
        "predicates_to_exclude": []
      }
    }
    assert PDResponse.parse_obj(in_message)

    response = client.post('/query', json=in_message)

    # was the request successful
    assert (response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)
    message = jret['message']

    assert (len(message) == 4)  # 4 because of the additional parameter: auxilliary_Graph
    kgnodes = message["knowledge_graph"]["nodes"]
    kgedges = message["knowledge_graph"]["edges"]
    result0 = message['results'][0]
    assert len(result0['node_bindings']) == 2
    for qgedge_id, qgedge in in_message['message']['query_graph']['edges'].items():
        inferred_edges = result0["analyses"][0]["edge_bindings"][qgedge_id][0]["id"]
        the_edge = kgedges[inferred_edges]
        assert in_message['message']['query_graph']['nodes'][qgedge["subject"]]['ids'][0] == the_edge["subject"]
        assert in_message['message']['query_graph']['nodes'][qgedge["object"]]['categories'][0] in \
               kgnodes[the_edge["object"]]['categories']


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
    assert PDResponse.parse_obj(in_message)

    response = client.post('/query', json=in_message)

    # was the request successful
    assert (response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)
    message = jret['message']

    assert (len(message) == 4)  # 4 because of the additional parameter: auxilliary_Graph
    kgnodes = message["knowledge_graph"]["nodes"]
    kgedges = message["knowledge_graph"]["edges"]
    result0 = message['results'][0]
    assert len(result0['node_bindings']) == 2
    for qgedge_id, qgedge in in_message['message']['query_graph']['edges'].items():
        result_edges = result0["analyses"][0]["edge_bindings"][qgedge_id][0]["id"]
        the_edge = kgedges[result_edges]
        assert in_message['message']['query_graph']['nodes'][qgedge["subject"]]['ids'][0] == the_edge["subject"]
        assert in_message['message']['query_graph']['nodes'][qgedge["object"]]['categories'][0] in \
               kgnodes[the_edge["object"]]['categories']


@pytest.mark.nongithub
def test_phenotype_to_gene_mcq():
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
                    "HP:0001263",
                    "HP:0001250",
                    "HP:0012758",
                    "HP:0012434"
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
    assert PDResponse.parse_obj(in_message)

    response = client.post('/query', json=in_message)

    # was the request successful
    assert (response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)
    message = jret['message']

    assert (len(message) == 4)  # 4 because of the additional parameter: auxilliary_Graph
    kgnodes = message["knowledge_graph"]["nodes"]
    kgedges = message["knowledge_graph"]["edges"]
    result0 = message['results'][0]
    assert len(result0['node_bindings']) == 2
    for qgedge_id, qgedge in in_message['message']['query_graph']['edges'].items():
        result_edges = result0["analyses"][0]["edge_bindings"][qgedge_id][0]["id"]
        the_edge = kgedges[result_edges]
        assert in_message['message']['query_graph']['nodes'][qgedge["subject"]]['ids'][0] == the_edge["subject"]
        assert in_message['message']['query_graph']['nodes'][qgedge["object"]]['categories'][0] in \
               kgnodes[the_edge["object"]]['categories']
