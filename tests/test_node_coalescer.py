import pytest
import json
import os
import src.single_node_coalescer as snc
from collections import defaultdict

def test_bindings():
    """Load up the answer in robokop_one_hop.json.
    It contains the robokop answer for (chemical_substance)-[contributes_to]->(Asthma).
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'robokop_one_hop.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
    qg = answerset['question_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['answers']
    a = answers[0]
    bindings = snc.make_bindings(qg,a)
    assert len(bindings) == 3 # 2 nodes, 1 edge

def test_hash_one_hop():
    """Load up the answer in robokop_one_hop.json.
    It contains the robokop answer for (chemical_substance)-[contributes_to]->(Asthma).
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'robokop_one_hop.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
    qg = answerset['question_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['answers']
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
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'robokop_one_hop_many_pred.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
    qg = answerset['question_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['answers']
    s = set()
    #how many preds in the kg?
    preds = set( [e['type'] for e in kg['edges']])
    for a in answers:
        bindings = snc.make_bindings(qg,a)
        s.add(snc.make_answer_hash(bindings,kg,qg,'n0'))
    assert len(s) == len(preds)
    assert len(s) > 1 #there better be more than one

def test_hash_topology():
    """This question has a more complicated topology.  There are two gene nodes that never
    change.  The other gene spot varies, and has related process variation.  Most variations
    include only one gene, but there are a couple that include 2"""
    #note that this json also contains support edges which are in the edge bindings, but not in the question
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'robokop_degreaser.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
    qg = answerset['question_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['answers']
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

