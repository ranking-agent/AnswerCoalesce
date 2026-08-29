import asyncio
from scipy.stats import hypergeom, binom, norm
from src.components import Enrichment
from src.graph_coalescence import duckdb_store
from src.util import LoggingUtil
import logging
import os
import json
import itertools
import orjson
import bmt

this_dir = os.path.dirname(os.path.realpath(__file__))

logger = LoggingUtil.init_logging('graph_coalescer', level=logging.WARNING, format='long', logFilePath=this_dir + '/')
tk = bmt.Toolkit()


def grouper(n, iterable):
    iterator = iter(iterable)
    while chunk := tuple(itertools.islice(iterator, n)):
        yield chunk


def filter_links_by_predicate(nodes_to_links, predicate_constraints, predicate_constraint_style, match_type="exact"):
    """Filter out links that don't meet the predicate constraints.

    predicate_constraints: list of dicts e.g. [{"predicate": "biolink:physically_interacts_with"}]
    predicate_constraint_style: "include" or "exclude"
    match_type:
        "exact"   - all keys and values in constraint must match link exactly
        "partial" - constraint predicate only needs to match link predicate key,
                    ignoring any additional qualifiers in the link

    Examples:
        Exact:   constraint {"predicate": "biolink:directly_physically_interacts_with"}
                 matches link {"predicate": "biolink:directly_physically_interacts_with"} only
        Partial: constraint {"predicate": "biolink:physically_interacts_with"}
                 matches link {"predicate": "biolink:physically_interacts_with",
                               "species_context_qualifier": "NCBITaxon:9606"}
    """
    if len(predicate_constraints) == 0:
        return nodes_to_links

    def matches_constraint(link_str, constraint, match_type):
        try:
            link_dict = json.loads(link_str)
        except (json.JSONDecodeError, TypeError):
            return False
        if match_type == "exact":
            # all keys and values must match exactly
            return all(link_dict.get(k) == v for k, v in constraint.items())
        elif match_type == "partial":
            # only match on predicate key, ignore additional qualifiers in link
            return link_dict.get("predicate") == constraint.get("predicate")
        return False

    new_nodes_to_links = {}
    for node, links in nodes_to_links.items():
        new_links = []
        for link in links:
            matched = any(
                matches_constraint(link[1], constraint, match_type)
                for constraint in predicate_constraints
            )
            if predicate_constraint_style == "include" and matched:
                new_links.append(link)
            elif predicate_constraint_style == "exclude" and not matched:
                new_links.append(link)
        new_nodes_to_links[node] = new_links

    return new_nodes_to_links


def filter_links_by_context(nodes_to_links, context_qualifiers):
    """Filter links to only those whose predicate JSON contains all the requested context qualifiers.

    context_qualifiers: dict of qualifier key-value pairs from the query, e.g.
        {"species_context_qualifier": "NCBITaxon:9606"}
    """
    if not context_qualifiers:
        return nodes_to_links
    new_nodes_to_links = {}
    for node, links in nodes_to_links.items():
        new_links = []
        for link in links:
            try:
                link_dict = orjson.loads(link[1])
            except (ValueError, TypeError):
                continue
            if all(link_dict.get(k) == v for k, v in context_qualifiers.items()):
                new_links.append(link)
        new_nodes_to_links[node] = new_links
    return new_nodes_to_links


