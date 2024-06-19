import pytest
import os, json, asyncio
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from src.components import Enrichment
from reasoner_pydantic import Response as PDResponse
import pytest
from src.graph_coalescence.graph_coalescer import filter_links_by_node_type
from src.components import Enrichment


jsondir='InputJson_1.5'
predicates_to_exclude =["biolink:causes", "biolink:biomarker_for", "biolink:biomarker_for", "biolink:contraindicated_for",
                        "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"]

def test_get_links_and_predicate_filter():
    """We expect that this Gene has 2701  links.
    "{\"predicate\": \"biolink:coexpressed_with\", \"species_context_qualifier\": \"NCBITaxon:9606\"}" 1540
    "{\"predicate\": \"biolink:correlated_with\", \"species_context_qualifier\": \"NCBITaxon:9606\"}" 1540
    "{\"predicate\": \"biolink:related_to\", \"species_context_qualifier\": \"NCBITaxon:9606\"}" 1826
    "{\"predicate\": \"biolink:associated_with\", \"species_context_qualifier\": \"NCBITaxon:9606\"}" 1540
    "{\"predicate\": \"biolink:physically_interacts_with\", \"species_context_qualifier\": \"NCBITaxon:9606\"}" 270
    "{\"predicate\": \"biolink:interacts_with\", \"species_context_qualifier\": \"NCBITaxon:9606\"}" 270
    "{\"predicate\": \"biolink:directly_physically_interacts_with\"}" 78
    "{\"predicate\": \"biolink:physically_interacts_with\"}" 78
    "{\"predicate\": \"biolink:interacts_with\"}" 110
    "{\"predicate\": \"biolink:related_to\"}" 211
    "{\"predicate\": \"biolink:genetically_interacts_with\"}" 10
    "{\"predicate\": \"biolink:located_in\"}" 62
    "{\"predicate\": \"biolink:has_part\"}" 6
    "{\"predicate\": \"biolink:overlaps\"}" 6
    "{\"predicate\": \"biolink:regulates\"}" 22
    "{\"predicate\": \"biolink:affects\"}" 22
    "{\"predicate\": \"biolink:actively_involved_in\"}" 19
    "{\"predicate\": \"biolink:participates_in\"}" 22
    "{\"predicate\": \"biolink:catalyzes\"}" 3
    "{\"object_direction_qualifier\": \"downregulated\", \"predicate\": \"biolink:regulates\"}" 10
    "{\"object_direction_qualifier\": \"decreased\", \"predicate\": \"biolink:regulates\"}" 10
    "{\"predicate\": \"biolink:correlated_with\"}" 6
    "{\"predicate\": \"biolink:associated_with\"}" 7
    "{\"predicate\": \"biolink:subclass_of\"}" 4
    "{\"object_direction_qualifier\": \"upregulated\", \"predicate\": \"biolink:regulates\"}" 6
    "{\"object_direction_qualifier\": \"increased\", \"predicate\": \"biolink:regulates\"}" 6
    "{\"predicate\": \"biolink:genetically_associated_with\"}" 1
    # symmetric edges are NOT doubled what is above at query time
    """
    curies = ["NCBIGene:10469"]
    total_edges = 7685
    nodes_to_links = gc.create_nodes_to_links(curies)
    assert len(nodes_to_links) == 1
    # Hand counted
    from collections import defaultdict
    dd = defaultdict(int)
    for link in nodes_to_links[curies[0]]:
        p = link[1]
        dd[p] += 1
    assert len(nodes_to_links[curies[0]]) == total_edges

    # Test exclude a single predicate, "biolink:directly_physically_interacts_with"
    constraint = {"predicate": "biolink:directly_physically_interacts_with"}
    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint], predicate_constraint_style='exclude')
    assert len(filtered_nodes_to_links[curies[0]]) == total_edges - 78

    # Test include a single symmetric predicate
    constraint = {"predicate": "biolink:associated_with"}
    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint], predicate_constraint_style='include')
    assert len(filtered_nodes_to_links[curies[0]]) == 7

    # Test include a single constraint with predicate and qualifier
    constraint = {"object_direction_qualifier": "upregulated", "predicate": "biolink:regulates"}
    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint], predicate_constraint_style='include')
    assert len(filtered_nodes_to_links[curies[0]]) == 6

    # Test exclude multiple constraints, including some that are not present at all
    constraint1 = {"predicate": "biolink:affects", "object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased"}
    constraint2 = {"predicate": "biolink:overlaps"}
    constraint3 = {"predicate": "biolink:related_to"}
    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint1, constraint2, constraint3], predicate_constraint_style='exclude')
    assert len(filtered_nodes_to_links[curies[0]]) == total_edges - (211 + 6)


    filtered_nodes_to_links = gc.filter_links_by_predicate(nodes_to_links, [constraint1, constraint2, constraint3],
                                                       predicate_constraint_style='include')
    assert len(filtered_nodes_to_links[curies[0]]) ==  (211 + 6)

