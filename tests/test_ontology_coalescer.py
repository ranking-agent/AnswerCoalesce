import os
import json

import src.ontology_coalescence.ontology_coalescer as oc
from src.single_node_coalescer import identify_coalescent_nodes
from src.components import Opportunity,Answer

def test_shared_superclass():
    """Check that FA is a shared superclass of FA type A and FA type J"""
    sc = oc.get_shared_superclasses(set(['MONDO:0009215','MONDO:0012187']),'MONDO')
    assert len(sc) == 1
    for k,v in sc.items():
        assert len(k) == 2
        assert 'MONDO:0019391' in v

#These tests are all based on the following subset of MONDO.  There are other terms in this hierarchy but not shown
# 771 Allergic Resperatory Disease
#   4784 Allergic Asthma
#     25556 Isocyanate induced asthma
#   4553 External Allergic Alveolitis
#     5668 Bird fanciers lung
#     5865 Mushroom workers lung
#   0017853 Hypersensitivy Pneumonitis
#     4584  Maple bark stripper's lung

def test_shared_superclass_2():
    """closest common super is 771"""
    sc = oc.get_shared_superclasses(set(['MONDO:0025556','MONDO:0004584']),'MONDO')
    assert len(sc) == 1
    for k,v in sc.items():
        assert len(k) == 2
        assert 'MONDO:0000771' in v

def test_shared_superclass_3():
    """If the shared superclass is in the list we should still return it.  From the
    bit of ontology listed above, there should be only one result. But, there's another
    way that 25556 and 4584 can have a superclass through anatomical groupings."""
    sc = oc.get_shared_superclasses(set(['MONDO:0025556','MONDO:0004584','MONDO:0000771']),'MONDO')
    print(sc)
    assert len(sc) == 2
    for k,v in sc.items():
        if len(k) == 3:
            assert 'MONDO:0000771' in v

def test_shared_superclass_subsets():
    """The first two ids have a direct superclass of 4553, but to get the last one we have to go up to 771"""
    sc = oc.get_shared_superclasses(set(['MONDO:0005668','MONDO:0005865','MONDO:0025556']),'MONDO')
    assert len(sc) == 2
    for k,v in sc.items():
        if len(k) == 3:
            assert 'MONDO:0000771' in v
        if len(k) == 2:
            assert 'MONDO:0004553' in v
    keylens = [ len(k) for k in sc.keys() ]
    assert 2 in keylens
    assert 3 in keylens

def test_get_enriched_supers():
    sc = oc.get_enriched_superclasses(set(['MONDO:0025556','MONDO:0004584','MONDO:0000771']),'disease')
    assert len(sc) == 1
    #The other two are both subclasses of 0000771, so the most enrichment will be for that node
    for v in sc:
        assert v[1] == 'MONDO:0000771'
        assert len(v[5]) == 3

def test_get_enriched_supers_multiple_results():
    sc = oc.get_enriched_superclasses(set(['MONDO:0005668','MONDO:0005865','MONDO:0025556']),'disease')
    assert len(sc) == 2
    #The other two are both subclasses of 0000771, so the most enrichment will be for that node
    for v in sc:
        if len(v[5]) == 3:
            assert v[1] == 'MONDO:0000771'
        if len(v[5]) == 2:
            assert v[1] == 'MONDO:0004553'
    vcounts = [len(v[5]) for v in sc]
    assert 3 in vcounts
    assert 2 in vcounts



def test_ontology_coalescer():
    curies = [ 'MONDO:0025556', 'MONDO:0004584', 'MONDO:0000771' ]
    opportunity = Opportunity('hash',('qg_0','disease'),curies,[0,1,2])
    opportunities=[opportunity]
    patches = oc.coalesce_by_ontology(opportunities)
    assert len(patches) == 1
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    p = patches[0]
    assert p.qg_id == 'qg_0'
    assert len(p.set_curies) == 3 # 3 of the 3 curies are subclasses of the output
    assert p.new_props['coalescence_method'] == 'ontology_enrichment'
    assert p.new_props['p_value'] < 1e-4
    assert p.new_props['superclass'] == 'MONDO:0000771'

