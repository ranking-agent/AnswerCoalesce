import pytest
from copy import deepcopy
import json
import os
from src.components import Opportunity

def test_no_filtering():
    """Check that no filtering done when all curies used."""
    #Create opp
    curies = ['curie:1','curie:2','curie:3']
    #opportunity is 1 kg_id per answer
    opportunity = Opportunity('hash',('qg_0','biolink:SmallMolecule'),curies,[0,1,2],{i:[curies[i]] for i in range(3)})
    new_opp = opportunity.filter(curies)
    assert opportunity == new_opp #same object
    assert new_opp.kg_ids == curies # no change
    assert new_opp.answer_indices == [0,1,2]

def test_simple_filtering():
    """When a curie is removed, return a new opp with the relevant kg_id and answer removed"""
    # Create opp
    curies = ['curie:1', 'curie:2', 'curie:3']
    #opportunity is 1 kg_id per answer
    opportunity = Opportunity('hash', ('qg_0', 'biolink:SmallMolecule'), curies, [0, 1, 2],
                              {i: [curies[i]] for i in range(3)})
    keep_curies = curies[0:-1]
    new_opp = opportunity.filter(keep_curies)
    assert not opportunity == new_opp  # new object
    assert set(new_opp.kg_ids) == set(keep_curies)  # changed
    assert new_opp.answer_indices == [0, 1] #answer 2 removed

def test_complex_filtering():
    """When any curie for an answer is removed, make sure the whole answer is gone"""
    # Create opp
    curies = ['curie:1', 'curie:2', 'curie:3', 'curie:4']
    #opportunity is 1 kg_id per answer
    opportunity = Opportunity('hash', ('qg_0', 'biolink:SmallMolecule'), curies, [0, 1],
                              {0: ['curie:1','curie:2'], 1:['curie:3,curie:4']})
    keep_curies = curies[0:-1] #just drop curie:4.  Answer 1 should be removed, and curie:3 along with it
    new_opp = opportunity.filter(keep_curies)
    assert not opportunity == new_opp  # new object
    assert set(new_opp.kg_ids) == set(['curie:1','curie:2'])
    assert new_opp.answer_indices == [0] #answer 1 removed

def test_empty_op():
    """When any curie for an answer is removed, make sure the whole answer is gone"""
    # Create opp
    curies = ['curie:1', 'curie:2', 'curie:3', 'curie:4']
    #opportunity is 1 kg_id per answer
    opportunity = Opportunity('hash', ('qg_0', 'biolink:SmallMolecule'), curies, [0, 1],
                              {0: ['curie:1','curie:2'], 1:['curie:3,curie:4']})
    keep_curies = curies[1:-1] #drop 1 curie from each answer
    new_opp = opportunity.filter(keep_curies)
    assert new_opp is None