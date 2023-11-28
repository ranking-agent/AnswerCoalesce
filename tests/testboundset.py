import pytest
import os, json
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from reasoner_pydantic import Response as PDResponse
from datetime import datetime

jsondir ='InputJson_1.4'

def test_pathfinderac():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'sampleset.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        answerset = answerset['message']

    newset = snc.coalesce(answerset, method='graph')

    #uncomment this to save the result to the directory
    # with open(f"newset{datetime.now()}.json", 'w') as outf:
    #     json.dump(newset, outf, indent=4)
    assert PDResponse.parse_obj({'message': newset})
    # Must be at least the length of the initial nodeset
    nodeset = {}
    for qg_id, node_data in newset.get("query_graph", {}).get("nodes", {}).items():
        if 'ids' in node_data and node_data.get('is_set'):
            nodeset = set(node_data.get('ids', []))
    assert len(newset['results']) >= len(nodeset)

