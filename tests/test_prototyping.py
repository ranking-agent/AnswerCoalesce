import pytest
import json, os, asyncio
from ruleandmultiquery import lookup
jsondir = 'InputJson_1.4'


def test_pathfinder1_():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'sampleset2.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
    newset = asyncio.run(lookup(answerset))
    if newset:
        if len(newset)>1:
            assert 'message' in newset[0]
            assert 'message' in newset[1]
        else:
            assert 'message' in newset
            assert 'result' in newset['message']



# if __name__ == '__main__':
#     try:
#         test_pathfinder1_()
#     except ConnectionError as cn:
#         print(cn)