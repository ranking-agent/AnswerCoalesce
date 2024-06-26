import os, pytest, json
from fastapi.testclient import TestClient
from reasoner_pydantic import Response as PDResponse

from src.server import APP

client = TestClient(APP)

jsondir= 'InputJson_1.5'


#This test requires too large of a test redis (the load files get bigger than github likes) so we keep it around
# to run locally against prod redises, but we use the mark to not run it on github actions
@pytest.mark.nongithub
def test_infer():
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

    assert PDResponse.parse_obj(in_message)

    response = client.post('/query', json=in_message)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    with open("MONDO0004975Drugfilterred.json", "w") as json_file:
        json.dump(jret, json_file, indent=4)

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