def filter_links_by_node_type(nodes_to_links, node_constraints, link_node_types):
    """Filter out links that don't meet the node constraints
    node constraints is a list of acceptable node types for the returned nodes.  The node type of the other node
    in the links is used to determine if the link is kept.  Fortunately, link_node_types holds all of the superclasses
    of the node type, so we can just check if the link node type is in the set of acceptable types.

    Also, we want to filter out links that end up with block-list nodes
    """
    # These are trash curies that we never want to see
    blocklist = {"HP:0000118", "MONDO:0000001", "MONDO:0700096", "UMLS:C1333305", "CHEBI:24431", "CHEBI:23367",
                 "CHEBI:33579", "CHEBI:36357", "CHEBI:33675", "CHEBI:33302", "CHEBI:33304", "CHEBI:33582",
                 "CHEBI:25806", "CHEBI:50860", "CHEBI:51143", "CHEBI:32988", "CHEBI:33285", "CHEBI:33256",
                 "CHEBI:36962", "CHEBI:35352", "CHEBI:36963", "CHEBI:25367", "CHEBI:72695", "CHEBI:33595",
                 "CHEBI:33832", "CHEBI:37577", "CHEBI:24532", "CHEBI:5686", "NCBITaxon:9606"}

    # Collect the accepted types, which are any subclass of what gets passed into node constraints.
    # We're going to special case named thing - if that's in there, we just bypass all the type checks.
    accept_all_types = ("biolink:NamedThing" in node_constraints)

    new_nodes_to_links = {}
    for node, links in nodes_to_links.items():
        new_links = []
        for link in links:
            if isinstance(link, list) or isinstance(link, tuple):
                othernode = link[0]
            else:
                othernode = link
            if othernode in blocklist:
                continue
            if accept_all_types:
                new_links.append(link)
            else:
                # we have 2 lists: node constraints and link_node_types_othernode.  We want to see if there is any overlap
                # between the two lists.  If there is, then we want to keep the link.
                accepted_types = set(node_constraints) & set(link_node_types[othernode])
                if len(accepted_types) > 0:
                    new_links.append(link)
        new_nodes_to_links[node] = new_links

    return new_nodes_to_links


async def coalesce_by_graph(input_ids, input_node_type,
                            node_constraints=None, predicate_constraints=None, predicate_constraint_style="exclude",
                            pvalue_threshold=None, max_results=None, filter_predicate_hierarchies=False,
                            context_qualifiers=None, exclude_ids=None):
    """
    Given a list of input_ids, find nodes that are enriched.
    Return a list of Enrichment objects describing each enrichment.
    We don't want to muck this up with a bunch of TRAPI handling, this is purely about finding the
    enriched nodes.
    node_contraints and predicate_constraints can be used to limit the search.   Node constraints can be used
    to only allow the new node to be of a certain type.  Predicate constraints can be used to only allow certain
    predicates to be used in the enrichment or to exclude certain predicates. predicate_constraint_style can set to
    either "include" or "exclude". If "include" then only links that exactly match one constraint pattern are included.
    If "exclude" then any link matching an "exclude" constraint is excluded.
    Predicates should be of the form:
    {"predicate": "biolink:related_to", "object_aspect_qualifier": "activity", "constraint": "include|exclude"}
    By including or not including these constraints, coalesce_by_graph can be used by either an MCQ query or EDGAR.
    max_results determines if we want more answers than we started with, so we need to parameterize.
    filter_predicate_hierarchies is used by EDGAR to suppress excluded
    ancestors and prune redundant hierarchy results before linked-edge
    hydration.
    """
    logger.info(f'Start of processing.')
    if node_constraints is None:
        node_constraints = ["biolink:NamedThing"]
    if predicate_constraints is None:
        predicate_constraints = []
    hierarchy_exclusion_pairs = []
    if filter_predicate_hierarchies and predicate_constraint_style == "exclude":
        for constraint in predicate_constraints:
            if isinstance(constraint, dict):
                excluded_predicate = constraint.get("predicate")
            elif isinstance(constraint, str) and constraint.startswith("{"):
                excluded_predicate = orjson.loads(constraint).get("predicate")
            else:
                excluded_predicate = constraint
            if excluded_predicate:
                hierarchy_exclusion_pairs.extend(
                    (excluded_predicate, ancestor)
                    for ancestor in get_ancestors(excluded_predicate)
                )
    candidates, total_node_count = await asyncio.to_thread(
        duckdb_store.enrichment_candidates,
        input_ids,
        input_node_type,
        node_constraints=node_constraints,
        predicate_constraints=predicate_constraints,
        predicate_constraint_style=predicate_constraint_style,
        context_qualifiers=context_qualifiers,
        hierarchy_exclusion_pairs=hierarchy_exclusion_pairs,
        filter_predicate_hierarchies=filter_predicate_hierarchies,
        exclude_ids=exclude_ids,
        pvalue_threshold=pvalue_threshold,
        max_results=max_results,
    )

    ndraws = len(set(input_ids))
    enriched_links = []
    for candidate in candidates:
        newcurie_is_source = (
            True if candidate.is_symmetric else not candidate.member_is_subject
        )
        enriched_links.append(
            Enrichment(
                candidate.p_value,
                candidate.neighbor_curie,
                candidate.predicate_json,
                newcurie_is_source,
                ndraws,
                candidate.background_count,
                total_node_count,
                candidate.linked_curies,
                list(candidate.neighbor_categories),
            )
        )

    if exclude_ids:
        enriched_links = [
            enrichment
            for enrichment in enriched_links
            if enrichment.enriched_node.new_curie not in exclude_ids
        ]
    enriched_links.sort(
        key=lambda enrichment: (
            enrichment.p_value,
            enrichment.enriched_node.new_curie,
            enrichment.predicate,
            enrichment.is_source,
        )
    )

    if max_results:
        enriched_links = enriched_links[:max_results]

    nodetypedict = {
        candidate.neighbor_curie: list(candidate.neighbor_categories)
        for candidate in candidates
    }
    await asyncio.to_thread(augment_enrichments, enriched_links, nodetypedict)

    return enriched_links