def test_get_prov():
    enrichment1 = Enrichment(1e-10, "NCBIGene:2932", '{"predicate": "biolink:interacts_with"}', True, 100, 10, 1000, ["NCBIGene:1500"], ["biolink:Gene"])
    enrichment2 = Enrichment(1e-10, "NCBIGene:1500", '{"predicate": "biolink:interacts_with"}', True, 100, 10, 1000, ["NCBIGene:2932"], ["biolink:Gene"])
    gc.add_provs([enrichment1,enrichment2])
    for link in enrichment1.links:
        assert link.prov
    for link in enrichment2.links:
        assert link.prov


def test_filter_links_by_node_type():
    # Mocking the nodes_to_links dictionary
    nodes_to_links = {
        "node1": [("node3", "predicate1", True), ("node4", "predicate2", False)],
        "node2": [("MONDO:0000001", "predicate1", False), ("node5", "predicate3", True)],
    }
    # Mocking the link_node_types dictionary
    link_node_types = {
        "node3": "biolink:Gene",
        "node4": "biolink:SmallMolecule",
        "MONDO:0000001": "biolink:Disease",
        "node5": "biolink:ChemicalEntity",
    }


    # Mocking the node_constraints list
    node_constraints = ["biolink:NamedThing"]
    # Expected output after filtering. The node constraint should let everythign past,
    # but the blocklist should get rid of the MONDO
    expected_output = { "node1": [("node3", "predicate1", True), ("node4", "predicate2", False)],
                        "node2": [("node5", "predicate3", True)] }

    # Call the function with the mocked data and assert the expectation
    result = filter_links_by_node_type(nodes_to_links, node_constraints, link_node_types)
    assert result == expected_output

    # Now try with a different node constraint: Chemical Entity which should remove node1
    node_constraints = ["biolink:ChemicalEntity"]
    expected_output = { "node1": [ ("node4", "predicate2", False)],
                        "node2": [("node5", "predicate3", True)] }

