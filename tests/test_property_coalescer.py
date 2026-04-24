import asyncio
import src.property_coalescence.property_coalescer as pc


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

def test_property_coalsecer():
    enr_props = asyncio.run(pc.coalesce_by_property(['CHEBI:955', 'CHEBI:100'], 'biolink:ChemicalEntity'))
    assert len(enr_props) == 3
    assert 'CHEBI_ROLE_biochemical_role' not in [enr_prop["enriched_property"] for enr_prop in enr_props]