def augment_enrichments(enriched_links, nodetypes):
    """Having found the set of enrichments we want to return, make sure that each enrichment has the node name and the node type."""
    enriched_curies = set([link.enriched_node.new_curie for link in enriched_links])
    nodenamedict = get_node_names(enriched_curies)
    for enrichment in enriched_links:
        enrichment.add_extra_node_name_and_label(nodenamedict, nodetypes)
    add_provs(enriched_links)


def add_provs(enrichments):
    all_edges = set()
    for enrichment in enrichments:
        all_edges.update(enrichment.get_prov_links())
    prov = duckdb_store.get_edge_provenance(all_edges)
    for enrichment in enrichments:
        enrichment.add_provenance(prov)


def get_node_types(unique_link_nodes):
    return duckdb_store.get_node_types(unique_link_nodes)


def get_node_names(unique_link_nodes):
    return duckdb_store.get_node_names(unique_link_nodes)


def create_nodes_to_links(allnodes, param_predicates=None, neighbor_ids=None):
    """Given a list of nodes identifiers, pull all their links
    If param_predicates is not empty, it should be a list of the same length as allnodes.
    It's use is in EDGAR where create_nodes_to_links is used in the final lookup step. In that case,
    we might be trying to run a bunch of rules at the same time and so the predicates will differ node to node.

    Note that we used to add inverted symmetric links to the results, but we no longer do that."""
    return duckdb_store.create_nodes_to_links(
        allnodes,
        param_predicates,
        neighbor_ids=neighbor_ids,
    )


def filter_result_hierarchies(results):
    enrichment_group_dict = {};

    for result in results:
        # Group results by enriched_node
        enrichment_group_dict.setdefault(result.enriched_node.new_curie, []).append(result)

    # Now filter by predicate hierarchies
    new_results = process_enrichment_group(enrichment_group_dict)

    return new_results


