import pytest
import json
import os
import src.single_node_coalescer as snc

input_dir = 'InputJson_1.1'

def xtest_killer_graphbased():
    fn = f'InputJson_1.2/killer.json'
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),fn)
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='graph')
    rs = newset['results']
    print(len(rs))

def xtest_big_graphbased():
    #Removed to keep backlink flow small
    fn = f'{input_dir}/bigger_new.json'
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),fn)
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='graph')
    rs = newset['results']
    print(len(rs))

def xtest_big_graphbased():
    """This input is over the github file size limit, so removing the test.  But it's good for profiling"""
    fn = f'{input_dir}/workflowb_strider_out.json'
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),fn)
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='graph')
    rs = newset['results']
    print(len(rs))