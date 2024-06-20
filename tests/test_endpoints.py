import os, pytest, json
from fastapi.testclient import TestClient
from reasoner_pydantic import Response as PDResponse

from src.server import APP

client = TestClient(APP)

jsondir= 'InputJson_1.5'


#This test requires too large of a test redis (the load files get bigger than github likes) so we keep it around
# to run locally against prod redises, but we use the mark to not run it on github actions
@pytest.mark.nongithub
def xtest_coalesce_basic():
    """Bring back when properties are working again"""
    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'alzheimer_with_workflowparams.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    #there are dups in this result set gross: dedup
    unique_results = {}
    for result in answerset['message']['results']:
        key = json.dumps(result,sort_keys=True)
        unique_results[key] = result

    answerset['message']['results'] = list(unique_results.values())

    assert PDResponse.parse_obj(answerset)
    # make a good request
    response = client.post('/coalesce/graph', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    # check the data
    ret = jret['message']
    # with open("jret", "w+") as f:
    #     json.dump(ret, f, indent=4)

    assert(len(ret) == 3 or len(ret) == 4) # 4 because of the additional parameter: auxilliary_Graph
    assert( len(ret['results'])==len(answerset['message']['results']))


# @pytest.mark.nongithub
def test_infer():
    # Sample lookup query with inferred knowledge_type
    answerset = {
        "parameters": {
            "pvalue_threshold": 1e-5,
            "result_length": 100,
            "predicates_to_exclude": [
                "biolink:causes", "biolink:biomarker_for", "biolink:biomarker_for", "biolink:contraindicated_for",
                "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"
            ]
        },
        "message": {
            "query_graph": {
                "nodes": {
                    "chemical": {
                        "categories": [
                            "biolink:ChemicalEntity"
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

    assert PDResponse.parse_obj(answerset)

    response = client.post('/query', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    with open("MONDO0004975.json", "w") as json_file:
        json.dump(jret, json_file, indent=4)

    ret = jret['message']

    assert(len(ret) == 4) # 4 because of the additional parameter: auxilliary_Graph

@pytest.mark.nongithub
def xtest_property():
    """Bring back when properties are working again"""
    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    testfilename = os.path.join(dir_path,jsondir,'property_ac_input.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/property', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    # check the data
    ret = jret['message']
    assert(len(ret) == 3 or len(ret) == 4) # 4 because of the additional parameter: auxilliary_Graph
    assert( len(ret['results'])==len(answerset['message']['results']))

