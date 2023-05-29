import pytest
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from src.components import Opportunity, Answer
import os, json

jsondir = 'InputJson_1.2'


def test_graph_coalescer_perf_test():
    from src.single_node_coalescer import coalesce
    import datetime

    # get a timestamp
    t1 = datetime.datetime.now()

    # get the path to the test file
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)), jsondir, 'EdgeIDAsStrAndPerfTest.json')

    # open the file and load it
    with open(test_filename, 'r') as tf:
        incoming = json.load(tf)
        incoming = incoming['message']

    # call function that does property coalesce
    coalesced = coalesce(incoming, method='graph')

    # get the amount of time it took
    diff = datetime.datetime.now() - t1

    # it should be less than this
    assert (diff.seconds < 60)


# Used in test_graph_coalesce to extract values from attributes, which can be a list or a string
def flatten(ll):
    if isinstance(ll, list):
        temp = []
        for ele in ll:
            temp.extend(flatten(ele))
        return temp
    else:
        return [ll]


def test_graph_coalesce_with_workflow():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_with_workflow.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph', return_original=True)

    # Must be at least the length of the initial answers
    assert len(newset['results']) >= len(answerset['results'])
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


def test_graph_coalesce_with_pred_exclude():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_pred_exclude.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert answerset['workflow'][0].get('predicates_to_exclude')
        predicates_to_exclude = answerset['workflow'][0].get('predicates_to_exclude', None)
        answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph', return_original=True, predicates_to_exclude=predicates_to_exclude)

    # Must be at least the length of the initial answers
    assert len(newset['results']) >= len(answerset['results'])
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


def test_graph_coalesce_with_threshold_1():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_threshold_1.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert answerset['workflow'][0].get('threshold')
        coalesce_threshold = answerset['workflow'][0].get('threshold', None)

    answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph', return_original=True, coalesce_threshold=coalesce_threshold)
    # Must be at least the length of the initial answers
    assert len(newset['results']) >= len(answerset['results'])

    check_opportunity = snc.identify_coalescent_nodes(answerset)
    #There is likely to be at least one result for each opportunity
    assert len(newset['results']) >= len(answerset['results']) + len(check_opportunity)

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

def test_graph_coalesce_with_threshold_500():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_threshold_500.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert answerset['workflow'][0].get('threshold')
        coalesce_threshold = answerset['workflow'][0].get('threshold', None)

    answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph', return_original=True, coalesce_threshold=coalesce_threshold)

    # Must be at least the length of the initial answers
    assert len(newset['results']) >= len(answerset['results'])

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
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_with_params.json')
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
    newset = snc.coalesce(answerset, method='graph', return_original=True, predicates_to_exclude=predicates_to_exclude,
                          coalesce_threshold=coalesce_threshold)

    # Must be at least the length of the initial answers
    assert len(newset['results']) >= len(answerset['results'])
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


def test_gouper():
    x = 'abcdefghi'
    n = 0
    for group in gc.grouper(3, x):
        x = group
        n += 1
    assert n == 3
    assert x == ('g', 'h', 'i')


def test_gouper_keys():
    d = {x: x for x in 'abcdefg'}
    n = 0
    for group in gc.grouper(3, d.keys()):
        x = group
        n += 1
    assert n == 3
    assert x == ('g',)