def process_enrichment_group(enrichment_group_dict):
    new_results = set()

    for enriched_node, enriched_results in enrichment_group_dict.items():
        # predicate_counts = {}
        #  if enriched_node == "HP:0001337": #or any node of interest
        #     #Copy the details to test_graph_coalesce.py to test the filter_result_hierarchies logic
        #     details = [(enriched_result.p_value, enriched_result.enriched_node.new_curie, enriched_result.predicate,
        #                 enriched_result.is_source, enriched_result.counts[0], enriched_result.counts[1],
        #                 enriched_result.counts[2], enriched_result.linked_curies,
        #                 enriched_result.enriched_node.newnode_type[0]) for enriched_result in enriched_results]
        #     for enriched_result in enriched_results:
        #         predicate = enriched_result.predicate
        #         if predicate in predicate_counts:
        #             predicate_counts[predicate] += 1
        #         else:
        #             predicate_counts[predicate] = 1
        #     A = 'Stop Over Here!!'
        #     print("WAIT!!!!! I wanna see the result")

        if len(enriched_results) == 1:
            new_results.update(enriched_results)
        else:
            # Re_group by p_value:
            p_value_group_dict = {}
            for enriched_result in enriched_results:
                p_value_group_dict.setdefault(enriched_result.p_value, []).append(enriched_result)

            # For each group, find the most specific predicates in each p_value group and put in specific results
            specific_results = get_specific_results(p_value_group_dict)

            # Pick the most specific in the specific results
            if len(specific_results) == 1:
                new_results.update(specific_results)
                continue
            # Else we pick the best representative of an enrichment node from the combined group result by min pvalue
            # OR Hierarchy again, Most especially if we can get further specificity
            # Filtering by predicate hierarchy and p_value scoring
            children_to_parent = children_parent_mapping(specific_results)
            pvalue_dict = {specific_result.predicate: specific_result.p_value for
                           specific_result in specific_results}
            most_preferred = streamline_children_to_parent(children_to_parent, pvalue_dict)

            for specific_result in specific_results:
                pred = specific_result.predicate
                if pred in most_preferred:
                    new_results.add(specific_result)
    return list(new_results)


def streamline_children_to_parent(children_to_parent, pvalues):
    """
    Given,
         pvalue_dict = {
                'biolink:contributes_to': 5.62677119993497e-16,
                'biolink:related_to': 6.984714344422767e-26,
                'biolink:treats_or_applied_or_studied_to_treat': 2.688166355839941e-06,
                'biolink:has_adverse_event': 2.8008696832786763e-17,
                'biolink:causes': 3.9591314521010225e-08
        }

    And child-parent dependencies between the predicates, we want to choose the one with best predicate in each case

        children_to_parent_dict = {
            'biolink:causes': {'biolink:contributes_to', 'biolink:related_to'},
            'biolink:contributes_to': {'biolink:related_to'},
            'biolink:has_adverse_event': {'biolink:related_to'}
        }

    since `biolink:related_to` has the best pvalue compared with the key,value pair in each item

    Then our results returns:
            {'biolink:related_to'}

    """
    streamlined_set = set()
    items_to_remove = set()

    # Let's gather all unique predicates from children_to_parent and their children
    all_keys = set(children_to_parent.keys())
    for children in children_to_parent.values():
        all_keys.update(children)

    # Get the p-values
    pvalue_lookup = {key: pvalues.get(key, float('inf')) for key in all_keys}

    # Streamline the children_to_parent dictionary
    for child, parents in list(children_to_parent.items()):
        if parents:
            # Select the element with the smallest p-value
            best_element = min([child] + list(parents), key=lambda x: pvalue_lookup[x])
            streamlined_set.add(best_element)
            continue
        # If a child has no parents, it needs to be compared with others
        candidates = set()
        for other_child, other_parents in children_to_parent.items():
            candidates.add(other_child)
            candidates.update(other_parents)
        candidates = candidates - items_to_remove
        grouping = group_by_predicate(candidates).get(orjson.loads(child).get("predicate"), [])
        if len(grouping) == 1 and child == grouping[0]:
            streamlined_set.add(child)
            items_to_remove.add(child)
        if len(grouping) > 1:
            best_element = min(grouping, key=lambda x: pvalue_lookup[x])
            streamlined_set.add(best_element)
            items_to_remove.update(grouping)

    # # Remove items marked for deletion, if it exists
    # for item in items_to_remove:
    #     del children_to_parent[item]

    if len(streamlined_set) == 1:
        return streamlined_set

    # Check to be sure the set aren't dependent on each other
    if len(streamlined_set) == 2:
        streamlist = list(streamlined_set)
        if streamlist[0] in children_to_parent.get(streamlist[1], []):
            # 0 is the parent but return the one with least pvalue
            if pvalues.get(streamlist[0]) < pvalues.get(streamlist[1]):
                return {streamlist[0]}
            else:
                return {streamlist[1]}
        elif streamlist[1] in children_to_parent.get(streamlist[0], []):
            # 1 is the parent but return the one with least pvalue
            if pvalues.get(streamlist[1]) < pvalues.get(streamlist[0]):
                return {streamlist[1]}
            else:
                return {streamlist[0]}
        else:
            streamlist0_pred_only = orjson.loads(streamlist[0]).get('predicate')
            streamlist1_pred_only = orjson.loads(streamlist[1]).get('predicate')
            # For the last time:
            if streamlist0_pred_only in get_ancestors(streamlist1_pred_only):
                if pvalues.get(streamlist[0]) < pvalues.get(streamlist[1]):
                    return {streamlist[0]}
                else:
                    return {streamlist[1]}
            if streamlist1_pred_only in get_ancestors(streamlist0_pred_only):
                if pvalues.get(streamlist[1]) < pvalues.get(streamlist[0]):
                    return {streamlist[1]}
                else:
                    return {streamlist[0]}
            # None is the parent of the other
            return streamlined_set

    if len(streamlined_set) > 2:
        new_children_to_parent = children_parent_mapping(list(streamlined_set))
        if new_children_to_parent == children_to_parent:
            return streamlined_set
        return streamline_children_to_parent(new_children_to_parent, pvalues)

    return streamlined_set


