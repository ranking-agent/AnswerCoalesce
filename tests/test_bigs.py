import pytest
import json
import os
import src.single_node_coalescer as snc

input_dir = 'InputJson_1.1'


def test_big_graphbased():
    fn = f'{input_dir}/bigger_new.json'
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),fn)
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='graph')
    rs = newset['results']
    print(len(rs))

