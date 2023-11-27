import os

import jsonschema
import pytest
import yaml
import json
from fastapi.testclient import TestClient
from reasoner_pydantic import Response as PDResponse
from datetime import datetime
from src.server import APP


client = TestClient(APP)

jsondir= 'InputJson_1.4'


def set_workflowparams(lookup_results):
    # Dummy parameters to check igf reasoner pydantic accepts the new parameters
    return lookup_results.update({"workflow": [
        {
            "id": "enrich_results",
            "parameters":
            {
                "predicates_to_exclude": ["biolink:causes", "biolink:biomarker_for", "biolink:biomarker_for", "biolink:contraindicated_for",
                    "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"],
                "properties_to_exclude": ["CHEBI_ROLE_drug", 'CHEBI_ROLE_pharmaceutical', 'CHEBI_ROLE_pharmacological_role']
            }
        }
    ]})

#This test requires too large of a test redis (the load files get bigger than github likes) so we keep it around
# to run locally against prod redises, but we use the mark to not run it on github actions
@pytest.mark.nongithub
def test_basic():
    """Bring back when properties are working again"""
    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    # testfilename = os.path.join(dir_path,jsondir,'D.1_strider.json')
    #
    # with open(testfilename, 'r') as tf:
    #     answerset = json.load(tf)

    testfilename = os.path.join(dir_path, jsondir, 'alzheimer_with_workflowparams.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        set_workflowparams(answerset)
        # assert PDResponse.parse_obj(answerset)

    #there are dups in this result set gross: dedup
    unique_results = {}
    for result in answerset['message']['results']:
        key = json.dumps(result,sort_keys=True)
        unique_results[key] = result

    answerset['message']['results'] = list(unique_results.values())

    assert PDResponse.parse_obj(answerset)
    # make a good request
    response = client.post('/coalesce/all', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    # check the data
    ret = jret['message']
    assert(len(ret) == 3 or len(ret) == 4) # 4 because of the additional parameter: auxilliary_Graph
    assert( len(ret['query_graph']['nodes']) < 6)

    assert( len(ret['results'])==len(answerset['message']['results']))

@pytest.mark.nongithub
def test_basicall():
    """Bring back when properties are working again"""
    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    # testfilename = os.path.join(dir_path,jsondir,'D.1_strider.json')
    #
    # with open(testfilename, 'r') as tf:
    #     answerset = json.load(tf)

    testfilename = os.path.join(dir_path, jsondir, 'sampleset1.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        set_workflowparams(answerset)
        # assert PDResponse.parse_obj(answerset)

    #there are dups in this result set gross: dedup

    assert PDResponse.parse_obj(answerset)
    # make a good request
    response = client.post('/query/all', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    # check the data
    ret = jret['message']
    with open(f"newset{datetime.now()}.json", 'w') as outf:
        json.dump(ret, outf, indent=4)
    assert(len(ret) == 3 or len(ret) == 4) # 4 because of the additional parameter: auxilliary_Graph


@pytest.mark.nongithub
def test_property():
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

def xtest_wfa3():
    """Bring back when properties are working again"""
    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    testfilename = os.path.join(dir_path,jsondir,'a3.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/all', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    # check the data
    ret = jret['message']
    assert(len(ret) == 3 or len(ret) == 4)
    assert( len(ret['results'])-len(answerset['message']['results']) > 0 )

def test_set_coalesce():
    """This is a 2 hop query with three answers
    A B C
    A B D
    A E D
    So it should produce 2 set coalesces: A B (CD), A (BE) D
    """
    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    testfilename = os.path.join(dir_path,jsondir,'twohop.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/set', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    # check the data
    ret = jret['message']
    assert(len(ret) == 3 or len(ret) == 4) # 4 because of the additional param: auxilliary_Graph
    assert( len(ret['results'])==len(answerset['message']['results']) )


def xtest_coalesce():
    """Bring back when properties are working again"""
    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    testfilename = os.path.join(dir_path,jsondir,'asthma_one_hop.json')

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
    assert(len(ret) == 3 or len(ret) == 4) # 4 because of the additional param: auxilliary_Graph
    assert( len(ret['results'])-len(answerset['message']['results']) == 118 )


def xfailed_relation_attrib_error_test_schizo_coalesce():
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'famcov_new.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/graph', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    jr = response.json()
    assert 'message' in jr

def xtest_lookup_graph_coalesce():
    """This test is fine when running against prod, but it's not a travis test case b/c we don't
    put this json into our test redis"""
    #This file is producing 500's
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'strider_out_issue_60.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/graph', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    original_answers = len(answerset['message']['results'])
    final_answers    = len(response.json()['message']['results'])
    rj = response.json()
    assert final_answers > original_answers

def xtest_diabetes_drugs_prop():
    #turn this back on when props are working again.
    #This file is producing 500's
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'diabetes_drugs.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/property', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    original_answers = len(answerset['message']['results'])
    final_answers    = len(response.json()['message']['results'])
    rj = response.json()
    for result in rj['message']['results']:
        assert len(result['node_bindings']['drug']) == len(result['edge_bindings']['treats'])
    assert final_answers > original_answers

def xtest_ms_drugs_500():
    """A fine test against prod but not agains the test redis unless we want to put wfc1 in the test redis."""
    #This file is producing 500's
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'wfc1_strider.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/graph', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    original_answers = len(answerset['message']['results'])
    final_answers    = len(response.json()['message']['results'])
    rj = response.json()
    assert final_answers > original_answers

def xtest_500():
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'bad_coalesce.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/graph', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    original_answers = len(answerset['message']['results'])
    final_answers    = len(response.json()['message']['results'])
    rj = response.json()
    assert final_answers > original_answers


def test_no_results():
    #Don'tfreak out if strider doesn't find anything
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'no_results.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/all', json=answerset)

    # was the request successful
    assert(response.status_code == 200)