import pytest
import os, json, asyncio
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from src.components import Enrichment
from reasoner_pydantic import Response as PDResponse
import pytest
from src.graph_coalescence.graph_coalescer import filter_links_by_node_type, streamline_children_to_parent
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


def test_filter_enrichment_results_s1():
    """
    Scenario 1***************:
        Results 1 and 2 is a tree in which 2 is the ancestor of 1; however, they have different p-values.
        Results 3 and 4 is a tree in which 4 is the ancestor of 3; however, they have the same p-value.

        Task: Consolidate the results into two using the most specific predicate in each tree.

        Steps:
        * Group the 4 results by p-values, then pick the most specific in each group.
            Step outcome:
            Three result groups: 1, 2, and 3 & 4
        * Now pick the most specific overall by p-value and parent/child relationship:
            If the step (1) outcomes have a parent/child relationship and the child has a better p-value, return the most specific (child).
            If the step (1) outcomes have a parent/child relationship and the parent has a better p-value, return the least specific (parent).
            Step outcome:
                The first group result (1) has a parent/child relationship with the second (2), and the child (result 1) has a better p-value.
                The third group result (3 & 4) is another branch in which 4 is the parent. They have the exact same p-value, so we pick the child (most specific).
            Hence, we return Results 1 and 3.

        Input: [result1, result2, result3, result4]
        Output: [result2, result3]
    """

    result1 = Enrichment(8.033689062162034e-11, 'HP:0020110', '{"predicate": "biolink:causes"}', True, 2, 4, 2,['CHEBI:8874', 'CHEBI:53289', 'CHEBI:42944'], 'biolink:DiseaseOrPhenotypicFeature')
    result2 = Enrichment(9.161641498909993e-11, 'HP:0020110', '{"predicate": "biolink:contributes_to"}', True, 2, 4, 2,['CHEBI:8874', 'CHEBI:53289', 'CHEBI:64312'], 'biolink:DiseaseOrPhenotypicFeature')
    result3 = Enrichment(1.3168191577498547e-10, 'HP:0020110', '{"predicate": "biolink:has_adverse_event"}', True, 2, 4,2, ['CHEBI:8874', 'CHEBI:53289', 'CHEBI:64312'], 'biolink:DiseaseOrPhenotypicFeature')
    result4 = Enrichment(1.3168191577498547e-10, 'HP:0020110', '{"predicate": "biolink:affects"}', True, 2, 4, 2,['CHEBI:8874', 'CHEBI:53289', 'CHEBI:64312'], 'biolink:DiseaseOrPhenotypicFeature')

    result = gc.filter_result_hierarchies([result1, result2, result3, result4])
    assert len(result) == 2
    assert result1 in result
    assert result3 in result



