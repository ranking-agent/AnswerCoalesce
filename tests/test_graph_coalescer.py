import pytest
import os, json, asyncio
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
#from src.components import Opportunity,Answer
from reasoner_pydantic import Response as PDResponse


jsondir='InputJson_1.5'

def test_get_links_and_predicate_filter():
    """We expect that this UniProt has 28 links.
    1 edge with predicate affects, object_aspect_qualifier activity, and object_direction_qualifier diecreased
    1 edge with in_taxon
    24 with predicate directly_physically_interacts_with"""
    curies = ["UniProtKB:P0C6U8"]
    nodes_to_links = gc.create_nodes_to_links(curies)
    assert len(nodes_to_links) == 1
    # Hand counted
    assert len(nodes_to_links[curies[0]]) == 28

    # Test exclude a single predicate, "biolink:directly_physically_interacts_with"
    constraint = {"predicate": "biolink:directly_physically_interacts_with"}
    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint], predicate_constraint_style='exclude')
    assert len(filtered_nodes_to_links[curies[0]]) == 2

    # Test include a single predicate "biolink:in_taxon"
    constraint = {"predicate": "biolink:in_taxon"}
    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint], predicate_constraint_style='include')
    assert len(filtered_nodes_to_links[curies[0]]) == 1

    # Test include a single constraint with predicate and qualifier
    constraint = {"predicate": "biolink:affects", "object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased"}
    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint], predicate_constraint_style='include')
    assert len(filtered_nodes_to_links[curies[0]]) == 1

    # Test exclude a single constraint with the affects predicate but no qualifier.  Nothing should be excluded b/c the matchs is imperfect
    constraint = {"predicate": "biolink:affects"}
    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint], predicate_constraint_style='include')
    assert len(filtered_nodes_to_links[curies[0]]) == 0

    # Test exclude multiple constraints, including some that are not present at all
    constraint1 = {"predicate": "biolink:affects", "object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased"}
    constraint2 = {"predicate": "biolink:in_taxon"}
    constraint3 = {"predicate": "biolink:related_to"}
    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint1, constraint2, constraint3], predicate_constraint_style='exclude')
    assert len(filtered_nodes_to_links[curies[0]]) == 26


    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint1, constraint2, constraint3],
                                                       predicate_constraint_style='include')
    assert len(filtered_nodes_to_links[curies[0]]) == 2

import pytest
from unittest.mock import MagicMock
from src.graph_coalescence.graph_coalescer import filter_links_by_node_type

def test_filter_links_by_node_type():
    # Mocking the nodes_to_links dictionary
    nodes_to_links = {
        "node1": [("node3", "predicate1", True), ("node4", "predicate2", False)],
        "node2": [("MONDO:0000001", "predicate1", False), ("node5", "predicate3", True)],
    }
    # Mocking the link_node_types dictionary
    link_node_types = {
        "node3": "biolink:Gene",
        "node4": "biolink:SmallMolecule",
        "MONDO:0000001": "biolink:Disease",
        "node5": "biolink:ChemicalEntity",
    }


    # Mocking the node_constraints list
    node_constraints = ["biolink:NamedThing"]
    # Expected output after filtering. The node constraint should let everythign past,
    # but the blocklist should get rid of the MONDO
    expected_output = { "node1": [("node3", "predicate1", True), ("node4", "predicate2", False)],
                        "node2": [("node5", "predicate3", True)] }

    # Call the function with the mocked data and assert the expectation
    result = filter_links_by_node_type(nodes_to_links, node_constraints, link_node_types)
    assert result == expected_output

    # Now try with a different node constraint: Chemical Entity which should remove node1
    node_constraints = ["biolink:ChemicalEntity"]
    expected_output = { "node1": [ ("node4", "predicate2", False)],
                        "node2": [("node5", "predicate3", True)] }

def test_graph_coalescer():
    curies = [ 'NCBIGene:106632262', 'NCBIGene:106632263','NCBIGene:106632261' ]
    enrichments = gc.coalesce_by_graph(curies, 'biolink:Gene' )
    assert len(enrichments) >= 1
    e = enrichments[0]
    assert len(e.linked_curies) == 3 # 3 of the 3 curies are subclasses of the output
    #TODO: add attribute testing to TRAPI tests
    #atts=p.new_props['attributes']
    #kv = { x['attribute_type_id']: x['value'] for x in atts}
    #assert kv['biolink:supporting_study_method_type'] == 'graph_enrichment'
    #assert kv['biolink:p_value'] < 1e-10
    assert e.p_value < 1e-10
    assert e.enriched_node.new_curie == "HGNC.FAMILY:1384"

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
    enrichments = gc.coalesce_by_graph(curies, 'biolink:Gene', result_length=100)
    assert len(enrichments) == 100
    e = enrichments[0]
    assert e.p_value < 1e-10

def test_graph_coalescer_perf_test():
    # Two opprtunities but,
    #       Zero patches in both old and new implementations
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
    coalesced = asyncio.run(coalesce(incoming, method='graph'))
    assert PDResponse.parse_obj({'message': coalesced})
    # get the amount of time it took
    diff = datetime.datetime.now() - t1

    # it should be less than this
    assert(diff.seconds < 60)