def test_filter_enrichment_results():
    """
    Scenario 1***************:
      result 1 and 2 is a tree in which 1 is the ancestor of 2, however, they have different pvalues
             3 and 4 is a tree in which 4 is the ancestor of 3, however, they have the same pvalue

      Task: Consolidate the result into two using the most specific predicate in each tree

      Steps:
        1. Groups the 4 results by pvalues then pick the most specific in ech case/group
            step_outcome: Results 1, 2, and 3
        2. if step (1)) outcomes has parent/child relationship and the child has a better p_value, return the most specific(child)
           if step (1)) outcomes has parent/child relationship and the parent has a better p_value, return the least specific(parent)
             step_outcomes:
                Results 1, 2 has a parent/child relationship and the child(result1) has a better pvalue
                Result 3 is another branch separate from 1, 2
             hence, we return Results 1, and 3

      input = [result1, result2, result3, result4]
      output: [result1, result4]


    Scenario 2***************:
      result 1, 2 and 4 is a tree in which 2 is the ancestor of 1, and 1 is the ancestor of 4; however, all have different pvalues
             3 and 5 is a tree in which 3 is the ancestor of 5, however, they have the different p_value

      Task: Consolidate the result into two using the most specific predicate in each tree

      Steps:
        1. Groups the 5 results by p_values then pick the most specific in ech case/group
            step_outcome: Results 1, 2, 3, 4, 5
        2. The step (1) outcomes has parent/child relationships:
                (a) 2, 1, 4
                (b) 3, 5
             step_outcomes:
               In (a), the child 1 has a better p_value, but it is the more specific, hence, return result 1
               In (b), the parent 3 has a better p_value, but it is the least specific of the two, hence, return the parent
        hence, we return Results 1, and 3

      input = [result1, result2, result3, result4, result5]
      output: [result3, result1]

      """
    result1 = Enrichment(8.033689062162034e-11,'HP:0020110', {'predicate': 'biolink:causes'}, True, 2, 4, 2, ['CHEBI:8874', 'CHEBI:53289', 'CHEBI:42944'], 'biolink:DiseaseOrPhenotypicFeature')
    result2 = Enrichment(9.161641498909993e-11, 'HP:0020110', {'predicate': 'biolink:contributes_to'}, True, 2, 4, 2, ['CHEBI:8874', 'CHEBI:53289', 'CHEBI:64312'], 'biolink:DiseaseOrPhenotypicFeature')
    result3 = Enrichment(1.3168191577498547e-10, 'HP:0020110', {'predicate': 'biolink:has_adverse_event'}, True, 2, 4, 2, ['CHEBI:8874', 'CHEBI:53289', 'CHEBI:64312'], 'biolink:DiseaseOrPhenotypicFeature')
    result4 = Enrichment(1.3168191577498547e-10, 'HP:0020110', {'predicate': 'biolink:affects'}, True, 2, 4, 2, ['CHEBI:8874', 'CHEBI:53289', 'CHEBI:64312'], 'biolink:DiseaseOrPhenotypicFeature')
    # Scenario 1 ***************
    result = gc.filter_result_hierarchies([result1, result2, result3, result4])
    assert [result3, result1] == result #unsorted because we wait to sort finally in the get_enriched_links

    # # Using a real enrichment result:
    # result1 = Enrichment(1.7108004493514417e-72, 'MONDO:0004975', {'predicate': 'biolink:treats'}, False, 16, 19, 1366955.0, ['UNII:12PYH0FTU9', 'CHEBI:45980', 'CHEBI:125612', 'CHEBI:15355', 'CHEBI:3048', 'CHEBI:53289', 'CHEBI:135927', 'CHEBI:64312', 'UNII:105J35OE21', 'CHEBI:42944', 'CHEBI:8874', 'CHEBI:8888', 'CHEBI:57589', 'CHEBI:9086', 'CHEBI:8707', 'CHEBI:5613'], 'biolink:Disease')
    # result2 = Enrichment(3.0839908185924632e-61, 'MONDO:0004975', {'predicate': 'biolink:biolink:treats_or_applied_or_studied_to_treat'}, False, 16, 96, 1366955.0, ['UNII:12PYH0FTU9', 'CHEBI:45980', 'CHEBI:125612', 'CHEBI:15355', 'CHEBI:3048', 'CHEBI:53289', 'CHEBI:135927', 'CHEBI:64312', 'UNII:105J35OE21', 'CHEBI:42944', 'CHEBI:8874', 'CHEBI:8888', 'CHEBI:57589', 'CHEBI:9086', 'CHEBI:8707', 'CHEBI:5613'], 'biolink:Disease')
    # result3 = Enrichment(3.7469289680403445e-31, 'MONDO:0004975', {'predicate': 'biolink:affects'}, False, 16, 13, 1366955.0, ['CHEBI:15355', 'CHEBI:3048', 'CHEBI:53289', 'CHEBI:8888', 'CHEBI:9086', 'CHEBI:8707', 'CHEBI:5613'], 'biolink:Disease')
    # result4 = Enrichment(1.6662626195823426e-28, 'MONDO:0004975', {'predicate': 'biolink:ameliorates_condition'}, False, 16, 6, 1366955.0, ['CHEBI:15355', 'CHEBI:3048', 'CHEBI:8888', 'CHEBI:9086', 'CHEBI:8707', 'CHEBI:5613'], 'biolink:Disease')
    # result5 = Enrichment(7.022661981030352e-05, 'MONDO:0004975', {'predicate': 'biolink:has_adverse_event'}, False, 16, 6, 1366955.0, ['CHEBI:53289'], 'biolink:Disease')
    # # Scenario 2 ***************
    # result = gc.filter_result_hierarchies([result1, result2, result3, result4, result5])
    # assert [result3, result1] == result  # unsorted because we wait to sort finally in the get_enriched_links

    print("All test cases passed!")



@pytest.mark.asyncio
async def test_graph_coalescer():
    curies = [ 'NCBIGene:106632262', 'NCBIGene:106632263','NCBIGene:106632261' ]
    enrichments = await gc.coalesce_by_graph(curies, 'biolink:Gene' )
    assert len(enrichments) >= 1
    e = enrichments[0]
    assert len(e.linked_curies) == 3 # 3 of the 3 curies are subclasses of the output
    #TODO: add attribute testing to TRAPI tests
    #atts=p.new_props['attributes']
    #kv = { x['attribute_type_id']: x['value'] for x in atts}
    #assert kv['biolink:supporting_study_method_type'] == 'graph_enrichment'
    #assert kv['biolink:p_value'] < 1e-10
    assert e.p_value < 1e-10
    assert e.enriched_node.new_curie == "HGNC.FAMILY:1384"