def test_full_coalesce_no_new_node():
    """Construct a test case that has our favorite mondo indentifiers. The most significant superclass is in the
    original list, so we don't need to add a new node to the kg.  We do need to add a couple of is_a edges though."""
    #This is going to create a KG that looks like:
    #           MONDO:0025556
    #         /               \
    # (start) - MONDO:0004584 - (end)
    #         \               /
    #           MONDO:0000771
    # Question goes (start)-disease-(end)
    # All 3 paths are given as answers
    curies = ['MONDO:0025556', 'MONDO:0004584', 'MONDO:0000771']
    nodes = [{"id":"start", "type":"phenotypic_feature"}, {"id":"end", "type":"phenotypic_feature"}]
    for c in curies:
        nodes.append({'id': c, 'type': 'disease'})
    edges = []
    for si,source in enumerate(curies):
        for ti,target in enumerate(['start','end']):
            edges.append({"id":f'e_{si}_{ti}', "source_id": source, "target_id": target, 'type': 'has_phenotype'})
    kg = {'nodes': nodes, 'edges':edges}
    #Create the QG
    qnodes = [{'id':'n0','curie':'start','type':'phenotypic_feature'},{'id':'n1','type':'disease'},
              {'id':'n2','curie':'end','type':'phenotypic_feature'}]
    qedges = [{'id':'e0','source_id':'n1','target_id':'n0','type':'has_phenotype'},
              {'id':'e1','source_id':'n1','target_id':'n1','type':'has_phenotype'}]
    qg = {'nodes':qnodes, 'edges':qedges}
    results = []
    for i,c in enumerate(curies):
        #These are the new-style (messenger) bindings:
        nb = [{'qg_id':'n0', 'kg_id':'start'},{'qg_id':'n2', 'kg_id':'end'},{'qg_id':'n1', 'kg_id':c}]
        eb = [{'qg_id':'e0', 'kg_id':f'e_{i}_{0}'}, {'qg_id':'e1', 'kg_id':f'e_{i}_{1}'}]
        results.append( {'node_bindings':nb, 'edge_bindings':eb, 'score': 10-i})
    answerset = {'query_graph': qg, 'knowledge_graph':kg, 'results': results}
    opps =  identify_coalescent_nodes(answerset)
    assert len(opps) == 1
    patches = oc.coalesce_by_ontology(opps)
    assert len(patches) == 1
    patch = patches[0]
    answers = [ Answer(r,qg,kg) for r in results]
    new_answer,updated_qg,updated_kg = patch.apply(answers,qg,kg)
    #I want to see that we've updated the kg to include is_a edges.
    is_a_curies = []
    for edge in kg['edges']:
        if edge['target_id'] == 'MONDO:0000771' and edge['type'] == 'is_a':
            is_a_curies.append(edge['source_id'])
    assert len(is_a_curies) == 2
    assert 'MONDO:0025556' in is_a_curies
    assert 'MONDO:0004584' in is_a_curies
    #print(new_answer.to_json())
    #assert False

def test_unique_coalesce():
    """This test is to fix https://github.com/ranking-agent/AnswerCoalesce/issues/13
    The issue is that the ontology coalescer preoduces non-unique results."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path,  'famcov.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
    opps = identify_coalescent_nodes(answerset)
    #TO check that each of these opportunities is unique, we will check that the
    # kg_ids each identifies are unique
    unique_kg_ids = set()
    for op in opps:
        aggable_identifiers = frozenset(op.kg_ids)
        assert aggable_identifiers not in unique_kg_ids
        unique_kg_ids.add(aggable_identifiers)
    #so we're good at this point, we have  set of unique opportunities.
    patches = oc.coalesce_by_ontology(opps)
    assert len(patches) == 2
    #patch = patches[0]
    #answers = [Answer(r, qg, kg) for r in results]
    #new_answer, updated_qg, updated_kg = patch.apply(answers, qg, kg)
    ## I want to see that we've updated the kg to include is_a edges.
    #is_a_curies = []
    #for edge in kg['edges']:
    #    if edge['target_id'] == 'MONDO:0000771' and edge['type'] == 'is_a':
    #        is_a_curies.append(edge['source_id'])
    #assert len(is_a_curies) == 2
    #assert 'MONDO:0025556' in is_a_curies
    #assert 'MONDO:0004584' in is_a_curies


# print(new_answer.to_json())
# assert False


def test_ontology_coalescer_met():
    curies = ['MONDO:0024388','MONDO:0006604','MONDO:0004235','MONDO:0000705','MONDO:0001028','MONDO:0005316','MONDO:0006989']
    sc = oc.get_enriched_superclasses(set(curies),'disease',pcut=1e-5)
    assert len(sc) > 0
    sc = oc.get_enriched_superclasses(set(curies),'disease',pcut=1e-6)
    assert len(sc) == 0

def test_ontology_coalescer_bogus_prefix():
    curies = ['FAKE:1234','MONDO:0024388','MONDO:0006604','MONDO:0004235','MONDO:0000705','MONDO:0001028','MONDO:0005316','MONDO:0006989']
    sc = oc.get_enriched_superclasses(set(curies),'disease',pcut=1e-5)
    assert len(sc) > 0