def group_by_predicate(items):
    """
    groups a list of predicate strings by the predicate only
    """
    grouped_items = {}

    for item in items:
        parsed_item = json.loads(item)
        predicate = parsed_item.get('predicate')

        if predicate not in grouped_items:
            grouped_items[predicate] = []
        grouped_items[predicate].append(item)

    return grouped_items


def children_parent_mapping(specific_results):
    def merge_dict(d):
        """
        For each key-value pair, check if any of the values are keys in the dictionary.
        If they are, merge their value sets and mark the key for removal.
        """
        # Make a new dictionary to merge all the items results
        merged_dict = {key: set(values) for key, values in d.items()}

        merging_needed = True
        while merging_needed:
            merging_needed = False
            keys_to_remove = set()
            temp_dict = {}

            for key, values in merged_dict.items():
                # W need a temporary set to avoid modifying the original set during iteration
                new_values = set(values)
                for value in values:
                    if value in merged_dict:
                        # Merge the value's set into the new set
                        new_values.update(merged_dict[value])
                        # Mark the key for removal
                        keys_to_remove.add(value)
                        # Mark merging as needed
                        merging_needed = True

                temp_dict[key] = new_values

            # Let's update the merged dictionary with the temporary dictionary
            merged_dict.update(temp_dict)

            # Then remove the merged keys
            for key in keys_to_remove:
                if key in merged_dict:
                    del merged_dict[key]

        return merged_dict

    children_to_parent = {}

    def bare_pred(full_predicate_str):
        return orjson.loads(full_predicate_str).get("predicate")

    # Map bare predicate -> set of full predicate strings that share it
    bare_to_full = {}
    for result in specific_results:
        pred = result if isinstance(result, str) else result.predicate
        bp = bare_pred(pred)
        bare_to_full.setdefault(bp, set()).add(pred)

    current_predicate = specific_results[0] if isinstance(specific_results[0], str) else specific_results[0].predicate

    for j in range(1, len(specific_results)):
        next_predicate = specific_results[j] if isinstance(specific_results[j], str) else specific_results[j].predicate

        if bare_pred(current_predicate) in get_ancestors(bare_pred(next_predicate)):
            children_to_parent.setdefault(next_predicate, set()).add(current_predicate)

        elif bare_pred(next_predicate) in get_ancestors(bare_pred(current_predicate)):
            children_to_parent.setdefault(current_predicate, set()).add(next_predicate)

        current_predicate = next_predicate

    allowable_predicates = {specific_result if isinstance(specific_results[0], str) else specific_result.predicate for
                            specific_result in specific_results}

    # Case where there are some misses; we need to somehow figure out how to store it in the children_to_parent_dict
    for result in specific_results:
        pred = result if isinstance(result, str) else result.predicate
        if pred in children_to_parent:
            continue
        if any(pred in values for values in children_to_parent.values()):
            continue
        pred_ancestors = get_ancestors(bare_pred(pred))
        if pred_ancestors:
            # Find allowable predicates whose bare predicate is an ancestor
            matching = set()
            for ap in allowable_predicates:
                if bare_pred(ap) in pred_ancestors:
                    matching.add(ap)
            children_to_parent[pred] = matching
        else:
            pred_children = get_children(bare_pred(pred))
            if pred_children:
                matching = set()
                for ap in allowable_predicates:
                    if bare_pred(ap) in pred_children:
                        matching.add(ap)
                for pred_child in matching:
                    if pred_child in children_to_parent:
                        children_to_parent.setdefault(pred_child, set()).add(pred)
            else:
                children_to_parent.setdefault(pred, set()).add(pred)

    return merge_dict(children_to_parent)


