import pytest
from copy import deepcopy
import json
import os
import src.single_node_coalescer as snc
from collections import defaultdict
from src.components import PropertyPatch,Answer

def test_bindings():
    """Load up the answer in robokop_one_hop.json.
    It contains the robokop answer for (chemical_substance)-[contributes_to]->(Asthma).
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.0','asthma_one_hop.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['results']
    a = Answer(answers[0],qg,kg)
    bindings = a.make_bindings()
    print(bindings)
    assert len(bindings) == 3 # 2 nodes, 1 edge

def test_hash_one_hop():
    """Load up the answer in robokop_one_hop.json.
    It contains the robokop answer for (chemical_substance)-[contributes_to]->(Asthma).
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.0','asthma_one_hop.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    answers = [Answer(ai,qg,kg) for ai in answerset['results']]
    s = set()
    for a in answers:
        bindings = a.make_bindings()
        s.add(snc.make_answer_hash(bindings,kg,qg,'n0'))
    assert len(s) == 1
    s = set()
    for a in answers:
        bindings = a.make_bindings()
        s.add(snc.make_answer_hash(bindings,kg,qg,'n1'))
    assert len(s) == len(answers)

def test_hash_one_hop_with_different_predicates():
    """Load up the answer in robokop_one_hop_many_pred.json.
    It contains the robokop answer for (chemical_substance)--(Asthma).
    It differs from one_hop.json in that it does not specify the predicate.  Therefore,
    we should end up with as many classes as combinations of predicates when n0 is the variable node
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.0','asthma_one_hop_many_preds.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    answers = [Answer(ai,qg,kg) for ai in answerset['results']]
    s = set()
    #We need to know how many predicate combinations are in the answers.  So a-[type1]-b is one,
    # and a-[type1,type2]-b (two edges between and and b with types type1,type2) is a different one.
    #how many preds in the kg?
    types = { e_id: e['predicate'] for e_id,e in kg['edges'].items()}
    preds = set()
    for result in answerset['results']:
        ebs = result['edge_bindings']
        ps = set()
        for eb_id,eblist in ebs.items():
            #all the qg_id should be e1, but just in case
            if eb_id != 'e1':
                continue
            for eb in eblist:
                et = types[ eb['id'] ]
                if et == 'literature_cooccurence':
                    continue
                ps.add(et)
        predset = frozenset( ps )
        preds.add(predset)
    for a in answers:
        bindings = a.make_bindings()
        s.add(snc.make_answer_hash(bindings,kg,qg,'n0'))
    print(s)
    print(preds)
    assert len(s) == len(preds)
    assert len(s) > 1 #there better be more than one

#out until I can regenerate the question with the new api format
def x_test_hash_topology():
    """This question has a more complicated topology.  There are two gene nodes that never
    change.  The other gene spot varies, and has related process variation.  Most variations
    include only one gene, but there are a couple that include 2"""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.0','robokop_degreaser.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['results']
    s = defaultdict(list)
    for i,a in enumerate(answers):
        bindings = snc.make_bindings(qg,a)
        s[snc.make_answer_hash(bindings,kg,qg,'n7')].append(i)
    nb = 0
    #If n7 is allowed to vary, then we're looking for gene groupings, of which there are 4.
    for b,l in s.items():
        if len(l) > 1:
            nb += 1
    assert nb==4
    t = defaultdict(list)
    for i,a in enumerate(answers):
        bindings = snc.make_bindings(qg,a)
        t[snc.make_answer_hash(bindings,kg,qg,'n3')].append(i)
    nb = 0
    #If n3 is allowed to vary, then we're looking for process gropuings.  There aren't any.
    # There are 2 processes that have more than one gene, but the predicate from gene to
    # chemical is different.
    for b,l in t.items():
        if len(l) > 1:
            nb += 1
    assert nb==0

def make_answer_set():
    # This test is based on a kg that looks like
    #           D
    #         /   \
    #   A - B - E - G
    #     \   X   /     (the X is a path from B-F and one from C-E
    #       C - F
    # And the answers trace al paths from A to G
    # ABEG, ABDG, ABFG, ACFG, ACEG

    #Create the testing KG
    nodenames ='ABCDEFG'
    nodes = {n: {"category":"biolink:NamedThing"} for n in nodenames}
    inputedges = ['AB','AC','BD','BE','BF','CE','CF','DG','EG','FG']
    edges = {e:{ "subject":e[0], "object":e[1], "predicate":"biolink:related_to"} for e in inputedges}
    kg = {'nodes': nodes, 'edges':edges}
    #Create the QG
    qnodes = {'n0':{'id':'A','category':'biolink:NamedThing'},'n1':{'category':'biolink:NamedThing'},
              'n2':{'category':'biolink:NamedThing'},'n3':{'id':'D','category':'biolink:NamedThing'}}
    qedges = {'e0':{'subject':'n0','object':'n1'},
              'e1':{'subject':'n1','object':'n2'},
              'e2':{'subject':'n2','object':'n3'}}
    qg = {'nodes':qnodes, 'edges':qedges}
    ans = ['ABEG','ABDG','ABFG','ACFG','ACEG']
    answers = []
    for i,a in enumerate(ans):
        nb = {f'n{i}': [ {'id': xi} for xi in x] for i,x in enumerate(a)}
        eb = {f'e{i}': [{'id':f'{a[i]}{a[i+1]}'}] for i in range(len(a)-1)}
        assert len(eb) == len(nb) -1
        answers.append( {'node_bindings':nb, 'edge_bindings':eb, 'score': 10-i})
    answerset = {'query_graph': qg, 'knowledge_graph':kg, 'results': answers}
    return answerset

def test_identify_coalescent_nodes():
    # There should be two nodes that can vary: (B,C) and (D,E,F)
    # We should get back for (B,C) 2 hash of A*FG, and A*EG and for (D,E,F) 2 hashes: AB*G, AC*G
    # But for AC*G, the * is limited to E,F
    answerset = make_answer_set()
    groups = snc.identify_coalescent_nodes(answerset)
    #for group in groups:
    #    print(group)
    assert len(groups) == 4
    found = defaultdict(int)
    #for hash,vnode,vvals,ansrs in groups:
    for opp in groups:
            found[ (opp.get_qg_id(),frozenset(opp.get_kg_ids())) ] += 1
    assert found[('n1',frozenset(['B','C']))] == 2
    assert found[('n2',frozenset(['D','E','F']))] == 1
    assert found[('n2',frozenset(['E','F']))] == 1

def test_apply_property_patches():
    answerset = make_answer_set()
    #answers = answerset['results']
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    answers = [Answer(ai,qg,kg) for ai in answerset['results']]
    #Find the opportunity we want to test:
    groups = snc.identify_coalescent_nodes(answerset)
    #for hash,vnode,vvals,ansrs in groups:
    for opp in groups:
        if opp.get_qg_id() == 'n2' and frozenset(opp.get_kg_ids()) == frozenset(['D','E','F']):
            ansrs = opp.get_answer_indices()
            break
    assert len(ansrs) == 3
    #Now pretend that we ran this through some kind of coalescence like a property
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    #get the original kg counts:
    patch = PropertyPatch('n2',['E','F'],{'new1':'test','new2':[1,2,3]},ansrs)
    new_answers,updated_qg,updated_kg = snc.patch_answers(answerset,[patch])
    assert len(new_answers) == 1
    na = new_answers[0]
    node_binding = na['node_bindings']['n2']
    assert len(node_binding) == 2
    nb_kgids = [ nb['id'] for nb in node_binding ]
    assert 'E' in nb_kgids
    assert 'F' in nb_kgids
    for nb in node_binding:
        assert nb['new1'] == 'test'
        assert len(nb['new2']) == 3
    edge_bindings_1 = [n['id'] for n in na['edge_bindings']['e1']]
    edge_bindings_2 = [n['id'] for n in na['edge_bindings']['e2']]
    assert len(edge_bindings_1) == 2
    assert 'BE' in edge_bindings_1
    assert 'BF' in edge_bindings_1
    assert len(edge_bindings_2) == 2
    assert 'EG' in edge_bindings_2
    assert 'FG' in edge_bindings_2

def test_apply_property_patches_add_new_node_that_isnt_new():
    """
    This is like our apply_property_patch_test, but we're going to also add a new node.
    But in a twist, the new node that we're adding is also one of our old nodes.  This is the case,
    e.g. when we do a superclass merge, but the superclass is one of the nodes that we're merging.
    We want to see that this causes a new edge to appear in our kg, which is an is_a edge between
    E and F. We also want to check that this edge makes it into the answer's edge bindings.
    """
    #Maybe it would be more readable to break this into a few different tests.  Same setup but checking different things
    answerset = make_answer_set()
    #answers = answerset['results']
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    assert len(qg['nodes']) == 4
    assert len(qg['edges']) == 3
    answers = [Answer(ai,qg,kg) for ai in answerset['results']]
    #Find the opportunity we want to test:
    groups = snc.identify_coalescent_nodes(answerset)
    #for hash,vnode,vvals,ansrs in groups:
    for opp in groups:
        if opp.get_qg_id() == 'n2' and frozenset(opp.get_kg_ids()) == frozenset(['D','E','F']):
            ansrs = opp.get_answer_indices()
            break
    assert len(ansrs) == 3
    #Now pretend that we ran this through some kind of coalescence like a property
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    #get the original kg counts:
    kg_nodes = deepcopy(kg['nodes'])
    kg_edges = deepcopy(kg['edges'])
    assert len(kg_edges) == 10
    patch = PropertyPatch('n2',['E','F'],{'new1':'test','new2':[1,2,3]},ansrs)
    #This is the new line:
    patch.add_extra_node("E",'biolink:NamedThing','biolink:is_a',newnode_is='target')
    new_answers,updated_qg,updated_kg = snc.patch_answers(answerset,[patch])
    #Did we patch the question correctly?
    assert len(updated_qg['nodes']) == 5 #started as 4
    assert len(updated_qg['edges']) == 4 #started as 3
    #n2 should now be a set in the question
    vnode = updated_qg['nodes']['n2']
    assert vnode['is_set']
    #Don't want to break any of the stuff that was already working...
    assert len(new_answers) == 1
    na = new_answers[0]
    node_binding = na['node_bindings']['n2']
    assert len(node_binding) == 2
    nbids = [nb['id'] for nb in node_binding]
    assert 'E' in nbids
    assert 'F' in nbids
    for nb in node_binding:
        assert nb['new1'] == 'test'
        assert len(nb['new2']) == 3
    #take advantage of node_bindings being a list.  it's a little hinky
    found_extra = False
    for nb_id, nbs in na['node_bindings'].items():
        if nb_id.startswith('extra'):
            found_extra = True
            assert len(nbs) == 1
            assert nbs[0]['id'] == 'E'
    assert found_extra
    #edge bindings
    edge_bindings_1 = [x['id'] for x in na['edge_bindings']['e1'] ]
    edge_bindings_2 = [x['id'] for x in na['edge_bindings']['e2'] ]
    assert len(edge_bindings_1) == 2
    assert 'BE' in edge_bindings_1
    assert 'BF' in edge_bindings_1
    assert len(edge_bindings_2) == 2
    assert 'EG' in edge_bindings_2
    assert 'FG' in edge_bindings_2
    #Now, want to look at what happened to the kg
    updated_kg_nodes = updated_kg['nodes']
    updated_kg_edges = updated_kg['edges']
    assert len(updated_kg_nodes) == len(kg_nodes) #shouldn't add a node
    assert len(updated_kg_edges) == 1 + len(kg_edges) #added 1 is_a edge
    idm = set(kg_edges.keys() )
    found = False
    for eid in updated_kg_edges:
        if eid not in idm:
            new_edge = updated_kg_edges[eid]
            assert new_edge['predicate'] == 'biolink:is_a'
            assert new_edge['subject'] == 'F'
            assert new_edge['object'] == 'E'
            found = True
    assert found
    found_extra_edges = False
    for edge_id, edge_binding in na['edge_bindings'].items():
        if edge_id.startswith('extra'):
            found_extra_edges = True
            assert len(edge_binding)== 1 #is it pointing to the new kg_id edge?
            assert edge_binding[0]['id'] == eid #is it pointing to the new
    assert found_extra_edges
    #edge_bindings_isa = [ x['kg_id'] for x in na[ 'edge_bindings' ] if x['qg_id'] == 'e2' ][0]

def test_round_trip():
    """Load up the answer in robokop_one_hop.json.
    It contains the robokop answer for (chemical_substance)-[contributes_to]->(Asthma).
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.0','asthma_one_hop.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='property')
    qg = json.dumps(newset['query_graph'])
    kg = json.dumps(newset['knowledge_graph'])
    rs = json.dumps(newset['results'])
    newset_json = json.dumps(newset)
    assert True