@pytest.mark.asyncio
async def test_graph_coalescer_double_check():
    curies = ['NCBIGene:191',
 'NCBIGene:55832',
 'NCBIGene:645',
 'NCBIGene:54884',
 'NCBIGene:8239',
 'NCBIGene:4175',
 'NCBIGene:10469',
 'NCBIGene:8120',
 'NCBIGene:3840',
 'NCBIGene:55705',
 'NCBIGene:2597',
 'NCBIGene:23066',
 'NCBIGene:7514',
 'NCBIGene:10128']
    enrichments = await gc.coalesce_by_graph(curies, 'biolink:Gene', result_length=100)
    assert len(enrichments) == 100
    e = enrichments[0]
    assert e.p_value < 1e-10


def test_graph_coalesce_basic():
    """Make sure that results are well formed."""
    input_message = get_input_message()
    coalesced = asyncio.run( snc.multi_curie_query(input_message, input_message.get("parameters")) )
    #Assert that the output is well-formed
    assert PDResponse.parse_obj(coalesced)
    # We should have lots of results.  The exact number will not change as long as the test data does not
    assert len(coalesced['message']['results']) == 5928
    # Let's make sure that the KL/AT are only mentioned once (this was a problem at one point)
    ps_and_preds = []
    for kedge_id, kedge in coalesced['message']['knowledge_graph']['edges'].items():
        atts = kedge.get('attributes')
        assert len(atts) == len(set([x['attribute_type_id'] for x in atts]))

def test_graph_coalesce_pvalue_threshold():
    input_message = get_input_message()
    threshold = 1e-7
    input_message["parameters"]["pvalue_threshold"] = threshold
    coalesced = asyncio.run( snc.multi_curie_query(input_message, input_message.get("parameters")) )
    #Make sure we got some results
    assert len(coalesced['message']['results']) > 0
    # All of the p-values should be less than the threshold
    # First, find all the enrichment edges.  They are the ones in the result.analysis.edge_bindings
    for r in coalesced['message']['results']:
        analysis = r["analyses"][0]
        for qg,kgs in analysis["edge_bindings"].items():
            kedge_id = kgs[0]["id"]
            kedge = coalesced['message']['knowledge_graph']['edges'][kedge_id]
            attributes = kedge.get("attributes")
            # Find the p_value attribute
            found = False
            for a in attributes:
                if a["attribute_type_id"] == "biolink:p_value":
                    found = True
                    assert a["value"] < threshold
            assert found

def test_graph_coalesce_predicate():
    input_message = get_input_message()
    threshold = 1e-7
    input_message["parameters"]["pvalue_threshold"] = threshold
    # Change the input qedge
    input_message["message"]["query_graph"]["edges"]["e1"]["predicates"] = ["biolink:has_phenotype"]
    coalesced = asyncio.run( snc.multi_curie_query(input_message, input_message.get("parameters")) )
    #Make sure we got some results
    assert len(coalesced['message']['results']) > 0
    # All of the enrichment edges should have the predicate we asked for
    # First, find all the enrichment edges.  They are the ones in the result.analysis.edge_bindings
    for r in coalesced['message']['results']:
        analysis = r["analyses"][0]
        for qg,kgs in analysis["edge_bindings"].items():
            kedge_id = kgs[0]["id"]
            kedge = coalesced['message']['knowledge_graph']['edges'][kedge_id]
            assert kedge["predicate"] == "biolink:has_phenotype"


def get_input_message():
    """We used to use more different inputs, but they generated test files that were too big for github."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'famcov_new_with_params_and_pcut1e7_MCQ.json')
    with open(testfilename, 'r') as tf:
        input_message = json.load(tf)
    assert PDResponse.parse_obj(input_message)
    assert input_message.get("parameters").get('pvalue_threshold')
    assert input_message.get("parameters").get('predicates_to_exclude')
    input_message["parameters"]["pvalue_threshold"] = None
    input_message["parameters"]["result_length"] = None
    return input_message



#Used in test_graph_coalesce to extract values from attributes, which can be a list or a string
def flatten(ll):
    if isinstance(ll, list):
        temp = []
        for ele in ll:
            temp.extend(flatten(ele))
        return temp
    else:
        return [ll]
def test_gouper():
    x = 'abcdefghi'
    n = 0
    for group in gc.grouper(3,x):
        x = group
        n += 1
    assert n == 3
    assert x == ('g','h','i')

def test_gouper_keys():
    d = {x:x for x in 'abcdefg'}
    n = 0
    for group in gc.grouper(3, d.keys()):
        x = group
        n += 1
    assert n == 3
    assert x == ('g',)