def is_child_in(child, parent, qualifier_enum):
    """Eg: activity_or_abundance is used in cases where the specificity of the relationship can not be determined to be either activity or abundance.
    In general, a more specific value from this enumeration should be used, if it is present in the result being filtered.
    """
    children = tk.get_permissible_value_children(parent, qualifier_enum) or []
    return child in children


def has_qualifier(predicate):
    # https://biolink.github.io/biolink-model/qualifiers.html
    qualifiers = {"object_aspect_qualifier", "object_direction_qualifier"}
    return any(q in predicate for q in qualifiers)


def get_ancestors(predicate):
    return tk.get_ancestors(predicate, formatted=True, reflexive=False) or []


def get_children(predicate):
    return tk.get_children(predicate, formatted=True) or []


# def get_specific_results(pvalue_group_dict):
#     """
#     This function accepts:
#         enrichment result grouped by pvalue, and most-likely, different predicates
#         for instance:
#                 0.0001: [(enriched_node1, causes), (enriched_node1, contributes_to)]
#                 0.0002: [(enriched_node1, has_advert_event), (enriched_node1, affects)]
#                 0.0003: [(enriched_node1, treats_or_applied_or_studied_to_treat), (enriched_node1, treats)]
#     to return specific list representative of enriched_node1:
#                 [(enriched_node1, causes),(enriched_node1, has_advert_event), (enriched_node1, treats)]
#
#     NB: No scoring is performed since each group compared shares the same p_value
#     """
#     # https://biolink.github.io/biolink-model/#enumerations
#     biolink_aspect_qualifier_enumeration = "GeneOrGeneProductOrChemicalEntityAspectEnum"
#
#     specific_results = []
#
#     for results in pvalue_group_dict.values():
#         if len(results) == 1:
#             specific_results.extend(results)
#             continue
#
#         most_specific_result = results[0]
#
#         for j in range(1, len(results)):
#             result_i = most_specific_result
#             result_j = results[j]
#
#             pred_i = orjson.loads(result_i.predicate)
#             pred_j = orjson.loads(result_j.predicate)
#
#             if pred_i.get("predicate") == pred_j.get("predicate"):
#                 # Equal predicates? then lets dig further down to the qualifier
#                 if any("qualifier" in key for key in pred_i) or any("qualifier" in key for key in pred_j):
#                     c_pred = pred_i
#                     n_pred = pred_j
#
#                     curr_qualifier = c_pred.get("object_aspect_qualifier") or c_pred.get("object_direction_qualifier")
#                     next_qualifier = n_pred.get("object_aspect_qualifier") or n_pred.get("object_direction_qualifier")
#
#                     if curr_qualifier and next_qualifier:
#                         if curr_qualifier == next_qualifier:
#                             if ("object_direction_qualifier" in c_pred) != ("object_direction_qualifier" in n_pred):
#                                 most_specific_result = result_i if "object_direction_qualifier" in c_pred else result_j
#
#                         elif is_child_in(curr_qualifier, next_qualifier, biolink_aspect_qualifier_enumeration):
#                             most_specific_result = result_i
#
#                         elif is_child_in(next_qualifier, curr_qualifier, biolink_aspect_qualifier_enumeration):
#                             most_specific_result = result_j
#
#                     elif has_qualifier(c_pred) and not has_qualifier(n_pred):
#                         most_specific_result = result_i
#
#                     elif has_qualifier(n_pred) and not has_qualifier(c_pred):
#                         most_specific_result = result_j
#
#                 else:
#                     most_specific_result = results[0]
#
#             else:
#                 top_ancestral_result = max([result_i, result_j], key=lambda result: len(
#                     get_ancestors(orjson.loads(result.predicate).get("predicate"))))
#                 most_specific_result = top_ancestral_result
#
#         specific_results.append(most_specific_result)
#
#     return specific_results


