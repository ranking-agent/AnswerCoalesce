import pytest
import src.graph_coalescence.graph_coalescer as gc
from src.single_node_coalescer import identify_coalescent_nodes
from src.components import Opportunity,Answer
from src.graph_coalescence.robokop_messenger import RobokopMessenger

def test_get_node_count():
    # fire up the class
    rm = RobokopMessenger()

    # call to get the number of nodes
    n = rm.get_hit_node_count('NCBIGENE:100328933', 'decreases_activity_of', False, 'chemical_substance')

    # get the expected node count
    assert n == 2

def test_get_links_for():
    """Test that we are able to retrieve edges from robokop.  We would rather point at KGX but this is it for now.
    We are also testing that we are aware of robokop's identifier converting.   We're passing in a mesh but what
    comes back in the KG will be a chebi.  make sure that we correctly identify the other node in this case."""
    rm = RobokopMessenger()
    nodes_type_list: dict = {}
    links = rm.get_links_for('MESH:D006843', 'chemical_substance', nodes_type_list)

    # The exact number doesn't matter
    assert len(links) > 20

    #MESH:D006843 == CHEBI:23115
    for link in links:
        assert 'CHEBI:23115' != link[0]

def test_shared_links():
    #sl = gc.get_shared_links(set(['HGNC:869','HGNC:870']), 'gene')
    nodes_type_list: dict = {}
    sl = gc.get_shared_links(set(['NCBIGene:538','NCBIGene:540']), 'gene', nodes_type_list)
    #Because we only had a pair of inputs, we should only get a single output.
    assert len(sl) == 1
    fams = []
    for value in sl.values():
        for curie,pred,is_source in value:
            if pred == 'part_of':
                assert is_source
                fams.append(curie)
    assert len(fams) > 0
    #may 6, 2020 this is failing b/c of a kg issue
    #assert 'HGNC.FAMILY:1212' in fams
    assert 'PANTHER.FAMILY:PTHR43520' in fams

#Failing due to RK KG problems.  Once HGNC FAMILY is fixed, turn this back on.  CB May 6, 2020
def test_enriched_links():
    """This pair of genes is chosen because they're not connected to much that is connected
    to much, so the test runs quickly.  The downside is that we get an unrealistically
    low number of results, but it doesn't take all day."""
    sl = gc.get_enriched_links(set(['HGNC:4295', 'HGNC:23263']), 'gene')
    assert sl[0][1] == 'HGNC.FAMILY:568'

#Failing due to RK KG problems.  Once HGNC FAMILY is fixed, turn this back on.  CB May 6, 2020
def test_enriched_links_hg():
    """This set of genes is chosen because it runs quickly"""
    sl = gc.get_enriched_links(set(['HGNC:44283', 'HGNC:44284','HGNC:44282']), 'gene')
    assert sl[0][1] == 'HGNC.FAMILY:1384'
    assert sl[0][5] == 5

#Failing due to RK KG problems.  Once HGNC FAMILY is fixed, turn this back on.  CB May 6, 2020
def test_graph_coalescer():
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
    assert len(p.added_nodes)==1

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

    # loop through the knowledge_graph return and insure that nodes have a type list
    for n in coalesced['knowledge_graph']['nodes']:
        assert(isinstance(n['type'], list))

def test_missing_node_norm():
    from src.single_node_coalescer import coalesce
    import os
    import json
    import datetime

    # get a timestamp
    t1 = datetime.datetime.now()

    # get the path to the test file
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'graph_named_thing_issue.json')

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
