from src.ontology_coalescence.ubergraph import UberGraph

def test_superclass():
    ug = UberGraph()
    mondo = "MONDO:0019391"
    sc = ug.get_superclasses_of(mondo)
    assert len(sc) > 20
    assert 'MONDO:0015356' in sc
    assert 'MONDO:0043008' in sc

def test_count_subclasses():
    ug = UberGraph()
    mondo = "MONDO:0020537"
    sc = ug.count_subclasses_of(mondo)
    assert sc == 4
