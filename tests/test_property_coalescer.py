import os
import src.property_coalescence.property_coalescer as pc



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
    assert len(properties['CHEBI_ROLE:biochemical_role']) == 3
    assert len(properties['CHEBI_ROLE:metabolite']) == 3
    assert len(properties['CHEBI_ROLE:antibacterial_agent']) == 2
    assert len(properties['CHEBI_ROLE:antimicrobial_agent']) == 2
    assert len(properties['CHEBI_ROLE:eukaryotic_metabolite']) == 2
    assert len(properties['CHEBI_ROLE:fungal_metabolite']) == 2
    assert len(properties) == 6

def test_property_enrichment():
    """
    Check our enrichment calculations.
    3/4l  are mutagens, genotoxins

    Note: 'CHEBI:134046' have CHEBI_ROLE:drug, to be sure bad predicates are rmoved ensure the 'CHEBI:134046' isn't returned
    """
    inputs = ['CHEBI:134018', 'PUBCHEM.COMPOUND:11254', 'PUBCHEM.COMPOUND:124886', 'PUBCHEM.COMPOUND:2478','PUBCHEM.COMPOUND:7839', 'CHEBI:134046']
    results = pc.get_enriched_properties(inputs,'biolink:ChemicalEntity')
    allenrichedchems = set()
    allenrichedchems.update(results[i][5] for i in range(len(results)))
    assert 'CHEBI:134046' not in allenrichedchems
    assert len(results) == 2
    assert results[0][1] == 'CHEBI_ROLE:mutagen'
    assert results[1][1] == 'CHEBI_ROLE:genotoxin'