def test_graph_coalesce_with_params_1e7():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_with_params_and_pcut1e7.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        assert answerset['workflow'][0].get("parameters").get('pvalue_threshold')
        assert answerset['workflow'][0].get("parameters").get('predicates_to_exclude')
        pvalue_threshold = answerset['workflow'][0].get("parameters").get('pvalue_threshold')
        predicates_to_exclude = answerset['workflow'][0].get("parameters").get('predicates_to_exclude')
    answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = asyncio.run(snc.coalesce(answerset, method='graph', predicates_to_exclude=predicates_to_exclude,
                          pvalue_threshold=pvalue_threshold))
    # Must be at least the length of the initial answers
    assert len(newset['results']) == len(answerset['results'])
    kgnodes = set([nid for nid, n in newset['knowledge_graph']['nodes'].items()])
    kgedges = newset['knowledge_graph']['edges']
    # Make sure that the edges are properly formed
    for eid, kg_edge in kgedges.items():
        assert isinstance(kg_edge["predicate"], str)
        assert kg_edge["predicate"].startswith("biolink:")
    for r in newset['results']:
        nbs = r['node_bindings']
        for qg_id, nbk in nbs.items():
            # Every node binding should be found somewhere in the kg nodes
            for nb in nbk:
                assert nb['id'] in kgnodes
                # And each of these nodes should have a name
                assert 'name' in newset['knowledge_graph']['nodes'][nb['id']]

        # make sure each new result has an extra edge
        ebs = r['enrichments']
        # make sure each enriched result has an extra edge
        if ebs:
            # check that the edges have the provenance we need
            # Every node binding should be found somewhere in the kg nodes
            for eb in ebs:
                e_bindings = newset['auxiliary_graphs'][eb]
                pvalue = set([a['value'] for a in e_bindings['attributes'] if a['attribute_type_id']== 'biolink:p_value'])
                assert (pvalue!=1e-06)
                eb_edges = e_bindings['edges']
                for eid in eb_edges:
                    if eid in original_edge_ids:
                        continue
                    extra_edge = True
                    eedge = kgedges[eid]
                    try:
                        resource = set(flatten([a['resource_id'] for a in eedge['sources']]))
                    except:
                        assert False
                    ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                    if resource:
                        assert len(resource.intersection(ac_prov)) == 2
                        assert len(resource) > len(ac_prov)
                    assert len(set(eedge['predicate']).intersection(set(predicates_to_exclude))) == 0
            assert extra_edge

def test_graph_coalesce_qualified():
    """Make sure that results are well formed."""
    # 4 new results binding with 4 dummies
    #chem_ids = ["MESH:C034206", "PUBCHEM.COMPOUND:2336", "PUBCHEM.COMPOUND:2723949", "PUBCHEM.COMPOUND:24823"]
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'qualified.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        answerset = answerset['message']

    #Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid,_ in answerset['knowledge_graph']['edges'].items()])
    #now generate new answers
    newset = asyncio.run(snc.coalesce(answerset, method='graph'))

    assert PDResponse.parse_obj({'message':newset})
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

def test_cvs_isopropyl():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'cvs_iso.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        answerset = answerset['message']
    #now generate new answers
    newset = asyncio.run(snc.coalesce(answerset, method='graph', pvalue_threshold=0.1))
    assert newset

def test_graph_coalesce():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir, 'famcov_new.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        answerset = answerset['message']
    #Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid,_ in answerset['knowledge_graph']['edges'].items()])
    original_node_ids = set([node for node in answerset['knowledge_graph']['nodes']])
    #now generate new answers
    newset = asyncio.run(snc.coalesce(answerset, method='graph'))
    assert PDResponse.parse_obj({'message': newset})
    kgnodes = set([nid for nid,n in newset['knowledge_graph']['nodes'].items()])
    kgedges = newset['knowledge_graph']['edges']
    #Make sure that the edges are properly formed
    for eid, kg_edge in kgedges.items():
        assert isinstance(kg_edge["predicate"],str)
        assert kg_edge["predicate"].startswith("biolink:")

    for r in newset['results']:
        #Make sure each result has at least one extra node binding
        nbs = r['node_bindings']
        # We are no longer including the enriched node in the node binding some of the following is not necessary
        for qg_id,nbk in nbs.items():
            #Every node binding should be found somewhere in the kg nodes
            for nb in nbk:
                assert nb['id'] in kgnodes
                #And each of these nodes should have a name
                assert 'name' in newset['knowledge_graph']['nodes'][nb['id']]
        #We are no longer updating the qgraph.
        #make sure each new result has an extra edge
        ebs = r['enrichments']
        # make sure each enriched result has an extra edge
        if ebs:
            # check that the edges have the provenance we need
            # Every node binding should be found somewhere in the kg nodes
            for eb in ebs:
                e_bindings = newset['auxiliary_graphs'][eb]
                eb_edges = e_bindings['edges']
                for eid in eb_edges:
                    if eid in original_edge_ids:
                        continue
                    extra_edge = True
                    eedge = kgedges[eid]
                    try:
                        resource = set(flatten([a['resource_id'] for a in eedge['sources']]))
                    except:
                        pass
                    if resource:
                        ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                        assert len(resource.intersection(ac_prov)) == 2
                        assert len(resource) > len(ac_prov)

            assert extra_edge

def test_graph_coalesce_strider():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,jsondir,'strider_relay_mouse.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        # Note: Assert PDResponse cannot work here since the categories are depicted as :
        # "categories": ["biolink:C", "biolink:H",...]
        answerset = answerset['message']
    newset = asyncio.run(snc.coalesce(answerset, method='graph'))
    #  Opportunities(5) contain nodes that we dont have links for, so they were filtered out and the patches =[]
    print(newset)

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

#Used in test_graph_coalesce to extract values from attributes, which can be a list or a string
def flatten(ll):
    if isinstance(ll, list):
        temp = []
        for ele in ll:
            temp.extend(flatten(ele))
        return temp
    else:
        return [ll]
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


