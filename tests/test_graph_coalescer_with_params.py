import pytest
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from src.components import Opportunity, Answer
import os, json

jsondir = 'InputJson_1.2'
jsondir2 = 'InputJson_1.3'

#Used in test_graph_coalesce to extract values from attributes, which can be a list or a string
def flatten(ll):
    if isinstance(ll, list):
        temp = []
        for ele in ll:
            temp.extend(flatten(ele))
        return temp
    else:
        return [ll]


def test_graph_coalesce_without_params():
    """
        Accepts a trapi1.3 formatted json with or without additional parameters like:
                Coalesce_threshold
                Predicates_to_exclude
       Uses line 57 to check the length of the final result set
       Subsequent lines make sure that results are well-formed.
    """
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir2, 'alzh_trapi_no_params.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']

    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph',  return_original=True)
    assert len(newset['results']) == len(answerset['results'])*2

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
        nbs = r['edge_bindings']
        extra_edge = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_edge = True
                # check that the edges have the provenance we need
                # Every node binding should be found somewhere in the kg nodes
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
                    ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                    assert len(values.intersection(ac_prov)) == 2
                    assert len(values) > len(ac_prov)
        # We are no longer updating the qgraph


def test_graph_coalesce_only_threshold_1():
    """
        Accepts a trapi1.3 formatted json with additional parameters like:
                Coalesce_threshold: Important
                Predicates_to_exclude: Optional
       Uses line 116 to check if the Important parameter is in the trapi1.3 json
       Uses line 124 to check the length of the final result set
       Subsequent lines make sure that results are well-formed.
    """
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir2, 'alzh_trapi_only_threshold_1.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert answerset['workflow'][0].get('threshold')
        coalesce_threshold = answerset['workflow'][0].get('threshold', None)
        answerset = answerset['message']

    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph',  return_original=True, coalesce_threshold= coalesce_threshold)
    assert len(newset['results']) == len(answerset['results']) + coalesce_threshold

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
        nbs = r['edge_bindings']
        extra_edge = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_edge = True
                # check that the edges have the provenance we need
                # Every node binding should be found somewhere in the kg nodes
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
                    ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                    assert len(values.intersection(ac_prov)) == 2
                    assert len(values) > len(ac_prov)
        # We are no longer updating the qgraph


def test_graph_coalesce_only_pred_exclude():
    """
        Accepts a trapi1.3 formatted json with additional parameters like:
                Coalesce_threshold: Optional
                Predicates_to_exclude: Important
       Uses line 183 to check if the Important parameter is in the trapi1.3 json
       Uses line 192 to check the length of the final result set
       Subsequent lines make sure that results are well-formed.
    """
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir2, 'alzh_trapi_only_predexclude.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert answerset['workflow'][0].get('predicates_to_exclude')
        predicates_to_exclude = answerset['workflow'][0].get('predicates_to_exclude', None)
        answerset = answerset['message']


    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph',  return_original=True, predicates_to_exclude=predicates_to_exclude)
    assert len(newset['results']) == len(answerset['results'])*2

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
        nbs = r['edge_bindings']
        extra_edge = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_edge = True
                # check that the edges have the provenance we need
                # Every node binding should be found somewhere in the kg nodes
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
                    ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                    assert len(values.intersection(ac_prov)) == 2
                    assert len(values) > len(ac_prov)
        # We are no longer updating the qgraph

#

def test_graph_coalesce_with_params_1():
    """
        Accepts a trapi1.3 formatted json with additional parameters like:
                Coalesce_threshold: Important
                Predicates_to_exclude: Important
       Uses line 252/253 to check if the Important parameter is in the trapi1.3 json
       Uses line 261 to check the length of the final result set
       Subsequent lines make sure that results are well-formed.
    """
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir2, 'alzh_trapi_with_params1.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert answerset['workflow'][0].get('threshold')
        assert answerset['workflow'][0].get('predicates_to_exclude')
        coalesce_threshold = answerset['workflow'][0].get('threshold', None)
        predicates_to_exclude = answerset['workflow'][0].get('predicates_to_exclude', None)
        answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph',  return_original=True, predicates_to_exclude=predicates_to_exclude, coalesce_threshold=coalesce_threshold)
    assert len(newset['results']) == len(answerset['results']) + coalesce_threshold

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
        nbs = r['edge_bindings']
        extra_edge = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_edge = True
                # check that the edges have the provenance we need
                # Every node binding should be found somewhere in the kg nodes
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
                    ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                    assert len(values.intersection(ac_prov)) == 2
                    assert len(values) > len(ac_prov)
        # We are no longer updating the qgraph


def test_graph_coalesce_with_params_500():
    """
        Accepts a trapi1.3 formatted json with additional parameters like:
                Coalesce_threshold: Important
                Predicates_to_exclude: Important
       Uses line 252/253 to check if the Important parameter is in the trapi1.3 json
       Uses line 261 to check the length of the final result set
       Subsequent lines make sure that results are well-formed.
    """
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir2, 'alzh_trapi_with_params500.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert answerset['workflow'][0].get('threshold')
        assert answerset['workflow'][0].get('predicates_to_exclude')
        coalesce_threshold = answerset['workflow'][0].get('threshold', None)
        predicates_to_exclude = answerset['workflow'][0].get('predicates_to_exclude', None)
        answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph',  return_original=True, predicates_to_exclude=predicates_to_exclude, coalesce_threshold=coalesce_threshold)
    assert len(newset['results']) == len(answerset['results']) + coalesce_threshold

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
        nbs = r['edge_bindings']
        extra_edge = False
        for qg_id, nbk in nbs.items():
            if qg_id.startswith('extra'):
                extra_edge = True
                # check that the edges have the provenance we need
                # Every node binding should be found somewhere in the kg nodes
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
                    ac_prov = set(['infores:aragorn', 'infores:automat-robokop'])
                    assert len(values.intersection(ac_prov)) == 2
                    assert len(values) > len(ac_prov)
        # We are no longer updating the qgraph

