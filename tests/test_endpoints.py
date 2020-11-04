import os

import jsonschema
import pytest
import yaml
import json
from fastapi.testclient import TestClient
from src.server import APP


client = TestClient(APP)

def test_coalesce():
    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    testfilename = os.path.join(dir_path, 'asthma_one_hop.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/property', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    ret = json.loads(response.content)

    # check the data
    assert(len(ret) == 3)
    assert( len(ret['results']) == 118 )

def test_unique_coalesce():
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, 'famcov_new.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # make a good request
    response = client.post('/coalesce/ontology', json=answerset)

    # was the request successful
    assert(response.status_code == 200)

    # convert the response to a json object
    ret = json.loads(response.content)

    assert('results' in ret)
    assert( len(ret['results']) <= 4 )

def test_schizo_coalesce():
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, 'schizo.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # setup some parameters
    param = {'method': 'graph'}

    # make a good request
    request, response = app.test_client.post('/coalesce', params= param, data=json.dumps(answerset))

    # was the request successful
    assert(response.status == 200)

    # convert the response to a json object
    ret = json.loads(response.body)

    #assert('results' in ret)
    #assert( len(ret['results']) <= 4 )