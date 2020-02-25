import pytest
import json
import os
import src.single_node_coalescer as snc


def xtest_one_hop():
    """Load up the answer in robokop_one_hop.json.
    It contains the robokop answer for (chemical_substance)-[contributes_to]->(Asthma).
    If the chemical substance is allowed to vary, every answer should give the same hash."""
    testfilename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'robokop_one_hop.json')
    with open(testfilename,'r') as tf:
        answerset = json.load(tf)
    qg = answerset['question_graph']
    kg = answerset['knowledge_graph']
    answers = answerset['answers']
    s = set()
    for a in answers:
        bindings = { f'n_{qg_id}': kg_id for qg_id, kg_id in a['node_bindings'].items() }
        bindings.update({ f'e_{qg_id}': kg_id for qg_id, kg_id in a['edge_bindings'].items() } )
        s.add(snc.make_answer_hash(bindings,kg,qg,'n0'))
    assert len(s) == 1

