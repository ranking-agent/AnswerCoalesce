import os

import jsonschema
import pytest
import yaml
import json
from fastapi.testclient import TestClient
from src.server import APP


client = TestClient(APP)

jsondir= 'InputJson_1.1'

def test_coalesce():
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
    assert(len(ret) == 3)
    assert( len(ret['results'])-len(answerset['message']['results']) == 118 )

def test_unique_coalesce():
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir,'famcov_new.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/ontology', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    jret = json.loads(response.content)

    ret = jret['message']
    assert('results' in ret)
    assert( len(ret['results'])-len(answerset['message']['results']) <= 4 )

def test_schizo_coalesce():
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

    #assert('results' in ret)
    #assert( len(ret['results']) <= 4 )

    jr = response.json()
    assert 'message' in jr

def test_lookup_graph_coalesce():
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

def test_diabetes_drugs_prop():
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

def test_ms_drugs_500():
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