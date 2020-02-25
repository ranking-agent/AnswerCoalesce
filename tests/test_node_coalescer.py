import pytest
import src.master_coalescer as mc

def test_indexer():
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