def test_apply_property_patches_add_two_new_nodes():
    """
    Given our normal pretend graph, add a couple of enrichment nodes, rather than one.
    """
    #Maybe it would be more readable to break this into a few different tests.  Same setup but checking different things
    answerset = make_answer_set()
    #answers = answerset['results']
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    assert len(qg['nodes']) == 4
    assert len(qg['edges']) == 3
    answers = [Answer(ai,qg,kg) for ai in answerset['results']]
    #Find the opportunity we want to test:
    groups = snc.identify_coalescent_nodes(answerset)
    #for hash,vnode,vvals,ansrs in groups:
    for opp in groups:
        if opp.get_qg_id() == 'n2' and frozenset(opp.get_kg_ids()) == frozenset(['D','E','F']):
            ansrs = opp.get_answer_indices()
            break
    assert len(ansrs) == 3
    #Now pretend that we ran this through some kind of coalescence like a property
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    #get the original kg counts:
    kg_nodes = deepcopy(kg['nodes'])
    kg_edges = deepcopy(kg['edges'])
    assert len(kg_edges) == 10
    patch = PropertyPatch('n2',['E','F'],{'new1':'test','new2':[1,2,3]},ansrs)
    #This is the new line:
    patch.add_extra_node("Q",'biolink:NamedThing','biolink:part_of',newnode_is='target')
    patch.add_extra_node("R",'biolink:NamedThing','biolink:interacts_with',newnode_is='source')
    new_answers,updated_qg,updated_kg = snc.patch_answers(answerset,[patch])
    #Did we patch the question correctly?
    assert len(updated_qg['nodes']) == 6 #started as 4
    assert len(updated_qg['edges']) == 5 #started as 3
    #n2 should now be a set in the question
    vnode = updated_qg['nodes']['n2']
    assert vnode['is_set']
    #Don't want to break any of the stuff that was already working...
    assert len(new_answers) == 1
    na = new_answers[0]
    node_binding = na['node_bindings']['n2']
    assert len(node_binding) == 2
    bound_ids = [ nb['id'] for nb in node_binding ]
    assert 'E' in bound_ids
    assert 'F' in bound_ids
    for nb in node_binding:
        assert nb['new1'] == 'test'
        assert len(nb['new2']) == 3
    #take advantage of node_bindings being a list.  it's a little hinky
    found_R = False
    found_Q = False
    for nb_id, nbs in na['node_bindings'].items():
        if nb_id.startswith('extra'):
            assert len(nbs) == 1
            if nbs[0]['id'] == 'R':
                found_R = True
            if nbs[0]['id'] == 'Q':
                found_Q = True
    assert found_R
    assert found_Q
    #edge bindings
    edge_bindings_1 = [ x['id'] for x in na['edge_bindings']['e1'] ]
    edge_bindings_2 = [ x['id'] for x in na['edge_bindings']['e2'] ]
    assert len(edge_bindings_1) == 2
    assert 'BE' in edge_bindings_1
    assert 'BF' in edge_bindings_1
    assert len(edge_bindings_2) == 2
    assert 'EG' in edge_bindings_2
    assert 'FG' in edge_bindings_2
    #Now, want to look at what happened to the kg
    updated_kg_nodes = updated_kg['nodes']
    updated_kg_edges = updated_kg['edges']
    assert len(updated_kg_nodes) == len(kg_nodes)+2
    assert len(updated_kg_edges) == 4 + len(kg_edges) #added 1 is_a edge
    #There should be 2 (E,F)-[part_of]->Q
    # and 2 (E,F)<-[interacts_with]-R
    idm = set( kg_edges.keys() )
    found = False
    countsQ = []
    countsR = []
    for eid in updated_kg_edges:
        if eid not in idm:
            new_edge = updated_kg_edges[eid]
            if new_edge['subject'] == 'R':
                countsR.append(new_edge['object'])
                assert new_edge['predicate'] == 'biolink:interacts_with'
            else:
                assert new_edge['object'] == 'Q'
                countsQ.append(new_edge['subject'])
    assert 'E' in countsQ
    assert 'E' in countsR
    assert 'F' in countsQ
    assert 'F' in countsR

