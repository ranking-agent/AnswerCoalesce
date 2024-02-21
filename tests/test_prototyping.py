import pytest
import json, os, asyncio
from src.multicurie_ac import multiCurieLookup
from fastapi.testclient import TestClient
jsondir = 'InputJson_1.4'
from src.server import APP
client = TestClient(APP)

def test_multicurie():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'sampleset4.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
    newset =  client.post('/query', json=answerset)
    newset_message = newset.json()["message"]
    if newset_message:
        assert len(newset_message) == 4
        assert 'results' in newset_message
        assert 'auxiliary_graphs' in newset_message
