import pytest
import json, os, asyncio
from ruleandmultiquery import lookup
jsondir = 'InputJson_1.4'


def xtest_pathfinder1_():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'samplesetnew.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
    newset = asyncio.run(lookup(answerset))
    assert 'message' in newset
    assert 'result' in newset['message']



# if __name__ == '__main__':
#     try:
#         test_pathfinder1_()
#     except ConnectionError as cn:
#         print(cn)