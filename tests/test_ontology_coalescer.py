import src.ontology_coalescence.ontology_coalescer as oc

def test_shared_superclass():
    sc = oc.get_shared_superclasses(['MONDO:0009215','MONDO:0012187'],'MONDO')
    assert 'MONDO:0019391' in sc

def test_shared_superclass_2():
    sc = oc.get_shared_superclasses(['MONDO:0025556','MONDO:0004584'],'MONDO')
    assert 'MONDO:0000771' in sc

def test_shared_superclass_3():
    """If the shared superclass is in the list we should still return it"""
    sc = oc.get_shared_superclasses(['MONDO:0025556','MONDO:0004584','MONDO:0000771'],'MONDO')
    assert 'MONDO:0000771' in sc

def test_get_enriched_supers():
    sc = oc.get_enriched_superclasses(['MONDO:0025556','MONDO:0004584','MONDO:0000771'],'disease')
    assert len(sc) == 2
    #The other two are both subclasses of 0000771, so the most enrichment will be for that node
    sc[0][1] == 'MONDO:0000771'

def test_ontology_coalescer():
    curies = [ 'MONDO:0025556', 'MONDO:0004584', 'MONDO:0000771' ]
    opportunity = ['hash',('qg_0','disease'),curies,[0,1,2]]
    opportunities=[opportunity]
    patches = oc.coalesce_by_ontology(opportunities)
    assert len(patches) == 1
    #patch = [qg_id that is being replaced, curies (kg_ids) in the new combined set, props for the new curies, answers being collapsed]
    p = patches[0]
    assert p[0] == 'qg_0'
    assert len(p[1]) == 3 # 3 of the 3 curies are subclasses of the output
    assert isinstance(p[2],dict)
    assert p[2]['coalescence_method'] == 'ontology_enrichment'
    assert p[2]['p_values'][0] < 1e-4
    assert len(p[2]['p_values']) == 2
    assert p[2]['superclass'][0] == 'MONDO:0000771'
