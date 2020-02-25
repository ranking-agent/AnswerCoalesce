import pytest
import src.single_node_coalescer as mc

def xtest_indexer():
    results = [ {'node_bindings':[{'qg_id':'qid0','kg_id':'kgid0'},
                                  {'qg_id':'qid1','kg_id':'kgid2'}]},
                {'node_bindings':[{'qg_id':'qid0','kg_id':'kgid0'},
                                  {'qg_id':'qid1','kg_id':'kgid1'}]},
                {'node_bindings':[{'qg_id':'qid0','kg_id':'kgid2'},
                                  {'qg_id':'qid1','kg_id':'kgid1'}]}
               ]
    index = mc.index_results(results)
    assert len(index) == 2
    assert 'qid0' in index
    assert 'qid1' in index
    assert len(index['qid0']) == 2
    assert len(index['qid0']['kgid0']) == 2
    assert 0 in index['qid0']['kgid0']
    assert 1 in index['qid0']['kgid0']
    assert len(index['qid0']['kgid2']) == 1
    assert 2 in index['qid0']['kgid2']
    assert len(index['qid1']) == 2
    assert len(index['qid1']['kgid2']) == 1
    assert 0 in index['qid1']['kgid2']
    assert len(index['qid1']['kgid1']) == 2
    assert 1 in index['qid1']['kgid1']
    assert 2 in index['qid1']['kgid1']

def xtest_node_matches_basic():
    """For a 2 node qg, we should return any grouping of the other node.
    So for this results file, if the vnode is qid0, then we should get results 1 and 2 together (matching kgid1)
    and if the vnode is qid1, we should get results 0,1 where both match kgid0"""
    results = [ {'node_bindings':[{'qg_id':'qid0','kg_id':'kgid0'},
                                  {'qg_id':'qid1','kg_id':'kgid2'}]},
                {'node_bindings':[{'qg_id':'qid0','kg_id':'kgid0'},
                                  {'qg_id':'qid1','kg_id':'kgid1'}]},
                {'node_bindings':[{'qg_id':'qid0','kg_id':'kgid2'},
                                  {'qg_id':'qid1','kg_id':'kgid1'}]}
               ]
    index = mc.index_results(results)
    #qid0
    matches = mc.find_partial_matches_by_node(index,'qid0')
    assert len(matches) == 1
    d,s = matches[0]
    assert len(d) == 1
    assert d['qid1'] == 'kgid1'
    assert len(s) == 2
    assert 1 in s
    assert 2 in s
    #qid1
    matches = mc.find_partial_matches_by_node(index,'qid1')
    assert len(matches) == 1
    d,s = matches[0]
    assert len(d) == 1
    assert d['qid0'] == 'kgid0'
    assert len(s) == 2
    assert 1 in s
    assert 0 in s

def xtest_node_matches_none():
    """Because qid2 are all unique, we'll get no answers"""
    results = [ {'node_bindings':[{'qg_id':'qid0','kg_id':'kgid0'},
                                  {'qg_id':'qid1','kg_id':'kgid2'},
                                  {'qg_id':'qid2','kg_id':'kgid3'}]},
                {'node_bindings':[{'qg_id':'qid0','kg_id':'kgid0'},
                                  {'qg_id':'qid1','kg_id':'kgid2'},
                                  {'qg_id':'qid2','kg_id':'kgid4'}]},
                {'node_bindings':[{'qg_id':'qid0','kg_id':'kgid2'},
                                  {'qg_id':'qid1','kg_id':'kgid1'},
                                  {'qg_id':'qid2','kg_id':'kgid5'}]}
               ]
    index = mc.index_results(results)
    matches = mc.find_partial_matches_by_node(index,'qid0')
    assert len(matches) == 0

def xtest_node_matches_multiple():
    """Because qid2 are all unique, we'll get no answers"""
    results = [{'node_bindings': [{'qg_id': 'qid0', 'kg_id': 'kgid0'},
                                  {'qg_id': 'qid1', 'kg_id': 'kgid2'},
                                  {'qg_id': 'qid2', 'kg_id': 'kgid3'}]},
               {'node_bindings': [{'qg_id': 'qid0', 'kg_id': 'kgid0'},
                                  {'qg_id': 'qid1', 'kg_id': 'kgid2'},
                                  {'qg_id': 'qid2', 'kg_id': 'kgid4'}]},
               {'node_bindings': [{'qg_id': 'qid0', 'kg_id': 'kgid0'},
                                  {'qg_id': 'qid1', 'kg_id': 'kgid1'},
                                  {'qg_id': 'qid2', 'kg_id': 'kgid4'}]},
               {'node_bindings': [{'qg_id': 'qid0', 'kg_id': 'kgid0'},
                                  {'qg_id': 'qid1', 'kg_id': 'kgid1'},
                                  {'qg_id': 'qid2', 'kg_id': 'kgid5'}]}
               ]
    index = mc.index_results(results)
    matches = mc.find_partial_matches_by_node(index, 'qid2')
    assert len(matches) == 2
    for x,m in matches:
        assert len(m) == 2