def test_automat_treat_diabetes_properties():
    """Load up the answer in
    It contains the robokop answer for
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    fn = 'mychem_treats_diabetes.json'
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.0',fn)
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='property')
    rs = newset['results']
    assert len(rs) > 10
    assert rs[0]['node_bindings']['n1'][0]['p_values'][0] < 1e-20

#Need to update this json file in line with the new graph
def xtest_automat_asthma_graph():
    """Load up the answer in
    It contains the robokop answer for
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #fn = 'mychem_treats_diabetes.json'
    fn = 'asthma_one_hop.json'
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),fn)
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='graph')
    rs = newset['results']
    assert len(rs) > 2
#    print(rs[0]['node_bindings'])
#    print(rs[1]['node_bindings'])
#    print(rs[2]['node_bindings'])
#    print(rs[3]['node_bindings'])
    assert rs[0]['node_bindings'][0]['p_value'] < 1e-20

def test_unique_ontology():
    fn = 'famcov_new.json'
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.0',fn)
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']
    newset = snc.coalesce(answerset,method='ontology',return_original=False)
    rs = newset['results']
    assert len(rs) <= 4
    #Also, this should have 4 nodes in the query graph.  The original 3 plus the superclass
    qg = newset['query_graph']
    assert len(qg['nodes']) == 4
    #Also, should have 3 edges in the query graph.  The original 2 plus the superclass
    assert len(qg['edges']) == 3

