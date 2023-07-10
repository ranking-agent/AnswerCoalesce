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

def test_double_check_enrichment():
    """Make sure that the patches length == auxiliary graph length."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_with_workflow.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert answerset.get('workflow')
        assert PDResponse.parse_obj(answerset)
    answerset = answerset['message']
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph', coalesce_threshold=None)
    # Must be at least the length of the initial answers
    assert len(newset['results']) == len(answerset['results'])
    opportunities = snc.identify_coalescent_nodes(answerset)
    patches = gc.coalesce_by_graph(opportunities)
    #There is at least one enriched result for each patch in the patches
    assert len(patches) == len(newset['auxiliary_graphs']) # 18

def test_graph_coalesce_qualified():
    """Make sure that results are well formed."""
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
    newset = snc.coalesce(answerset, method='graph')
    assert PDResponse.parse_obj({'message': newset})
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

def test_graph_coalesce_creative():
    """Make sure that results are well formed."""
    #chem_ids = ["MESH:C034206", "PUBCHEM.COMPOUND:2336", "PUBCHEM.COMPOUND:2723949", "PUBCHEM.COMPOUND:24823"]
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'qualifiedcreative.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    #Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid,_ in answerset['knowledge_graph']['edges'].items()])
    #now generate new answers
    newset = snc.coalesce(answerset, method='graph')
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


def test_graph_coalesce_with_pred_exclude():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_pred_exclude.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        assert answerset['workflow'][0].get("parameters").get('predicates_to_exclude')
        predicates_to_exclude = answerset['workflow'][0].get('predicates_to_exclude', None)
        answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph', predicates_to_exclude=predicates_to_exclude)
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
        extra_node = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_node = True
            # Every node binding should be found somewhere in the kg nodes
            for nb in nbk:
                assert nb['id'] in kgnodes
                # And each of these nodes should have a name
                assert 'name' in newset['knowledge_graph']['nodes'][nb['id']]
        # We are no longer updating the qgraph.
        #        assert extra_node
        # make sure each new result has an extra edge
        ebs = r['analyses'][0]['edge_bindings']
        extra_edge = False
        for qg_id, ebk in ebs.items():
            # check that the edges have the provenance we need
            # Every node binding should be found somewhere in the kg nodes
            for nb in ebk:
                eedge = kgedges[nb['id']]
                if nb['id'] in original_edge_ids:
                    continue
                try:
                    values = set(flatten([a['value'] for a in eedge['attributes']]))
                except:
                    assert False
                ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                assert len(values.intersection(ac_prov)) == 2
                assert len(values) > len(ac_prov)


def test_graph_coalesce_with_threshold_1():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_threshold_1.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        assert answerset['workflow'][0].get("parameters").get('threshold')
        coalesce_threshold = answerset['workflow'][0].get("parameters").get('threshold')
    answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph', coalesce_threshold=coalesce_threshold)
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
        extra_node = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_node = True
            # Every node binding should be found somewhere in the kg nodes
            for nb in nbk:
                assert nb['id'] in kgnodes
                # And each of these nodes should have a name
                assert 'name' in newset['knowledge_graph']['nodes'][nb['id']]
        # We are no longer updating the qgraph.
        #        assert extra_node
        # make sure each new result has an extra edge
        ebs = r['analyses'][0]['edge_bindings']
        extra_edge = False
        for qg_id, ebk in ebs.items():
            # check that the edges have the provenance we need
            # Every node binding should be found somewhere in the kg nodes
            for nb in ebk:
                eedge = kgedges[nb['id']]
                if nb['id'] in original_edge_ids:
                    continue
                try:
                    values = set(flatten([a['value'] for a in eedge['attributes']]))
                except:
                    assert False
                ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                assert len(values.intersection(ac_prov)) == 2
                assert len(values) > len(ac_prov)


def test_graph_coalesce_with_params_and_pcut():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_with_params_and_pcut.json')
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
    newset = snc.coalesce(answerset, method='graph', predicates_to_exclude=predicates_to_exclude,
                          pcut=pvalue_threshold)
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
        extra_node = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_node = True
            # Every node binding should be found somewhere in the kg nodes
            for nb in nbk:
                assert nb['id'] in kgnodes
                # And each of these nodes should have a name
                assert 'name' in newset['knowledge_graph']['nodes'][nb['id']]
        # We are no longer updating the qgraph.
        #        assert extra_node
        # make sure each new result has an extra edge
        ebs = r['analyses'][0]['edge_bindings']
        extra_edge = False
        for qg_id, ebk in ebs.items():
            # check that the edges have the provenance we need
            # Every node binding should be found somewhere in the kg nodes
            for nb in ebk:
                eedge = kgedges[nb['id']]
                if nb['id'] in original_edge_ids:
                    continue
                try:
                    values = set(flatten([a['value'] for a in eedge['attributes']]))
                except:
                    assert False
                ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                assert len(values.intersection(ac_prov)) == 2
                assert len(values) > len(ac_prov)


def test_graph_coalesce_with_threshold_500():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_threshold_500.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        assert answerset['workflow'][0].get("parameters").get('threshold')
        coalesce_threshold = answerset['workflow'][0].get("parameters").get('threshold')
    answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph', coalesce_threshold=coalesce_threshold)
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
        extra_node = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_node = True
            # Every node binding should be found somewhere in the kg nodes
            for nb in nbk:
                assert nb['id'] in kgnodes
                # And each of these nodes should have a name
                assert 'name' in newset['knowledge_graph']['nodes'][nb['id']]
        # make sure each new result has an extra edge
        ebs = r['analyses'][0]['edge_bindings']
        extra_edge = False
        for qg_id, ebk in ebs.items():
            # check that the edges have the provenance we need
            # Every node binding should be found somewhere in the kg nodes
            for nb in ebk:
                eedge = kgedges[nb['id']]
                if nb['id'] in original_edge_ids:
                    continue
                try:
                    values = set(flatten([a['value'] for a in eedge['attributes']]))
                except:
                    assert False
                ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                assert len(values.intersection(ac_prov)) == 2
                assert len(values) > len(ac_prov)


def test_graph_coalesce_with_params_500():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_with_params.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        assert answerset['workflow'][0].get("parameters").get('threshold')
        assert answerset['workflow'][0].get("parameters").get('predicates_to_exclude')
        coalesce_threshold = answerset['workflow'][0].get('threshold', None)
        predicates_to_exclude = answerset['workflow'][0].get('predicates_to_exclude', None)
    answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph', predicates_to_exclude=predicates_to_exclude,
                          coalesce_threshold=coalesce_threshold)
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
        extra_node = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_node = True
            # Every node binding should be found somewhere in the kg nodes
            for nb in nbk:
                assert nb['id'] in kgnodes
                # And each of these nodes should have a name
                assert 'name' in newset['knowledge_graph']['nodes'][nb['id']]
        # We are no longer updating the qgraph.
        #        assert extra_node
        # make sure each new result has an extra edge
        ebs = r['analyses'][0]['edge_bindings']
        extra_edge = False
        for qg_id, ebk in ebs.items():
            # check that the edges have the provenance we need
            # Every node binding should be found somewhere in the kg nodes
            for nb in ebk:
                eedge = kgedges[nb['id']]
                if nb['id'] in original_edge_ids:
                    continue
                try:
                    values = set(flatten([a['value'] for a in eedge['attributes']]))
                except:
                    assert False
                ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                assert len(values.intersection(ac_prov)) == 2
                assert len(values) > len(ac_prov)


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
