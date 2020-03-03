import src.ontology_coalescence.ontology_coalescer as oc

def test_shared_superclass():
    sc = oc.get_shared_superclasses(['MONDO:0009215','MONDO:0012187'])
    assert 'MONDO:0019391' in sc

def test_shared_superclass_2():
    sc = oc.get_shared_superclasses(['MONDO:0025556','MONDO:0004584'])
    assert 'MONDO:0000771' in sc

def test_shared_superclass_3():
    """If the shared superclass is in the list we should still return it"""
    sc = oc.get_shared_superclasses(['MONDO:0025556','MONDO:0004584','MONDO:0000771'])
    assert 'MONDO:0000771' in sc

def test_get_enriched_supers():
    sc = oc.get_enriched_superclasses(['MONDO:0025556','MONDO:0004584','MONDO:0000771'],'disease')
    print(sc)
    assert False