def test_filter_enrichment_results_S2():
    """
    Scenario 2*************** REAL EXAMPLE FROM AC:
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
      output: [result1, result3]

    # #   """

    result1 = Enrichment(1.7108004493514417e-72, 'MONDO:0004975', '{"predicate": "biolink:treats"}', False, 16, 19,1366955.0, ['UNII:12PYH0FTU9', 'CHEBI:45980', 'CHEBI:125612', 'CHEBI:15355', 'CHEBI:3048', 'CHEBI:53289', 'CHEBI:135927', 'CHEBI:64312', 'UNII:105J35OE21', 'CHEBI:42944', 'CHEBI:8874', 'CHEBI:8888', 'CHEBI:57589', 'CHEBI:9086', 'CHEBI:8707', 'CHEBI:5613'], 'biolink:Disease')
    result2 = Enrichment(3.0839908185924632e-61, 'MONDO:0004975','{"predicate": "biolink:treats_or_applied_or_studied_to_treat"}', False, 16, 96, 1366955.0,['UNII:12PYH0FTU9', 'CHEBI:45980', 'CHEBI:125612', 'CHEBI:15355', 'CHEBI:3048', 'CHEBI:53289', 'CHEBI:135927', 'CHEBI:64312', 'UNII:105J35OE21', 'CHEBI:42944', 'CHEBI:8874', 'CHEBI:8888', 'CHEBI:57589', 'CHEBI:9086', 'CHEBI:8707', 'CHEBI:5613'], 'biolink:Disease')
    result3 = Enrichment(3.7469289680403445e-31, 'MONDO:0004975', '{"predicate": "biolink:affects"}', False, 16, 13,1366955.0, ['CHEBI:15355', 'CHEBI:3048', 'CHEBI:53289', 'CHEBI:8888', 'CHEBI:9086', 'CHEBI:8707', 'CHEBI:5613'], 'biolink:Disease')
    result4 = Enrichment(1.6662626195823426e-28, 'MONDO:0004975', '{"predicate": "biolink:ameliorates_condition"}',False, 16, 6, 1366955.0, ['CHEBI:15355', 'CHEBI:3048', 'CHEBI:8888', 'CHEBI:9086', 'CHEBI:8707', 'CHEBI:5613'], 'biolink:Disease')
    result5 = Enrichment(7.022661981030352e-05, 'MONDO:0004975', '{"predicate": "biolink:has_adverse_event"}', False,16, 6, 1366955.0, ['CHEBI:53289'], 'biolink:Disease')

    result = gc.filter_result_hierarchies([result1, result2, result3, result4, result5])
    assert len(result) == 2
    assert result1 in result
    assert result3 in result


def test_filter_enrichment_results_s3():
    """
    Scenario 3***************: REAL EXAMPLE FROM AC
        Results 1 and 2 and 3 all has the same p_value, however, result3 is the parent of result3 which is the parent if result1

        Task: Return the most specific (child) results in the tree

        Steps:
        * Find the ancestors of each of the results then return the last child.

        Input: [result1, result2, result3]
        Output: [result1]
    """
    result1 = Enrichment(1.2043826479125558e-07, 'HP:0032141', '{"predicate": "biolink:causes"}', False, 61, 11, 1366955.0, ['CHEBI:15407', 'CHEBI:51209'], 'biolink:Disease')
    result2 = Enrichment(1.2043826479125558e-07, 'HP:0032141', '{"predicate": "biolink:related_to"}', True, 61, 11,1366955.0, ['CHEBI:15407', 'CHEBI:51209'], 'biolink:Disease')
    result3 = Enrichment(1.2043826479125558e-07, 'HP:0032141', '{"predicate": "biolink:contributes_to"}', False, 61, 11,1366955.0, ['CHEBI:15407', 'CHEBI:51209'], 'biolink:Disease')

    result = gc.filter_result_hierarchies([result1, result2, result3])
    assert result == [result1]


def test_filter_enrichment_results_s4():
    """
    Scenario 4***************: REAL EXAMPLE FROM AC
        Results 2 is the overall parent in tree, it also has the least p_value

        Task: Return the results with the least p_value.

        Steps:
        * Group the 4 results the most specific p-value and parent/child relationship:
            If the child has a better p-value, return the most specific (child).
            If the parent has a better p-value, return the least specific (parent).

        Input: [result1, result2, result3, result4]
        Output: [result2]
    # #   """

    result1 = Enrichment(5.62677119993497e-16, 'MONDO:0006032', '{"predicate": "biolink:contributes_to"}', False, 61, 193,1366955.0,['CHEBI:408174', 'CHEBI:5147', 'CHEBI:6888', 'CHEBI:8378', 'CHEBI:8382', 'CHEBI:92511'], 'biolink:Disease')
    result2 = Enrichment(6.984714344422767e-26, 'MONDO:0006032', '{"predicate": "biolink:related_to"}', True, 61,310, 1366955.0,['CHEBI:28918', 'CHEBI:408174', 'CHEBI:5134', 'CHEBI:5147', 'CHEBI:5551', 'CHEBI:6888', 'CHEBI:8378', 'CHEBI:8382', 'CHEBI:92511', 'UNII:420K487FSG'],'biolink:Disease')
    result3 = Enrichment(2.688166355839941e-06, 'MONDO:0006032', '{"predicate": "biolink:treats_or_applied_or_studied_to_treat"}', False, 61, 52,1366955.0,['CHEBI:28918', 'CHEBI:4463'], 'biolink:Disease')
    result4 = Enrichment(2.8008696832786763e-17, 'MONDO:0006032', '{"predicate": "biolink:has_adverse_event"}', False, 61, 117,1366955.0,['CHEBI:28918', 'CHEBI:5134', 'CHEBI:5551', 'CHEBI:6888', 'CHEBI:8378', 'UNII:420K487FSG'], 'biolink:Disease')
    result5 = Enrichment(3.9591314521010225e-08, 'MONDO:0006032', '{"predicate": "biolink:causes"}', False, 61, 139,1366955.0,['CHEBI:408174', 'CHEBI:5147', 'CHEBI:92511'], 'biolink:Disease')

    result = gc.filter_result_hierarchies([result1, result2, result3, result4, result5])
    assert result == [result2]
    #