def get_specific_results(pvalue_group_dict):
    """
    This function accepts:
        enrichment result grouped by pvalue, and most-likely, different predicates
        for instance:
                0.0001: [(enriched_node1, causes), (enriched_node1, contributes_to)]
                0.0002: [(enriched_node1, has_advert_event), (enriched_node1, affects)]
                0.0003: [(enriched_node1, treats_or_applied_or_studied_to_treat), (enriched_node1, treats)]
    to return specific list representative of enriched_node1:
                [(enriched_node1, causes),(enriched_node1, has_advert_event), (enriched_node1, treats)]

    NB: No scoring is performed since each group compared shares the same p_value
    """
    # https://biolink.github.io/biolink-model/#enumerations
    biolink_aspect_qualifier_enumeration = "GeneOrGeneProductOrChemicalEntityAspectEnum"
    biolink_direction_qualifier_enumeration = "DirectionQualifierEnum"

    specific_results = []

    for results in pvalue_group_dict.values():
        if len(results) == 1:
            specific_results.extend(results)
            continue

        most_specific_result = results[0]

        for j in range(1, len(results)):
            result_i = most_specific_result
            result_j = results[j]

            pred_i = orjson.loads(result_i.predicate)
            pred_j = orjson.loads(result_j.predicate)

            if pred_i.get("predicate") == pred_j.get("predicate"):
                # Equal predicates? then lets dig further down to the qualifier
                if any("qualifier" in key for key in pred_i) or any("qualifier" in key for key in pred_j):
                    c_pred = pred_i
                    n_pred = pred_j

                    # Handle ASPECT qualifiers separately from DIRECTION qualifiers
                    curr_aspect = c_pred.get("object_aspect_qualifier")
                    next_aspect = n_pred.get("object_aspect_qualifier")
                    curr_direction = c_pred.get("object_direction_qualifier")
                    next_direction = n_pred.get("object_direction_qualifier")

                    # Compare aspect qualifiers (if both have them)
                    if curr_aspect and next_aspect:
                        if curr_aspect == next_aspect:
                            # Same aspect, prefer the one with direction qualifier
                            if curr_direction and not next_direction:
                                most_specific_result = result_i
                            elif next_direction and not curr_direction:
                                most_specific_result = result_j
                            # Both have or both lack direction - keep current
                        else:
                            # Different aspects - check hierarchy
                            try:
                                if is_child_in(curr_aspect, next_aspect, biolink_aspect_qualifier_enumeration):
                                    most_specific_result = result_i
                                elif is_child_in(next_aspect, curr_aspect, biolink_aspect_qualifier_enumeration):
                                    most_specific_result = result_j
                            except ValueError:
                                # If enum lookup fails, keep current
                                pass

                    # Compare direction qualifiers (if both have them and no aspect difference)
                    elif curr_direction and next_direction:
                        if curr_direction != next_direction:
                            try:
                                if is_child_in(curr_direction, next_direction, biolink_direction_qualifier_enumeration):
                                    most_specific_result = result_i
                                elif is_child_in(next_direction, curr_direction, biolink_direction_qualifier_enumeration):
                                    most_specific_result = result_j
                            except ValueError:
                                # If enum lookup fails, keep current
                                pass

                    # One has qualifier, one doesn't - prefer the one with qualifier
                    elif (curr_aspect or curr_direction) and not (next_aspect or next_direction):
                        most_specific_result = result_i
                    elif (next_aspect or next_direction) and not (curr_aspect or curr_direction):
                        most_specific_result = result_j

                else:
                    most_specific_result = results[0]

            else:
                top_ancestral_result = max([result_i, result_j], key=lambda result: len(
                    get_ancestors(orjson.loads(result.predicate).get("predicate"))))
                most_specific_result = top_ancestral_result

        specific_results.append(most_specific_result)

    return specific_results
