from src.ontology_coalescence.ubergraph import UberGraph

def test_superclass():
    ug = UberGraph()
    mondo = "MONDO:0019391"
    scmap = ug.get_superclasses_of([mondo])
    #sc = scmap[mondo]
    assert len(scmap) > 20
    for k,v in scmap.items():
        assert len(v) == 1
        assert mondo in v
    assert 'MONDO:0015356' in scmap
    assert 'MONDO:0043008' in scmap

def test_count_subclasses():
    ug = UberGraph()
    mondo = "MONDO:0020537"
    sc= ug.count_subclasses_of( set([mondo]) )
    assert sc[mondo] == 4
