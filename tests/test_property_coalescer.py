import src.property_coalescence.property_coalescer as pc
from src.components import Opportunity


def xtest_disease_props():
    #this won't work in travis unless we put the db files there.
    #check a disease
    pl = pc.PropertyLookup()
    dprops = pl.lookup_property_by_node('MONDO:0019438','biolink:Disease')
    #{'nutritional_or_metabolic_disease', 'systemic_or_rheumatic_disease'}
    assert len(dprops) == 2
    assert 'nutritional_or_metabolic_disease' in dprops
    assert 'systemic_or_rheumatic_disease' in dprops
    # check counts
    num = pl.total_nodes_with_property('nutritional_or_metabolic_disease','biolink:Disease')
    assert num > 100
    zero = pl.total_nodes_with_property('blarney','biolink:Disease')
    assert zero == 0
    #How many diseases?
    dcount = pl.get_nodecount('biolink:Disease')
    assert dcount > 20000

def test_get_properties():
    #this won't work in travis unless we put the db files there.
    pl = pc.PropertyLookup()
    #Check a chemical
    props = pl.lookup_property_by_node('CHEBI:64663','biolink:ChemicalEntity')
    assert len(props) == 2
    assert 'CHEBI_ROLE:allergen'in props
    assert 'CHEBI_ROLE:aetiopathogenetic_role'in props

    #Check an empty
    eprops = pl.lookup_property_by_node('CHEBI:NOTREAL','biolink:ChemicalEntity')
    assert len(eprops) == 0

    #This one was failing because multiple old nodes in robokopdb2 were merging to chebi:16856.  And
    # one without properties was tromping the one with properties, so we were getting an empty property list
    # for something that should have lots of properties!
    qprops = pl.lookup_property_by_node('PUBCHEM.COMPOUND:124886','biolink:ChemicalEntity')
    assert len(qprops) > 5

def test_collect_properties():
    """
    Given three nodes, find properties that two or more of them share
    'CHEBI:68299':{ 'antibacterial_agent',  'fungal_metabolite'}
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
    properties = pl.collect_properties(['CHEMBL.COMPOUND:CHEMBL1765416', 'PUBCHEM.COMPOUND:53355908', 'CHEBI:65728'],'biolink:ChemicalEntity')
    assert len(properties['CHEBI_ROLE:metabolite']) == 3
    assert len(properties['CHEBI_ROLE:biochemical_role']) == 3
    assert len(properties['CHEBI_ROLE:antibacterial_agent']) == 2
    assert len(properties['CHEBI_ROLE:antimicrobial_agent']) == 2
    assert len(properties['CHEBI_ROLE:eukaryotic_metabolite']) == 2
    assert len(properties['CHEBI_ROLE:fungal_metabolite']) == 2
    assert len(properties) == 6

def test_property_enrichment():
    """
    Check our enrichment calculations.
    3/4l  are mutagens, genotoxins
    """
    inputs = ['PUBCHEM.COMPOUND:11254', 'PUBCHEM.COMPOUND:124886', 'PUBCHEM.COMPOUND:2478','PUBCHEM.COMPOUND:7839']
    results = pc.get_enriched_properties(inputs,'biolink:ChemicalEntity')
    assert len(results) == 2
    assert results[0][1] == 'CHEBI_ROLE:mutagen'
    assert results[1][1] == 'CHEBI_ROLE:genotoxin'

def xtest_disease_property_enrichment():
    """
    Check our enrichment calculations.
    """
    inputs = ['MONDO:0010563', 'MONDO:0010379', 'MONDO:0021019']
    results = pc.get_enriched_properties(inputs, 'biolink:Disease')
    assert len(results) == 2
    assert results[0][1] == 'X_linked_recessive_disease'
    assert results[1][1] == 'X_linked_disease'

def test_property_coalsecer():
    curies = ['PUBCHEM.COMPOUND:11254', 'PUBCHEM.COMPOUND:124886', 'PUBCHEM.COMPOUND:2478','PUBCHEM.COMPOUND:7839']
    opportunity = Opportunity('hash',('qg_0','biolink:SmallMolecule'),curies,[0,1,2,3],{i:[curies[i]] for i in range(4)})
    opportunities=[opportunity]
    patches = pc.coalesce_by_property(opportunities)
    assert len(patches) == 1
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    p = patches[0]
    assert p.qg_id == 'qg_0'
    assert len(p.set_curies) == 3 # 3 of the 4 curies have the identified properties

def xtest_property_coalescer_perf_test():
    from src.single_node_coalescer import coalesce
    import os
    import json
    import datetime

    # get a timestamp
    t1 = datetime.datetime.now()

    # get the path to the test file
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.1','EdgeIDAsStrAndPerfTest.json')

    # open the file and load it
    with open(test_filename,'r') as tf:
        incoming = json.load(tf)
        incoming = incoming['message']

    # call function that does property coalesce
    coalesced = coalesce(incoming, method='property')

    # get the amount of time it took
    diff = datetime.datetime.now() - t1

    # it should be less than this
    assert(diff.seconds < 120)

def xtest_property_coalescer_why_no_coalesce():
    from src.single_node_coalescer import coalesce
    import os
    import json
    import datetime

    # get the path to the test file
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.1','test_property.json')

    # open the file and load it
    with open(test_filename,'r') as tf:
        incoming = json.load(tf)
        incoming = incoming['message']

    # call function that does property coalesce
    coalesced = coalesce(incoming, method='all')
    print(len(coalesced['results']))
    print('hi')

