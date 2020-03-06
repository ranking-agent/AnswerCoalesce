import pytest
import src.graph_coalescence.graph_coalescer as gc
from src.single_node_coalescer import identify_coalescent_nodes
from src.components import Opportunity,Answer

def test_shared_links():
    sl = gc.get_shared_links(set(['HGNC:869','HGNC:870']),'gene')
    #Because we only had a pair of inputs, we should only get a single output.
    assert len(sl) == 1
    fams = []
    for value in sl.values():
        for curie,pred,is_source in value:
            if pred == 'part_of':
                assert is_source
                fams.append(curie)
    assert len(fams) > 0
    assert 'HGNC.FAMILY:1212' in fams

@pytest.mark.slow
def xtest_enriched_links():
    sl = gc.get_enriched_links(set(['HGNC:869', 'HGNC:870']), 'gene')
    tops = [ s[1] for s in sl[:3] ]
    assert 'HGNC.FAMILY:1212' in tops
