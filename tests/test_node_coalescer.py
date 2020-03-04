import pytest
import json
import os
import src.single_node_coalescer as snc
from collections import defaultdict
from src.components import PropertyPatch

def test_bindings():
    """Load up the answer in robokop_one_hop.json.
    It contains the robokop answer for (chemical_substance)-[contributes_to]->(Asthma).
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'asthma_one_hop.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['results']
    a = answers[0]
    bindings = snc.make_bindings(qg,a)
    print(bindings)
    assert len(bindings) == 3 # 2 nodes, 1 edge

def test_hash_one_hop():
    """Load up the answer in robokop_one_hop.json.
    It contains the robokop answer for (chemical_substance)-[contributes_to]->(Asthma).
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'asthma_one_hop.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['results']
    s = set()
    for a in answers:
        bindings = snc.make_bindings(qg,a)
        s.add(snc.make_answer_hash(bindings,kg,qg,'n0'))
    assert len(s) == 1
    s = set()
    for a in answers:
        bindings = snc.make_bindings(qg,a)
        s.add(snc.make_answer_hash(bindings,kg,qg,'n1'))
    assert len(s) == len(answers)

def test_hash_one_hop_with_different_predicates():
    """Load up the answer in robokop_one_hop_many_pred.json.
    It contains the robokop answer for (chemical_substance)--(Asthma).
    It differs from one_hop.json in that it does not specify the predicate.  Therefore,
    we should end up with as many classes as predicates when n0 is the variable node
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'asthma_one_hop_many_preds.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['results']
    s = set()
    #how many preds in the kg?
    preds = set( [e['type'] for e in kg['edges']])
    preds.remove('literature_co-occurrence') #omnicorp edges not part of our mapping
    for a in answers:
        bindings = snc.make_bindings(qg,a)
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
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'robokop_degreaser.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
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
    nodes = [{"id":n, "type":"named_thing"} for n in nodenames]
    inputedges = ['AB','AC','BD','BE','BF','CE','CF','DG','EG','FG']
    edges = [{"id":e, "source_id":e[0], "target_id":e[1], "type":"related_to"} for e in inputedges]
    kg = {'nodes': nodes, 'edges':edges}
    #Create the QG
    qnodes = [{'id':'n0','curie':'A','type':'named_thing'},{'id':'n1','type':'named_thing'},
              {'id':'n2','type':'named_thing'},{'id':'n3','curie':'D','type':'named_thing'}]
    qedges = [{'id':'e0','source_id':'n0','target_id':'n1'},
              {'id':'e1','source_id':'n1','target_id':'n2'},
              {'id':'e2','source_id':'n2','target_id':'n3'}]
    qg = {'nodes':qnodes, 'edges':qedges}
    ans = ['ABEG','ABDG','ABFG','ACFG','ACEG']
    answers = []
    for a in ans:
        #These are for the old-style (robokop) bindings:
        #nb =  {f'n{i}':list(x) for i,x in enumerate(a) }
        #eb =  {f'e{i}':[f'{a[i]}{a[i+1]}'] for i in range(len(a)-1) }
        #These are the new-style (messenger) bindings:
        nb = [{'qg_id':f'n{i}', 'kg_id': list(x)} for i,x in enumerate(a)]
        eb = [{'qg_id':f'e{i}', 'kg_id':[f'{a[i]}{a[i+1]}']} for i in range(len(a)-1)]
        assert len(eb) == len(nb) -1
        answers.append( {'node_bindings':nb, 'edge_bindings':eb})
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
    answers = answerset['results']
    #Find the opportunity we want to test:
    groups = snc.identify_coalescent_nodes(answerset)
    #for hash,vnode,vvals,ansrs in groups:
    for opp in groups:
        if opp.get_qg_id() == 'n2' and frozenset(opp.get_kg_ids()) == frozenset(['D','E','F']):
            ansrs = opp.get_answer_indices()
            break
    #Now pretend that we ran this through some kind of coalescence like a property
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    patch = PropertyPatch('n2',['E','F'],{'new1':'test','new2':[1,2,3]},ansrs)
    new_answers = snc.patch_answers(answers,[patch])
    assert len(new_answers) == 1
    na = new_answers[0]
    node_binding = [ x for x in na[ 'node_bindings' ] if x['qg_id'] == 'n2' ][0]
    assert len(node_binding['kg_id']) == 2
    assert 'E' in node_binding[ 'kg_id' ]
    assert 'F' in node_binding[ 'kg_id' ]
    assert node_binding['new1'] == 'test'
    assert len(node_binding['new2']) == 3
    edge_bindings_1 = [ x['kg_id'] for x in na[ 'edge_bindings' ] if x['qg_id'] == 'e1' ][0]
    edge_bindings_2 = [ x['kg_id'] for x in na[ 'edge_bindings' ] if x['qg_id'] == 'e2' ][0]
    assert len(edge_bindings_1) == 2
    assert 'BE' in edge_bindings_1
    assert 'BF' in edge_bindings_1
    assert len(edge_bindings_2) == 2
    assert 'EG' in edge_bindings_2
    assert 'FG' in edge_bindings_2


