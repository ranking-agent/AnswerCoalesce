import pytest
import json
import os
import src.single_node_coalescer as snc

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
    print(a)
    bindings = snc.make_bindings(qg,a)
    print(bindings)
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



