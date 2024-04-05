import pytest
import os, json
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from reasoner_pydantic import Response as PDResponse

jsondir ='InputJson_1.4'

def set_workflowparams(lookup_results):
    # Dummy parameters to check igf reasoner pydantic accepts the new parameters
    return lookup_results.update({"workflow": [
        {
            "id": "enrich_results",
            "parameters":
            {
                "predicates_to_exclude": ["biolink:causes", "biolink:biomarker_for", "biolink:biomarker_for", "biolink:contraindicated_for",
                    "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"],
                "properties_to_exclude": ["CHEBI_ROLE_drug", 'CHEBI_ROLE_pharmaceutical', 'CHEBI_ROLE_pharmacological_role'],
                "nodesets_to_exclude": ["MONDO:0001", 'MONDO:00002']
            }
        }
    ]})

import requests
common_diseasesdir = 'CommonDiseases'
def xtest_all_ui_message():
    # Uncomment this part to fetch the message from ars
    # dir_path = os.path.dirname(os.path.realpath(__file__))
    # name = 'Cystic-Fibrosis'
    # req = requests.get("https://ars.test.transltr.io/ars/api/messages/7da3fb74-de99-42fc-aaa2-e45ee4be1114")
    # answerset = req.json()['fields']['data']
    #
    # with open(dir_path+'/'+common_diseasesdir+'/'+name+'.json', 'w') as qw:  #saves the file
    #     qw.write(json.dumps({'message': answerset}, indent=4))

    # OR Uncomment this part to load message from directory
    name = 'hyperlipidemia.json'
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, common_diseasesdir, name)
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']

    # set_workflowparams(answerset)
    predicates_to_exclude = None
    pvalue_threshold = None
    properties_to_exclude = None
    if 'workflow' in answerset and 'parameters' in answerset['workflow'][0]:
        pvalue_threshold = answerset.get('workflow')[0].get('parameters').get('pvalue_threshold', 0)
        predicates_to_exclude = answerset.get('workflow')[0].get('parameters').get('predicates_to_exclude', None)
        properties_to_exclude = answerset.get('workflow', [])[0].get('parameters').get('properties_to_exclude', None)

    answerset = answerset['message']
    # These edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid, _ in answerset['knowledge_graph']['edges'].items()])

    print(f'\n==Coalesce for{name}===')
    #now generate new answers
    # Local redis only do property enrichment because there is no sufficient datss for graph enrichment
    newset = snc.coalesce(answerset, method='all', predicates_to_exclude= predicates_to_exclude, properties_to_exclude=properties_to_exclude, pvalue_threshold=pvalue_threshold)

    assert PDResponse.parse_obj({'message': newset})
    with open(dir_path+'/'+common_diseasesdir+'/ac_results/'+name.split('.')[0]+'_output.json', 'w') as qw:
        qw.write(json.dumps({'message': newset}, indent=4))

    kgedges = newset['knowledge_graph']['edges']
    extra_edge = False
    for eid, eedge in kgedges.items():
        if eid in original_edge_ids:
            continue
        extra_edge = True
        if 'qualifiers' in eedge:
            for qual in eedge["qualifiers"]:
                assert qual["qualifier_type_id"].startswith("biolink:")
        assert extra_edge #This only works with port forwarding when there are graphenriched results


def flatten(ll):
    if isinstance(ll, list):
        temp = []
        for ele in ll:
            temp.extend(flatten(ele))
        return temp
    else:
        return [ll]

def xtest_all_coalesce_creative_long():
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'alzheimer.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
    assert PDResponse.parse_obj(answerset)
    answerset = answerset['message']
    #Some of these edges are old, we need to know which ones...
    original_edge_ids = set([eid for eid,_ in answerset['knowledge_graph']['edges'].items()])
    #now generate new answers
    newset = snc.coalesce(answerset, method='graph')
    assert PDResponse.parse_obj({'message':newset})
    kgedges = newset['knowledge_graph']['edges']
    for _ ,eedge in kgedges.items():
        if 'qualifiers' in eedge:
            for qual in eedge["qualifiers"]:
                assert qual["qualifier_type_id"].startswith("biolink:")

    # This only works with the lookup results whose nodebindings contain qnode_id originally
    for i, r in enumerate(newset['results']):
        old_r = answerset['results'][i]['node_bindings']
        # Make sure each result has at least one extra node binding
        assert r['node_bindings'] == old_r

def test_all_coalesce_with_workflow():
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
            sources = set(flatten([a['resource_id'] for a in eedge['sources']]))
            ac_sour = set(['infores:automat-robokop'])
            assert len(ac_sour.intersection(sources)) == 1
        except:
            pass
    assert extra_edge

def test_all_coalesce_with_pred_exclude():
    bad_predicates = ["biolink:causes", "biolink:biomarker_for", "biolink:biomarker_for", "biolink:contraindicated_for",
                      "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"]
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_pred_exclude.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        assert answerset['workflow'][0].get("parameters").get('predicates_to_exclude')
        predicates_to_exclude = answerset['workflow'][0].get("parameters").get('predicates_to_exclude', None)
        answerset = answerset['message']

    # now generate new answers
    newset = snc.coalesce(answerset, method='all', predicates_to_exclude=predicates_to_exclude)
    assert PDResponse.parse_obj({'message': newset})
    # Must be at least the length of the initial answers
    assert len(newset['results']) == len(answerset['results'])
    aux_graphs  = newset.get('auxiliary_graphs', {})
    if aux_graphs:
        for aux_g_id, aux_g_data in aux_graphs.items():
            if 'n_ac' in aux_g_id:
                continue
            for attr in aux_g_data['attributes']:
                if attr['attribute_type_id'] == 'biolink:predicate':
                    assert attr['value'] not in bad_predicates
    for r in newset['results']:
        enr = r['enrichments']
        if enr:
            # make sure enriched id exists in the aux_graphs
            assert set(aux_graphs.keys()).intersection(enr) != 0

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