def test_filter_enrichment_results_s5():
    """
    Scenario 5*************** REAL EXAMPLE FROM AC:
      result6 has "related_to" predicate which is the parent of "affects" common to the other results
      result1, result2, result3, result4, result5, result7, result8, result9, result10, result11, result12 has the same "affects" predicates
            However,
                    result5 has no Qualifier
                    other results have Qualifiers which are dependent on each other

      Task: Return the result the most specific/best p_value predicate in the tree

      Steps:
        1. Groups the results by p_values then pick the most specific in ech case/group
            step_outcome: 7 Results from the 7 distinct p_values
        2. The step (1) outcomes has parent/child relationships:
                result6 is the parent of [result1, result3, result5, result8, result10, result12]
            *
             step_outcomes:
               if any of the children has a better p_value, and it is the more specific, hence, return the child
               if the parent-result6 has a better p_value, though it is the least specific, return the parent
        hence, we return result5

      input = [result1, result2, result3, result4, result5, result7, result8, result9, result10, result11, result12]
      output: [result5]

    # #   """

    result1 = Enrichment(0.0005353534265271418, 'NCBIGene:632', '{"object_aspect_qualifier": "secretion", "predicate": "biolink:affects"}', False, 61, 12,1366955.0, ['CHEBI:6888'], 'biolink:Gene')
    result2 = Enrichment(0.0005353534265271418, 'NCBIGene:632', '{"object_aspect_qualifier": "transport", "predicate": "biolink:affects"}', False, 61, 12,1366955.0, ['CHEBI:6888'], 'biolink:Gene')
    result3 = Enrichment(0.00022309876782534895, 'NCBIGene:632', '{"object_aspect_qualifier": "secretion", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}', False, 61, 5, 1366955.0, ['CHEBI:6888'], 'biolink:Gene')
    result4 = Enrichment(0.00022309876782534895, 'NCBIGene:632', '{"object_aspect_qualifier": "transport", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}', False, 61, 5, 1366955.0, ['CHEBI:6888'], 'biolink:Gene')
    result5 = Enrichment(3.980364423629894e-07, 'NCBIGene:632', '{"predicate": "biolink:affects"}', False, 61, 20,  1366955.0, ['CHEBI:4463', 'CHEBI:6888'], 'biolink:Gene')
    result6 = Enrichment(6.725615356368366e-07, 'NCBIGene:632', '{"predicate": "biolink:related_to"}', False, 61, 26,  1366955.0, ['CHEBI:4463', 'CHEBI:6888'], 'biolink:Gene')
    result7 = Enrichment(0.00017848299646047716, 'NCBIGene:632', '{"object_aspect_qualifier": "expression", "predicate": "biolink:affects"}', False, 61, 4, 1366955.0, ['CHEBI:4463'], 'biolink:Gene')
    result8 = Enrichment(0.00017848299646047716, 'NCBIGene:632', '{"object_aspect_qualifier": "expression", "object_direction_qualifier": "increased", "predicate": "biolink:affects"}', False, 61, 4, 1366955.0, ['CHEBI:4463'], 'biolink:Gene')
    result9 = Enrichment(0.00017848299646047716, 'NCBIGene:632',  '{"object_aspect_qualifier": "abundance", "predicate": "biolink:affects"}', False, 61, 4, 1366955.0, ['CHEBI:4463'], 'biolink:Gene')
    result10 = Enrichment(0.00017848299646047716, 'NCBIGene:632', '{"object_aspect_qualifier": "abundance", "object_direction_qualifier": "increased", "predicate": "biolink:affects"}', False, 61, 4, 1366955.0, ['CHEBI:4463'], 'biolink:Gene')
    result11 = Enrichment(0.0003123243378767348, 'NCBIGene:632', '{"object_aspect_qualifier": "activity_or_abundance", "predicate": "biolink:affects"}', False, 61, 7, 1366955.0, ['CHEBI:4463'], 'biolink:Gene')
    result12 = Enrichment(0.00026771254826782066, 'NCBIGene:632', '{"object_aspect_qualifier": "activity_or_abundance", "object_direction_qualifier": "increased", "predicate": "biolink:affects"}', False, 61, 6, 1366955.0, ['CHEBI:4463'], 'biolink:Gene')

    result = gc.filter_result_hierarchies([result1, result2, result3, result4, result5, result6, result7, result8, result9, result10, result11, result12])
    assert result == [result5]

    print("All test cases passed!")


