import pytest
import src.graph_coalescence.graph_coalescer as gc
from src.single_node_coalescer import identify_coalescent_nodes
from src.components import Opportunity,Answer
from src.graph_coalescence.robokop_messenger import RobokopMessenger

def test_get_node_count():
    # fire up the class
    rm = RobokopMessenger()

    # call to get the number of nodes
    n = rm.get_hit_node_count('HGNC:108', 'decreases_activity_of', False, 'chemical_substance')

    # get the expected node count
    assert n == 2184

def test_get_links_for():
    rm = RobokopMessenger()
    links = rm.get_links_for('MESH:D006843', 'chemical_substance')

    # this normally returns 92 links
    assert len(links) == 92

    # the curie at this location is ('GO:0018978')
    assert links[0][0] == 'GO:0018978'

def test_shared_links():
    sl = gc.get_shared_links(set(['HGNC:869','HGNC:870']), 'gene')
    # Because we only had a pair of inputs, we should only get a single output.
    assert len(sl) == 1
    fams = []
    for value in sl.values():
        for curie,pred,is_source in value:
            if pred == 'part_of':
                assert is_source
                fams.append(curie)
    assert len(fams) > 0
    assert 'HGNC.FAMILY:1212' in fams

def test_enriched_links():
    """This pair of genes is chosen because they're not connected to much that is connected
    to much, so the test runs quickly.  The downside is that we get an unrealistically
    low number of results, but it doesn't take all day."""
    sl = gc.get_enriched_links(set(['HGNC:4295', 'HGNC:23263']), 'gene')
    assert sl[0][1] == 'HGNC.FAMILY:568'

def test_enriched_links_hg():
    """This set of genes is chosen because it runs quickly"""
    sl = gc.get_enriched_links(set(['HGNC:44283', 'HGNC:44284','HGNC:44282']), 'gene')
    assert sl[0][1] == 'HGNC.FAMILY:1384'
    assert sl[0][5] == 5

def test_ontology_coalescer():
    curies = [ 'HGNC:44283', 'HGNC:44284','HGNC:44282' ]
    opportunity = Opportunity('hash',('qg_0','gene'),curies,[0,1,2])
    opportunities=[opportunity]
    patches = gc.coalesce_by_graph(opportunities)
    assert len(patches) == 1
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    p = patches[0]
    assert p.qg_id == 'qg_0'
    assert len(p.set_curies) == 3 # 3 of the 3 curies are subclasses of the output
    assert p.new_props['coalescence_method'] == 'graph_enrichment'
    assert p.new_props['p_value'] < 1e-10
    assert isinstance(p.new_props['enriched_nodes'],list)

def test_graph_coalescer_perf_test():
    from src.single_node_coalescer import coalesce
    import os
    import json
    import datetime

    # get a timestamp
    t1 = datetime.datetime.now()

    # get the path to the test file
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'EdgeIDAsStrAndPerfTest.json')

    # open the file and load it
    with open(test_filename,'r') as tf:
        incoming = json.load(tf)

    # call function that does property coalesce
    coalesced = coalesce(incoming, method='graph')

    # get the amount of time it took
    diff = datetime.datetime.now() - t1

    # it should be less than this
    assert(diff.seconds < 60)

    # loop through the query_graph return and insure that edge ids are strs
    for n in coalesced['query_graph']['edges']:
        assert(isinstance(n['id'], str))

    # loop through the knowledge_graph return and insure that edge ids are strs
    for n in coalesced['knowledge_graph']['edges']:
        assert(isinstance(n['id'], str))
