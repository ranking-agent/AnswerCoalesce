import pytest
import json
import os
import src.single_node_coalescer as snc
import src.ontology_coalescence.ontology_coalescer as oc
from src.components import Opportunity

input_dir = 'InputJson_1.1'

def test_big_ontology():
    fn = f'{input_dir}/bigger_new.json'
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),fn)
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='ontology')
    rs = newset['results']
    print(len(rs))

def test_big_graphbased():
    fn = f'{input_dir}/bigger_new.json'
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),fn)
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='graph')
    rs = newset['results']
    print(len(rs))

