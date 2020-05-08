import src.property_coalescence.property_coalescer as pc
from src.components import Opportunity


def test_disease_props():
    #this won't work in travis unless we put the db files there.
    #check a disease
    pl = pc.PropertyLookup()
    dprops = pl.lookup_property_by_node('MONDO:0019438','disease')
    #{'nutritional_or_metabolic_disease', 'systemic_or_rheumatic_disease'}
    assert len(dprops) == 2
    assert 'nutritional_or_metabolic_disease' in dprops
    assert 'systemic_or_rheumatic_disease' in dprops
    # check counts
    num = pl.total_nodes_with_property('nutritional_or_metabolic_disease','disease')
    assert num > 100
    zero = pl.total_nodes_with_property('blarney','disease')
    assert zero == 0
    #How many diseases?
    dcount = pl.get_nodecount('disease')
    assert dcount > 20000

def test_get_properties():
    #this won't work in travis unless we put the db files there.
    pl = pc.PropertyLookup()
    #Check a chemical
    props = pl.lookup_property_by_node('CHEBI:64663','chemical_substance')
    #{'allergen', 'aetiopathogenetic_role', 'role', 'biological_role'}
    assert len(props) == 3
    assert 'allergen'in props
    assert 'aetiopathogenetic_role' in props
    assert 'biological_role' in props #also kinda crap...

    #Check an empty
    eprops = pl.lookup_property_by_node('CHEBI:93088','chemical_substance')
    assert len(eprops) == 0

    #This one was failing because multiple old nodes in robokopdb2 were merging to chebi:16856.  And
    # one without properties was tromping the one with properties, so we were getting an empty property list
    # for something that should have lots of properties!
    qprops = pl.lookup_property_by_node('CHEBI:16856','chemical_substance')
    assert len(qprops) > 10
    assert 'biological_role' in qprops

def test_collect_properties():
    """
    Given three nodes, find properties that two or more of them share
    'CHEBI:68299':{'biochemical_role', 'metabolite', 'molecule_type:Small molecule', 'antibacterial_agent',
    'eukaryotic_metabolite', 'antimicrobial_agent', 'biological_role',  'fungal_metabolite'}
    'CHEBI:68075':{'biochemical_role', 'metabolite', 'molecule_type:Small molecule', 'eukaryotic_metabolite',
    'biological_role', 'Penicillium_metabolite', 'fungal_metabolite'}
    'CHEBI:65728':{'biochemical_role', 'metabolite', 'chemical_role', 'donor', 'antibacterial_agent',
    'antimicrobial_agent', 'biological_role', 'acid',  'Bronsted_acid'}
    So 'biochemical_role':all 3
    'metabolite': all 3
    'molecule_type:Small molecule': 1&2
    'antibacterial_agent': 1&3
    'eukaryotic_metabolite: 1&2
    'antimicrobial_agent': 1 & 3
    'biological_role': all 3
    'fungal_metabolite': 1&2
    'Penicilluim_metabolite': only in 2, so should not show up
    'chemical_role': only in 3, so should not show up
    'donor': only in 3, so should not show up
    'acid': only in 3, so should not show up
    'Bronsted_acid': only in 3, so should not show up
    """
    pl = pc.PropertyLookup()
    properties = pl.collect_properties(['CHEBI:68299', 'CHEBI:68075', 'CHEBI:65728'],'chemical_substance')
    assert len(properties['metabolite']) == 3
    assert len(properties['biochemical_role']) == 3
    assert len(properties['biological_role']) == 3
    assert len(properties['molecule_type:Small molecule']) == 2
    assert len(properties['antibacterial_agent']) == 2
    assert len(properties['antimicrobial_agent']) == 2
    assert len(properties['eukaryotic_metabolite']) == 2
    assert len(properties['fungal_metabolite']) == 2
    assert len(properties) == 8

def test_property_enrichment():
    """
    Check our enrichment calculations.
    These chemicals are all known to contribute to FA
    2/3 are mutagens, genotoxins, and aetiopathogenetic_role
    """
    inputs = ['CHEBI:23704', 'CHEBI:16856', 'CHEBI:28901']
    results = pc.get_enriched_properties(inputs,'chemical_substance')
    assert len(results) == 3
    assert results[0][1] == 'mutagen'
    assert results[1][1] == 'genotoxin'
    assert results[2][1] == 'aetiopathogenetic_role'

def test_disease_property_enrichment():
    """
    Check our enrichment calculations.
    """
    inputs = ['MONDO:0010563', 'MONDO:0010379', 'MONDO:0021019']
    results = pc.get_enriched_properties(inputs, 'disease')
    assert len(results) == 2
    assert results[0][1] == 'X_linked_recessive_disease'
    assert results[1][1] == 'X_linked_disease'

def test_property_coalsecer():
    curies = ['CHEBI:23704', 'CHEBI:16856', 'CHEBI:28901']
    opportunity = Opportunity('hash',('qg_0','chemical_substance'),curies,[0,1,2])
    opportunities=[opportunity]
    patches = pc.coalesce_by_property(opportunities)
    assert len(patches) == 1
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    p = patches[0]
    assert p.qg_id == 'qg_0'
    assert len(p.set_curies) == 2 # 2 of the 3 curies have the identified properties
    assert p.new_props['coalescence_method'] == 'property_enrichment'
    assert p.new_props['p_values'][0] < 1e-4
    assert len(p.new_props['p_values']) == 3
    assert p.new_props['properties'][2] == 'aetiopathogenetic_role'

def test_property_coalescer_perf_test():
    from src.single_node_coalescer import coalesce
    import os
    import json
    import datetime

    # get a timestamp
    t1 = datetime.datetime.now()

    # get the path to the test file
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'EdgeIDAsStrAndPerfTest.json')

    # open the file and load it
    with open(test_filename,'r') as tf:
        incoming = json.load(tf)

    # call function that does property coalesce
    coalesced = coalesce(incoming, method='property')

    # get the amount of time it took
    diff = datetime.datetime.now() - t1

    # it should be less than this
    assert(diff.seconds < 60)

    # loop through the query_graph return and insure that edge ids are strs
    for n in coalesced['query_graph']['edges']:
        assert(isinstance(n['id'], str))

    # loop through the knowledge_graph return and insure that edge ids are strs
    for n in coalesced['knowledge_graph']['edges']:
        assert(isinstance(n['id'], str))