def test_double_predicates():
    # This test is based on a kg that looks like
    #   B
    #  / \
    # A  D
    #  \/
    #  C
    # Except all the edges are doubled (there are 2 predicates between each)

    #Create the testing KG
    nodenames ='ABCD'
    nodes = { n:{"category":"biolink:NamedThing"} for n in nodenames}
    inputedges = ['AB','AC','BD','CD']
    edges = {f'r{e}': {"subject":e[0], "object":e[1], "predicate":"biolink:related_to"} for e in inputedges}
    edges.update({f'a{e}':{ "subject":e[0], "object":e[1], "predicate":"biolink:also_related_to"} for e in inputedges})
    kg = {'nodes': nodes, 'edges':edges}
    #Create the QG
    qnodes = {'n0':{'id':'A','category':'biolink:NamedThing'},'n1':{'category':'biolink:NamedThing'},
              'n2':{'id':'D','category':'biolink:NamedThing'}}
    qedges = {'e0':{'subject':'n0','object':'n1'},
              'e1':{'subject':'n1','object':'n2'}}
    qg = {'nodes':qnodes, 'edges':qedges}
    ans = ['ABD','ACD']
    answers = []
    for i,a in enumerate(ans):
        nb = {f'n{i}': [{'id': x}] for i,x in enumerate(a)}
        eb = {f'e{i}': [{'id':f'r{a[i]}{a[i+1]}'},{'id':f'a{a[i]}{a[i+1]}'}] for i in range(len(a)-1)}
        assert len(eb) == len(nb) -1
        answers.append( {'node_bindings':nb, 'edge_bindings':eb, 'score': 10-i})
    answerset = {'query_graph': qg, 'knowledge_graph':kg, 'results': answers}
    #Now, this answerset should produce 1 single opportunity
    groups = snc.identify_coalescent_nodes(answerset)
    assert len(groups) == 1
    print(groups)
