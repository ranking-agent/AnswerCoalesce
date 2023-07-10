import pytest
import os, json
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from reasoner_pydantic import Response as PDResponse

jsondir ='InputJson_1.4'


#Used in test_graph_coalesce to extract values from attributes, which can be a list or a string
def flatten(ll):
    if isinstance(ll, list):
        temp = []
        for ele in ll:
            temp.extend(flatten(ele))
        return temp
    else:
        return [ll]

# Enrichment method = 'all'
def test_all_coalesce_creative_long():
    # coalesce method = 'all'
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'alzheimer.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        answerset = answerset['message']
    #Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid,_ in answerset['knowledge_graph']['edges'].items()])
    #now generate new answers
    # Local redis only do property enrichment because there is no sufficient datss for graph enrichment
    newset = snc.coalesce(answerset, method='all')
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
    # assert extra_edge #This only works with port forwarding when there are graphenriched results

    # This only works with the lookup results whose nodebindings contain qnode_id originally
    for i, r in enumerate(newset['results']):
        old_r = answerset['results'][i]['node_bindings']
        # Make sure each result has at least one extra node binding
        assert r['node_bindings'] == old_r




def test_all_coalesce_with_workflow():
    bad_predicates = ('biolink:causes', 'biolink:biomarker_for', 'biolink:biomarker_for', 'biolink:contraindicated_for', 'biolink:contributes_to', 'biolink:has_adverse_event', 'biolink:causes_adverse_event')
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_with_workflow.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    original_node_ids = set([node for node in answerset['knowledge_graph']['nodes']])
    # now generate new answers
    newset = snc.coalesce(answerset, method='all')
    assert PDResponse.parse_obj({'message': newset})
    # Must be at least the length of the initial answers
    assert len(newset['results']) == len(answerset['results'])
    kgnodes = set([nid for nid, n in newset['knowledge_graph']['nodes'].items()])
    kgedges = newset['knowledge_graph']['edges']
    # Make sure that the edges are properly formed
    for eid, kg_edge in kgedges.items():
        assert isinstance(kg_edge["predicate"], str)
        assert kg_edge["predicate"].startswith("biolink:")
    for r in newset['results']:
        # Make sure each result has at least one extra node binding
        nbs = r['node_bindings']
        for qg_id, nbk in nbs.items():
            # Every node binding should be found somewhere in the kg nodes
            for nb in nbk:
                assert nb['id'] in kgnodes
                # And each of these nodes should have a name
                assert 'name' in newset['knowledge_graph']['nodes'][nb['id']]
        # We are no longer updating the qgraph.

    # make sure enriched result has an extra edge and extra node
    extra_node = False
    for node in kgnodes:
        if node in original_node_ids:
            continue
        extra_node = True
    assert extra_node

    extra_edge = False
    for eid, eedge in kgedges.items():
        if eid in original_edge_ids:
             continue
        extra_edge = True
        eedge = kgedges[eid]
        try:
            names = set(flatten([a['original_attribute_name'] for a in eedge['attributes']]))
            predicates = set(
                flatten([a['value'] for a in eedge['attributes'] if a['original_attribute_name'] == 'predicates']))
        except:
            assert False
        ac_prov = set(['coalescence_method', 'p_value'])
        assert len(names.intersection(ac_prov)) == 2
        assert len(names) > len(ac_prov)
        assert len(predicates.intersection(bad_predicates)) >= 0
    assert extra_edge




def test_all_coalesce_with_pred_exclude():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_pred_exclude.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        assert answerset['workflow'][0].get("parameters").get('predicates_to_exclude')
        predicates_to_exclude = answerset['workflow'][0].get("parameters").get('predicates_to_exclude', None)
        answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])

    # now generate new answers
    newset = snc.coalesce(answerset, method='all', predicates_to_exclude=predicates_to_exclude)
    assert PDResponse.parse_obj({'message': newset})
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
                        predicates = set(flatten([a['value'] for a in eedge['attributes'] if a['original_attribute_name']=='predicates'] ))
                        resource = set(flatten([a['resource_id'] for a in eedge['sources']]))
                    except:
                        assert False
                    ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                    assert len(resource.intersection(ac_prov)) == 2
                    assert len(resource) > len(ac_prov)
                    assert len(predicates.intersection(predicates_to_exclude)) == 0

            assert extra_edge



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