def test_filter_enrichment_results_s6():
    """
    Scenario 5*************** REAL EXAMPLE FROM AC:
      result6 has "related_to" predicate which is the parent of "affects" common to the other results
      result1, result2, result3, result4, result5, result7, result8, result9, result10, result11, result12 has the same "affects" predicates
            However,
                    result5 has no Qualifier
                    other results have Qualifiers which are dependent on each other

      Task: Return the result the most specific/best p_value predicate in the tree

      Steps:
        1. Groups the results by p_values then pick the most specific in ech case/group
            step_outcome: 7 Results from the 7 distinct p_values
        2. The step (1) outcomes has parent/child relationships:
                result6 is the parent of [result1, result3, result5, result8, result10, result12]
            *
             step_outcomes:
               if any of the children has a better p_value, and it is the more specific, hence, return the child
               if the parent-result6 has a better p_value, though it is the least specific, return the parent
        hence, we return result5

      input = [result1, result2, result3, result4, result5, result7, result8, result9, result10, result11, result12]
      output: [result5]

    # #   """

    result1 = Enrichment(6.440871527077959e-35, 'NCBIGene:154', '{"object_aspect_qualifier": "activity", "predicate": "biolink:affects"}', False, 61, 2837,1366955.0, ['19'], 'biolink:Gene')
    result2 = Enrichment(8.841059601006888e-35, 'NCBIGene:154', '{"object_aspect_qualifier": "activity_or_abundance", "predicate": "biolink:affects"}', False, 61, 2885,1366955.0, ['19'], 'biolink:Gene')
    result3 = Enrichment(1.2708916953779429e-34, 'NCBIGene:154', '{"predicate": "biolink:affects"}', False, 61, 5, 1366955.0, ['CHEBI:6888'], 'biolink:Gene')
    result4 = Enrichment(1.451342937454794e-32, 'NCBIGene:154', '{"predicate": "biolink:related_to"}', False, 61, 5, 1366955.0, ['CHEBI:6888'], 'biolink:Gene')
    result5 = Enrichment(2.512830362134677e-36, 'NCBIGene:154', '{"object_aspect_qualifier": "activity", "object_direction_qualifier": "increased", "predicate": "biolink:affects"}', False, 61, 1789,  1366955.0, ['18'], 'biolink:Gene')
    result6 = Enrichment(2.615464485693035e-36, 'NCBIGene:154',  '{"object_aspect_qualifier": "activity_or_abundance", "object_direction_qualifier": "increased", "predicate": "biolink:affects"}', False, 61, 1793,  1366955.0, ['18'], 'biolink:Gene')
    result7 = Enrichment(3.750524768721316e-27, 'NCBIGene:154', '{"predicate": "biolink:binds"}', True, 61, 746, 1366955.0, ['12'], 'biolink:Gene')
    result8 = Enrichment(1.3889291678789253e-34, 'NCBIGene:154', '{"predicate": "biolink:directly_physically_interacts_with"}', True, 61, 4, 1366955.0, ['15'], 'biolink:Gene')
    result9 = Enrichment(6.37300413954452e-37, 'NCBIGene:154',  '{"predicate": "biolink:interacts_with"}', False, 61, 4, 1366955.0, ['CHEBI:4463'], 'biolink:Gene')
    result10 = Enrichment(2.50950277122731e-31, 'NCBIGene:154', '{"predicate": "biolink:regulates"}', False, 61, 37, 1366955.0, ['9'], 'biolink:Gene')
    result11 = Enrichment(4.557847849630573e-36, 'NCBIGene:154', '{"object_direction_qualifier": "upregulates", "predicate": "biolink:regulates"}', False, 61, 7, 1366955.0, ['9'], 'biolink:Gene')
    result12 = Enrichment(8.924548060814318e-05, 'NCBIGene:154', '{"predicate": "biolink:increases_response_to"}', True, 61, 2, 1366955.0, ['CHEBI:4463'], 'biolink:Gene')
    result13 = Enrichment(1.0822387821668951e-14, 'NCBIGene:154', '{"object_aspect_qualifier": "molecular_interaction", "predicate": "biolink:affects"}', False, 61, 16, 1366955.0, ['4'], 'biolink:Gene')
    result14 = Enrichment(1.9435986995566893e-41, 'NCBIGene:154', '{"object_aspect_qualifier": "abundance", "predicate": "biolink:affects"}', False, 61, 48, 1366955.0, ['12'], 'biolink:Gene')
    result15 = Enrichment(5.402888231040584e-16, 'NCBIGene:154', '{"object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}', True, 61, 2, 1366955.0, ['8'], 'biolink:Gene')
    result16 = Enrichment(0.0004907515897535203, 'NCBIGene:154', '{"predicate": "biolink:affects_response_to"}', False, 61, 37, 1366955.0, ['1'], 'biolink:Gene')
    result17 = Enrichment(0.0007137408715038871, 'NCBIGene:154', '{"predicate": "biolink:affects"}', False, 61, 7, 1366955.0, ['16'], 'biolink:Gene')
    result18 = Enrichment(4.062152451583994e-11, 'NCBIGene:154', '{"object_aspect_qualifier": "molecular_interaction", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}', True, 61, 2, 1366955.0, ['3'], 'biolink:Gene')
    result19 = Enrichment(3.9824963795193066e-09, 'NCBIGene:154', '{"predicate": "biolink:positively_correlated_with"}', False, 61, 37, 1366955.0, ['9'], 'biolink:Gene')
    result20 = Enrichment(4.462373594297634e-05, 'NCBIGene:154', '{"object_aspect_qualifier": "localization", "object_direction_qualifier": "increased", "predicate": "biolink:affects"}', False, 61, 7, 1366955.0, ['1'], 'biolink:Gene')

    result = gc.filter_result_hierarchies([result1, result2, result3, result4, result5, result6, result7, result8, result9, result10, result11, result12, result13, result14, result15, result16, result17, result18, result19, result20])
    assert result9 in result
    assert result14 in result
    assert len(result) == 2

    print("All test cases passed!")


