import os
import src.property_coalescence.property_coalescer as pc
from src.components import Enrichment
import asyncio


def test_get_properties():

    pl = pc.PropertyLookup()

    # 'CHEBI:955' should have 4 roles: 'metabolite', 'plant_metabolite', 'biochemical_role', 'eukaryotic_metabolite'
    props = pl.lookup_property_by_node('CHEBI:955','biolink:ChemicalEntity')
    assert len(props) == 4
    assert 'CHEBI_ROLE_metabolite' in props
    assert 'CHEBI_ROLE_plant_metabolite' in props


    # 'CHEBI:100' should have the same 4 roles as 955:
    props = pl.lookup_property_by_node('CHEBI:100', 'biolink:ChemicalEntity')
    assert len(props) == 4
    assert 'CHEBI_ROLE_biochemical_role' in props
    assert 'CHEBI_ROLE_eukaryotic_metabolite' in props

    # Let's search for the same but now see if it excludes the bad predicates (drug, pharmaceutical, biochemical_role)  inline
    enr_props = pc.get_enriched_properties(['CHEBI:955', 'CHEBI:100'],'biolink:ChemicalEntity')
    assert len(enr_props) == 3
    assert not any('CHEBI_ROLE_biochemical_role' in enr_prop.get("enriched_property") for enr_prop in enr_props)

    #Check an empty
    eprops = pl.lookup_property_by_node('CHEBI:NOTREAL','biolink:ChemicalEntity')
    assert len(eprops) == 0

    #This one was failing because multiple old nodes in robokopdb2 were merging to chebi:16856.  And
    # one without properties was tromping the one with properties, so we were getting an empty property list
    # for something that should have lots of properties!
    qprops = pl.lookup_property_by_node('CHEBI:16856','biolink:ChemicalEntity')
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
    properties = pl.collect_properties(['CHEBI:68299', 'CHEBI:68075', 'CHEBI:65728'],'biolink:ChemicalEntity')
    assert len(properties['CHEBI_ROLE_biochemical_role']) == 3
    assert len(properties['CHEBI_ROLE_metabolite']) == 3
    assert len(properties['CHEBI_ROLE_antibacterial_agent']) == 2
    assert len(properties['CHEBI_ROLE_antimicrobial_agent']) == 2
    assert len(properties['CHEBI_ROLE_eukaryotic_metabolite']) == 2
    assert len(properties['CHEBI_ROLE_fungal_metabolite']) == 2
    assert len(properties) == 6

def test_property_enrichment():
    """
    Check our enrichment calculations.
    3/4l  are mutagens, genotoxins

    Note: 'CHEBI:134046' have CHEBI_ROLE:drug, to be sure bad predicates are rmoved ensure the 'CHEBI:134046' isn't returned
    """
    inputs = ['CHEBI:132747', 'CHEBI:23704', 'CHEBI:16856', 'CHEBI:28901','CHEBI:28534', 'CHEBI:134046']
    results = pc.get_enriched_properties(inputs,'biolink:ChemicalEntity')
    result_properties = [enr_prop.get("enriched_property") for enr_prop in results]
    allenrichedchems = set()
    allenrichedchems.update(curies for result in results for curies in result.get("linked_curies"))
    assert 'CHEBI:134046' not in allenrichedchems
    assert len(results) == 9

    assert 'CHEBI_ROLE_biochemical_role' not in result_properties
    assert 'CHEBI_ROLE_mutagen' in result_properties
    assert 'CHEBI_ROLE_genotoxin' in result_properties

def xtest_disease_property_enrichment():
    """
    This would not work since we have no disease db right now
    Check our enrichment calculations.
    """
    inputs = ['MONDO:0010563', 'MONDO:0010379', 'MONDO:0021019']
    results = pc.get_enriched_properties(inputs, 'biolink:Disease')
    assert len(results) == 2
    assert results[0][1] == 'X_linked_recessive_disease'
    assert results[1][1] == 'X_linked_disease'

def test_property_coalsecer():
    enr_props = asyncio.run(pc.coalesce_by_property(['CHEBI:955', 'CHEBI:100'], 'biolink:ChemicalEntity'))
    assert len(enr_props) == 3
    assert 'CHEBI_ROLE_biochemical_role' not in [enr_prop["enriched_property"] for enr_prop in enr_props]


def xtest_property_coalescer_perf_test():
    from src.single_node_coalescer import coalesce
    import os
    import json
    import datetime

    # get a timestamp
    t1 = datetime.datetime.now()

    # get the path to the test file
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.5','EdgeIDAsStrAndPerfTest.json')

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
    test_filename = os.path.join(os.path.abspath(os.path.dirname(__file__)),'InputJson_1.5','test_property.json')

    # open the file and load it
    with open(test_filename,'r') as tf:
        incoming = json.load(tf)
        incoming = incoming['message']

    # call function that does property coalesce
    coalesced = coalesce(incoming, method='all')
    print(len(coalesced['results']))
    print('hi')

