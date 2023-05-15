import pytest
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from src.components import Opportunity,Answer
import os,json

jsondir='InputJson_1.2'

def test_graph_coalescer():
    curies = [ 'NCBIGene:106632262', 'NCBIGene:106632263','NCBIGene:106632261' ]
    opportunity = Opportunity('hash',('qg_0','biolink:Gene'),curies,[0,1,2],{i:[curies[i]] for i in [0,1,2]})
    opportunities=[opportunity]
    patches = gc.coalesce_by_graph(opportunities)
    assert len(patches) == 1
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    p = patches[0]
    assert p.qg_id == 'qg_0'
    assert len(p.set_curies) == 3 # 3 of the 3 curies are subclasses of the output
    atts=p.new_props['attributes']
    kv = { x['original_attribute_name']: x['value'] for x in atts}
    assert kv['coalescence_method'] == 'graph_enrichment'
    assert kv['p_value'] < 1e-10
    assert len(p.added_nodes)==1

def test_graph_coalescer_double_check():
    curies = ['NCBIGene:191',
 'NCBIGene:55832',
 'NCBIGene:645',
 'NCBIGene:54884',
 'NCBIGene:8239',
 'NCBIGene:4175',
 'NCBIGene:10469',
 'NCBIGene:8120',
 'NCBIGene:3840',
 'NCBIGene:55705',
 'NCBIGene:2597',
 'NCBIGene:23066',
 'NCBIGene:7514',
 'NCBIGene:10128']
    cts = [i for i in range(len(curies))]
    opportunity = Opportunity('hash',('qg_0','biolink:Gene'),curies,cts,{i:[curies[i]] for i in cts})
    opportunities=[opportunity]
    patches = gc.coalesce_by_graph(opportunities)
    assert len(patches) == 15
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    p = patches[0]
    assert p.qg_id == 'qg_0'
    #assert len(p.set_curies) == 3 #  Don't really know how many there are.
    atts=p.new_props['attributes']
    kv = { x['original_attribute_name']: x['value'] for x in atts}
    assert kv['coalescence_method'] == 'graph_enrichment'
    assert kv['p_value'] < 1e-10
    assert len(p.added_nodes)==1



def test_graph_coalescer_perf_test():
    from src.single_node_coalescer import coalesce
    import datetime

    # get a timestamp
    t1 = datetime.datetime.now()

    # get the path to the test file
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),jsondir,'EdgeIDAsStrAndPerfTest.json')

    # open the file and load it
    with open(test_filename,'r') as tf:
        incoming = json.load(tf)
        incoming = incoming['message']

    # call function that does property coalesce
    coalesced = coalesce(incoming, method='graph')

    # get the amount of time it took
    diff = datetime.datetime.now() - t1

    # it should be less than this
    assert(diff.seconds < 60)

#Used in test_graph_coalesce to extract values from attributes, which can be a list or a string
def flatten(ll):
    if isinstance(ll, list):
        temp = []
        for ele in ll:
            temp.extend(flatten(ele))
        return temp
    else:
        return [ll]

def test_graph_coalesce_qualified():
    """Make sure that results are well formed."""
    #chem_ids = ["MESH:C034206", "PUBCHEM.COMPOUND:2336", "PUBCHEM.COMPOUND:2723949", "PUBCHEM.COMPOUND:24823"]
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,"InputJson_1.3", 'qualified.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    #Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid,_ in answerset['knowledge_graph']['edges'].items()])
    #now generate new answers
    newset = snc.coalesce(answerset, method='graph', return_original=False)
    kgnodes = set([nid for nid,n in newset['knowledge_graph']['nodes'].items()])
    kgedges = newset['knowledge_graph']['edges']
    extra_edge = False
    for eid,eedge in kgedges.items():
        if eid in original_edge_ids:
            continue
        extra_edge = True
        assert 'qualifiers' in eedge
        for qual in eedge["qualifiers"]:
            assert qual["qualifier_type_id"].startswith("biolink:")
    assert extra_edge



def test_graph_coalesce():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'famcov_new.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    #Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid,_ in answerset['knowledge_graph']['edges'].items()])
    #now generate new answers
    newset = snc.coalesce(answerset, method='graph',return_original=False)
    kgnodes = set([nid for nid,n in newset['knowledge_graph']['nodes'].items()])
    kgedges = newset['knowledge_graph']['edges']
    #Make sure that the edges are properly formed
    for eid, kg_edge in kgedges.items():
        assert isinstance(kg_edge["predicate"],str)
        assert kg_edge["predicate"].startswith("biolink:")
    for r in newset['results']:
        #Make sure each result has at least one extra node binding
        nbs = r['node_bindings']
        extra_node = False
        for qg_id,nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_node = True
            #Every node binding should be found somewhere in the kg nodes
            for nb in nbk:
                assert nb['id'] in kgnodes
                #And each of these nodes should have a name
                assert 'name' in newset['knowledge_graph']['nodes'][nb['id']]
        #We are no longer updating the qgraph.
#        assert extra_node
        #make sure each new result has an extra edge
        nbs = r['edge_bindings']
        extra_edge = False
        for qg_id,nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_edge = True
                #check that the edges have the provenance we need
                #Every node binding should be found somewhere in the kg nodes
                for nb in nbk:
                    eedge = kgedges[nb['id']]
                    if nb['id'] in original_edge_ids:
                        continue
                    keys = [a['attribute_type_id'] for a in eedge['attributes']]
                    try:
                        values = set(flatten([a['value'] for a in eedge['attributes']]))
                    except:
                        print(eedge)
                        assert False
                    ac_prov = set( ['infores:aragorn', 'infores:automat-robokop'] )
                    assert len(values.intersection(ac_prov)) == 2
                    assert len(values) > len(ac_prov)
        #We are no longer updating the qgraph
#        assert extra_edge

def test_graph_coalesce_strider():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir,'strider_relay_mouse.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset, method='graph', return_original=True)
    for r in newset['results']:
        nbs = r['node_bindings']
        extra = False
        for nb in nbs:
            if nb.startswith('extra'):
                extra = True
        assert extra

def xtest_missing_node_norm():
    #removing test to keep link size low`
    from src.single_node_coalescer import coalesce
    import datetime

    # get a timestamp
    t1 = datetime.datetime.now()

    # get the path to the test file
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),jsondir,'graph_named_thing_issue.json')

    # open the file and load it
    with open(test_filename,'r') as tf:
        incoming = json.load(tf)
        incoming = incoming['message']

    # call function that does property coalesce
    coalesced = coalesce(incoming, method='graph')

    # get the amount of time it took
    diff = datetime.datetime.now() - t1

    # it should be less than this
    assert(diff.seconds < 60)


def test_gouper():
    x = 'abcdefghi'
    n = 0
    for group in gc.grouper(3,x):
        x = group
        n += 1
    assert n == 3
    assert x == ('g','h','i')

def test_gouper_keys():
    d = {x:x for x in 'abcdefg'}
    n = 0
    for group in gc.grouper(3, d.keys()):
        x = group
        n += 1
    assert n == 3
    assert x == ('g',)