def test_streamline_children_to_parent():
    """
    There are mix if qualifier predicates and unqualified ones, in which there are dependencies amidst them
    group into the dependencies and pict the best p_valued predicate in each group until there is no dependencies
    amidst the final predicate set
    STEP 1:
        there are 4 main categories
            6 affects, 5 of them has aspects_qualifiers like: activity, abundance, activity_or_abundance, degradation
            binds
            2 interacts_with: directly_physically_interacts_with, interacts_with
            related_to
        All the 4 has top common ancestors which is "related_to"

    Step 2:
        Category 1: "affect_abundance" (1.5453909029914237e-18) has the best amongst other affects and compared to the overall ancestor
        Category 2: the overall ancestor - "related_to" is better than "binds"
        category 3: directly_physically_interacts_with (1.3682869515329492e-11) has better pvalue
        category 4: the overall ancestor (5.5909317582396114e-09) against itself

        This implies:
            Category 1: "affect_abundance" (1.5453909029914237e-18)
            category 3: directly_physically_interacts_with (1.3682869515329492e-11)
            category 4: the overall ancestor- related_to (5.5909317582396114e-09)



    Step 3:
        Now we compare inter categories:
            The overall ancestor - "related_to" is the least p_valued, hence
                Category 1: "affect_abundance" (1.5453909029914237e-18)
                category 3: directly_physically_interacts_with (1.3682869515329492e-11)
    Step 4:
        the two categories are not dependent on each other, so they are returned
    """
    chilren_to_parent_mapping = {'{"predicate": "biolink:directly_physically_interacts_with"}': {'{"predicate": "biolink:interacts_with"}'},
                                 '{"predicate": "biolink:binds"}': {'{"predicate": "biolink:related_to"}'},
                                 '{"object_aspect_qualifier": "activity_or_abundance", "predicate": "biolink:affects"}': {'{"predicate": "biolink:related_to"}'},
                                 '{"object_aspect_qualifier": "activity", "predicate": "biolink:affects"}': {'{"predicate": "biolink:related_to"}'},
                                 '{"object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}': {'{"predicate": "biolink:related_to"}'},
                                 '{"object_aspect_qualifier": "activity_or_abundance", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}': {'{"predicate": "biolink:related_to"}'},
                                 '{"predicate": "biolink:affects"}': {'{"predicate": "biolink:related_to"}'},
                                 '{"object_aspect_qualifier": "abundance", "predicate": "biolink:affects"}': {'{"predicate": "biolink:related_to"}'},
                                 '{"object_aspect_qualifier": "degradation", "predicate": "biolink:affects"}': {'{"predicate": "biolink:related_to"}'},
                                 '{"object_aspect_qualifier": "degradation", "object_direction_qualifier": "increased", "predicate": "biolink:affects"}': {'{"predicate": "biolink:related_to"}'}
                                 }
    pvalue_mapping = {'{"predicate": "biolink:directly_physically_interacts_with"}': 1.3682869515329492e-11,
                     '{"predicate": "biolink:interacts_with"}': 1.383372195529e-11,
                     '{"object_aspect_qualifier": "activity", "predicate": "biolink:affects"}': 3.262843218581081e-07,
                     '{"object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}': 3.2206484179349686e-07,
                     '{"object_aspect_qualifier": "activity_or_abundance", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}': 3.226250781949897e-07,
                     '{"predicate": "biolink:binds"}': 8.330611363906712e-09,
                     '{"predicate": "biolink:related_to"}': 5.5909317582396114e-09,
                     '{"object_aspect_qualifier": "activity_or_abundance", "predicate": "biolink:affects"}': 3.7195220929660993e-09,
                     '{"predicate": "biolink:affects"}': 0.0003159809536664026,
                     '{"object_aspect_qualifier": "abundance", "predicate": "biolink:affects"}': 1.5453909029914237e-18,
                     '{"object_aspect_qualifier": "degradation", "predicate": "biolink:affects"}': 3.51139263990654e-05,
                     '{"object_aspect_qualifier": "degradation", "object_direction_qualifier": "increased", "predicate": "biolink:affects"}': 2.3409421266829084e-05
                      }
    streamlined_set = streamline_children_to_parent(chilren_to_parent_mapping, pvalue_mapping)
    assert len(streamlined_set) == 2
    assert streamlined_set == {'{"object_aspect_qualifier": "abundance", "predicate": "biolink:affects"}',
                                '{"predicate": "biolink:directly_physically_interacts_with"}'}


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


