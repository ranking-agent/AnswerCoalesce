import os

import jsonschema
import pytest
import yaml
import json
from src.server import app


def test_coalesce():
    # get the location of the Translator specification file
    dir_path: str = os.path.dirname(os.path.realpath(__file__))

    # load the Translator specification
    with open(os.path.join(dir_path, '../src/translator_interchange_0.9.0.yaml')) as f:
        spec: dict = yaml.load(f, Loader=yaml.SafeLoader)

    testfilename = os.path.join(dir_path, 'asthma_one_hop.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # load the query specification, first get the result node
    validate_with: dict = spec["components"]["schemas"]["Result"]

    # then get the components in their own array so the relative references are found
    validate_with["components"] = spec["components"]

    # remove the result node because we already have it at the top
    validate_with["components"].pop("Result", None)

    jsonschema.validate(instance=answerset, schema=validate_with)

    # setup some parameters
    param = {'method': 'property'}

    # make a good request
    request, response = app.test_client.post('/coalesce', params= param, data=json.dumps(answerset))

    # was the request successful
    assert(response.status == 200)

    # convert the response to a json object
    ret = json.loads(response.body)

    # TODO: check the data
    assert(True)

def test_unique_coalesce():
    dir_path: str = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, 'famcov.json')

    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    # setup some parameters
    param = {'method': 'ontology'}

    # make a good request
    request, response = app.test_client.post('/coalesce', params= param, data=json.dumps(answerset))

    # was the request successful
    assert(response.status == 200)

    # convert the response to a json object
    ret = json.loads(response.body)

    assert('results' in ret)
    assert( len(ret['results']) <= 4 )