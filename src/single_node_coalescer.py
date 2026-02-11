from collections import defaultdict
from itertools import chain
import logging
import orjson
import time

from src.property_coalescence.property_coalescer import coalesce_by_property, lookup_nodes_by_properties
from src.graph_coalescence.graph_coalescer import coalesce_by_graph, create_nodes_to_links, get_node_types, \
    filter_links_by_node_type, get_node_names, add_provs

from src.scoring import pvalue_to_sigmoid, combine_rule_pvalues_to_score
from src.components import MCQDefinition, Lookup, NewEdge, QueryParams, InferenceParams, EnrichmentResult, \
    EnrichmentType

from src.trapi import create_knowledge_graph_edge, create_knowledge_graph_edge_from_component, \
    create_knowledge_graph_node, add_node_to_knowledge_graph, add_edge_to_knowledge_graph, add_auxgraph_for_enrichment, \
    add_enrichment_edge, add_enrichment_result, add_member_of_klat, EGARTRAPIBuilder, prune_message

logger = logging.getLogger(__name__)
role_predicate = "biolink:has_chemical_role"
INFORES = "infores:answercoalesce"


######################################
# Entry Points
###################################

async def multi_curie_query(in_message, parameters):
    """Takes a TRAPI multi-curie query and returns a TRAPI multi-curie answer."""
    # Get the list of nodes that you want to enrich:
    mcq_definition = MCQDefinition(in_message)
    enrichment_results = await coalesce_by_graph(mcq_definition.group_node.curies,
                                                 mcq_definition.group_node.semantic_type,
                                                 node_constraints=mcq_definition.enriched_node.semantic_types,
                                                 predicate_constraints=[mcq_definition.edge.predicate],
                                                 predicate_constraint_style="include",
                                                 pvalue_threshold=parameters["pvalue_threshold"],
                                                 result_length=parameters["result_length"])
    return await create_mcq_trapi_response(in_message, enrichment_results, mcq_definition)


async def infer(in_message: dict) -> dict:
    """
    Takes a TRAPI infer query and returns a TRAPI infer answer.
    """
    builder = EGARTRAPIBuilder(in_message)
    import time

    try:
        # 1. Parse query parameters
        params = QueryParams.from_message(in_message)
        if not params:
            builder.log_error("No curie specified or invalid query structure")
            return in_message

        inf_params = InferenceParams.from_message(in_message)

        # 2. Initial lookup
        lookup_start = time.time()
        try:
            lookup_results = lookup_single(
                params.curie,
                params.predicate_parts,
                params.is_source,
                params.output_semantic_type
            )
        except Exception as e:
            builder.log_error(
                f"Lookup failed: {str(e)}",
                metadata={"timing_seconds": round(time.time() - lookup_start, 3)}
            )
            logger.exception(f"Lookup failed for {params.curie}")
            return in_message

        if not lookup_results or not lookup_results.link_ids:
            builder.log_error(
                f"No lookup results found for {params.curie}",
                metadata={"timing_seconds": round(time.time() - lookup_start, 3)}
            )
            ensure_empty_results(in_message)
            return in_message

        # LOG LOOKUP SUCCESS
        builder.log("Lookup stage complete", level="INFO",
                    metadata={"total_lookups": len(lookup_results.link_ids),
                              "timing_seconds": round(time.time() - lookup_start, 3)
                              }
                    )
        logger.info(f"Found {len(lookup_results.link_ids)} lookup results for {params.curie}")

        # 3 & 4. ENRICHMENT
        enrichment_start = time.time()

        async def safe_graph_enrichment():
            try:
                return await coalesce_by_graph(
                    lookup_results.link_ids,
                    params.output_semantic_type,
                    node_constraints=inf_params.node_constraints,
                    predicate_constraint_style=inf_params.predicate_constraint_style,
                    predicate_constraints=inf_params.predicate_constraints,
                    pvalue_threshold=inf_params.pvalue_threshold,
                    filter_predicate_hierarchies=True
                )
            except Exception as e:
                builder.log_error(f"Graph enrichment failed: {str(e)}")
                logger.exception("Graph enrichment failed")
                return []

        async def safe_property_enrichment():
            try:
                return await coalesce_by_property(
                    lookup_results.link_ids,
                    params.output_semantic_type,
                    property_constraints=inf_params.property_constraints,
                    pvalue_threshold=inf_params.pvalue_threshold
                )
            except Exception as e:
                builder.log_error(f"Property enrichment failed: {str(e)}")
                logger.exception("Property enrichment failed")
                return []

        import asyncio
        graph_enrichment_results, property_enrichment_results = await asyncio.gather(
            safe_graph_enrichment(),
            safe_property_enrichment()
        )

        all_enrichments = unify_enrichments(graph_enrichment_results, property_enrichment_results)

        if not all_enrichments:
            builder.log_error("No enrichment results from graph or property analysis",
                               metadata={"timing_seconds": round(time.time() - enrichment_start, 3)}
                               )
            ensure_empty_results(in_message)
            return in_message

        exclude_ids = set(lookup_results.link_ids) | {params.curie}
        filtered_enrichments = filter_enrichments(
            all_enrichments,
            exclude_ids=exclude_ids,
            max_rules=inf_params.rule_length
        )

        if not filtered_enrichments:
            builder.log_error("No enrichment results after filtering",
                              metadata={"timing_seconds": round(time.time() - enrichment_start, 3)})
            ensure_empty_results(in_message)
            return in_message

        # LOG ENRICHMENT SUCCESS
        enrichment_pvalues = [e.p_value for e in filtered_enrichments]
        builder.log("Enrichment stage complete", level="INFO",
                    metadata={"total_enrichments": len(filtered_enrichments),
                              "graph_enrichments": len([e for e in filtered_enrichments if e.enrichment_type == EnrichmentType.GRAPH]),
                              "property_enrichments": len([e for e in filtered_enrichments if e.enrichment_type == EnrichmentType.PROPERTY]),
                              "pvalue_stats": {"min": float(min(enrichment_pvalues)), "max": float(max(enrichment_pvalues))},
                              "unique_enriched_nodes": len(set(e.enriched_id for e in filtered_enrichments)), "timing_seconds": round(time.time() - enrichment_start, 3)
                              }
                    )
        logger.info(f"Found {len(filtered_enrichments)} enrichments after filtering")

        # 6. INFERENCE LOOKUP
        inference_start = time.time()
        try:
            graph_inferred_results, property_inferred_results = await run_inference_lookup(filtered_enrichments, params)
        except Exception as e:
            builder.log_error(f"Inference lookup failed: {str(e)}", metadata={"timing_seconds": round(time.time() - inference_start, 3)})
            logger.exception("Inference lookup failed")
            ensure_empty_results(in_message)
            return in_message

        if not graph_inferred_results and not property_inferred_results:
            builder.log_error("No inferred results found", metadata={"timing_seconds": round(time.time() - inference_start, 3)})
            ensure_empty_results(in_message)
            return in_message

        # LOG INFERENCE SUCCESS
        unique_graph_inferred = set()
        for enrichment, inferred_result in graph_inferred_results:
            unique_graph_inferred.update(
                link.link_id for link in inferred_result.lookup_links
                if link.link_id not in lookup_results.link_ids  # Exclude original lookups
            )

        unique_property_inferred = set()
        for prop, inferred_data in property_inferred_results.items():
            unique_property_inferred.update(
                link_id for link_id in inferred_data.get("lookup_links", [])
                if link_id not in lookup_results.link_ids  # Exclude original lookups
            )

        total_graph_inferences = sum(len(inferred_result.lookup_links) for _, inferred_result in graph_inferred_results)
        total_property_inferences = sum(len(inferred_data.get("lookup_links", [])) for inferred_data in property_inferred_results.values())

        builder.log("Inference lookup complete", level="INFO",
                    metadata={"total_inferences": total_graph_inferences + total_property_inferences,
                              "unique_inferred_nodes": len(unique_graph_inferred | unique_property_inferred),
                              "graph_inferences": {"total": total_graph_inferences, "unique": len(unique_graph_inferred), "enrichments_used": len(graph_inferred_results)},
                              "property_inferences": {"total": total_property_inferences, "unique": len(unique_property_inferred), "enrichments_used": len(property_inferred_results)},
                              "timing_seconds": round(time.time() - inference_start, 3)
                              }
                    )

        # 7. BUILD RESPONSE
        build_start = time.time()
        build_edgar_response(
            builder, params, lookup_results, filtered_enrichments,
            graph_inferred_results, property_inferred_results,
            result_length=inf_params.result_length
        )

        # LOG BUILD SUCCESS
        builder.log("Response build complete", level="INFO", metadata={"timing_seconds": round(time.time() - build_start, 3)})

        logger.info(f"Built response with {len(builder.results)} results")

        return in_message

    except Exception as e:
        builder.log_error(f"Unexpected error in inference pipeline: {str(e)}")
        logger.exception("Unexpected error in inference pipeline")
        ensure_empty_results(in_message)
        return in_message


def lookup_single(curie: str, predicate_parts: str, is_source: bool,
                  output_semantic_type: str) -> Lookup | None:
    """
    Look up direct connections for a single curie.

    Returns a Lookup object with:
    - link_ids: List of connected node IDs
    - lookup_links: List of Lookup_Links with node info and edges
    """
    link_ids = create_nodes_to_links([curie], param_predicates=[predicate_parts])
    link_ids = {node: links for node, links in link_ids.items() if links}

    if not link_ids:
        return None

    all_ids = list(chain.from_iterable(link_ids.values())) + [curie]
    all_node_names = get_node_names(all_ids)
    all_node_types = get_node_types(all_ids)

    # Filter by output semantic type and create Lookup object
    for curie_node, id_links in link_ids.items():
        filtered = filter_links_by_node_type(
            {curie_node: id_links},
            [output_semantic_type],
            all_node_types
        )
        for node, links in filtered.items():
            lookup = Lookup(
                node, predicate_parts, is_source,
                all_node_names, all_node_types, links,
                output_semantic_type
            )
            add_provs([lookup])
            return lookup

    return None


async def run_inference_lookup(enrichments: list[EnrichmentResult], params: QueryParams) -> tuple[list, dict]:
    """
    Run second lookup from enriched nodes to find inferred results.

    Graph and property inference run IN PARALLEL for better performance.

    Returns:
        graph_inferred: List of tuples (EnrichmentResult, Lookup) to preserve context
        property_inferred: Dict from property_coalescer
    """
    import asyncio

    # Separate by type
    graph_enrichments = [e for e in enrichments if e.enrichment_type == EnrichmentType.GRAPH]
    property_enrichments = [e for e in enrichments if e.enrichment_type == EnrichmentType.PROPERTY]

    async def process_graph_inference():
        """Process graph enrichments to find inferred nodes"""
        graph_inferred = []

        for enrichment in graph_enrichments:
            link_ids = create_nodes_to_links([enrichment.enriched_id], param_predicates=[enrichment.predicate])
            link_ids = {node: links for node, links in link_ids.items() if links}

            if not link_ids:
                continue

            all_ids = list(chain.from_iterable(link_ids.values())) + [enrichment.enriched_id]
            all_node_names = get_node_names(all_ids)
            all_node_types = get_node_types(all_ids)

            for curie_node, id_links in link_ids.items():
                filtered = filter_links_by_node_type(
                    {curie_node: id_links},
                    [params.output_semantic_type],
                    all_node_types
                )
                for node, links in filtered.items():
                    lookup = Lookup(
                        node, enrichment.predicate, False,
                        all_node_names, all_node_types, links,
                        params.output_semantic_type
                    )
                    add_provs([lookup])
                    graph_inferred.append((enrichment, lookup))

        return graph_inferred

    async def process_property_inference():
        """Process property enrichments to find inferred nodes"""
        if not property_enrichments:
            return {}

        prop_dicts = [
            {
                "enriched_property": e.enriched_id,
                "p_value": e.p_value,
                "linked_curies": e.linked_curies,
                "counts": list(e.counts)
            }
            for e in property_enrichments
        ]
        property_inferred, nodeset = lookup_nodes_by_properties(
            prop_dicts,
            params.output_semantic_type,
            return_nodeset=True
        )
        node_names = get_node_names(nodeset)
        for prop, data in property_inferred.items():
            data["lookup_names"] = [node_names.get(link) for link in data.get("lookup_links", [])]

        return property_inferred

    # Run both inference lookups in parallel
    graph_inferred, property_inferred = await asyncio.gather(
        process_graph_inference(),
        process_property_inference()
    )

    return graph_inferred, property_inferred


######################################
# ENRICHMENT FUNCTIONS
###################################

async def property_enrich(input_ids, params, parameters):
    """Given a list of ids, find the property based enrichments for each.  Returns a list of enrichments.  Each
     enrichment is a dictionary with the form:
     {
        "enriched_property": curie,
        "attached_nodes": the list of input curies that have direct edges to the enriched_node,
        "enrichment_attributes": the p-value and other stats for the enrichment
     }
     """
    # TODO: Ola to implement based on coalesce
    enrichment_results = await coalesce_by_property(input_ids,
                                                    params.output_semantic_type,
                                                    property_constraints=[],
                                                    pvalue_threshold=parameters.get("pvalue_threshold", 1e-6),
                                                    )
    # chk_best_rule = {}
    # for i, result in enumerate(enrichment_results):
    #     # Group results by enriched_node
    #     chk_best_rule.setdefault(result["enriched_property"], []).append((role_predicate, result["p_value"]))
    # print("++++++++++++++++++")
    # print(" P After: ", len(chk_best_rule))
    # print("++++++++++++++++++")
    # with open('HP0003637DrugfilteredPrule_to_use.json', 'w') as json_file:
    #     json.dump(chk_best_rule, json_file, indent=4)
    return enrichment_results


async def create_mcq_trapi_response(in_message, enrichment_results, mcq_definition):
    """Create a TRAPI multi-curie answer. Go out and get the provenance or other features as needed.
    in_message: the original TRAPI message in dict form
    enrichment_results: the enriched nodes and edges
    input_qnode_id: the id of the input node.
    """
    # We need to have knowledge_graph edges for member_of the inputs (if they don't already exist).
    # We will also need access to those edges by result node to create the auxiliary graphs.
    member_of_edges = await create_or_find_member_of_edges_and_nodes(in_message, mcq_definition)
    for enrichment in enrichment_results:
        await create_result_from_enrichment(in_message, enrichment, member_of_edges, mcq_definition)
    return in_message


async def create_result_from_enrichment(in_message, enrichment, member_of_edges, mcq_definition):
    """
     Each enrichment is a result.  For each enrichment we need to
     1. (possibly) add the new node to the knowledge graph
     2. Add the edges between the new node and the member nodes to the knowledge graph
     3. Create an auxiliary graph for each element of the member_id consisting of the edge from the member_id to the new node
        and the member_of edge connecting the member_id to the input node.
     4. Add the inferred edge from the new node to the input uuid to the knowledge graph
     5. Add the auxiliary graphs created above to the inferred edge
     6. Create a new result
     7. In the result, create the node_bindings
     8. In the result, create the analysis and add edge_bindings to it.
     """
    # 1.(possibly) add the new node to the knowledge graph
    node = create_knowledge_graph_node(enrichment.enriched_node.new_curie, enrichment.enriched_node.newnode_type,
                                       enrichment.enriched_node.newnode_name)
    add_node_to_knowledge_graph(in_message, enrichment.enriched_node.new_curie, node)
    aux_graph_ids = []
    for edge in enrichment.links:
        # 2. Add the edges between the new node and the member nodes to the knowledge graph
        trapi_edge = create_knowledge_graph_edge_from_component(edge)
        direct_edge_id = add_edge_to_knowledge_graph(in_message, edge=trapi_edge)
        # 3. Create an auxiliary graph for each element of the member_id consisting of the edge from the member_id to the new node
        aux_graph_id = add_auxgraph_for_enrichment(in_message, direct_edge_id, member_of_edges,
                                                   enrichment.enriched_node.new_curie)
        aux_graph_ids.append(aux_graph_id)
    # 4. Add the inferred edge from the new node to the input uuid to the knowledge graph and
    # 5. Add the auxiliary graphs created above to the inferred edge
    enrichment_kg_edge_id = add_enrichment_edge(in_message, enrichment, mcq_definition, aux_graph_ids)
    # 6. Create a new result
    # 7. In the result, create the node_bindings
    # 8. In the result, create the analysis and add edge_bindings to it.
    # 9. Make a score out of the enrichment pvalue
    enrichment_pval = pvalue_to_sigmoid(enrichment.p_value, scale=0.5, shift=5)
    add_enrichment_result(in_message, enrichment.enriched_node, enrichment_pval, enrichment_kg_edge_id, mcq_definition)


async def create_or_find_member_of_edges_and_nodes(in_message, mcq_definition):
    """Create or find the member_of edges for the input nodes from the member_ids element of input_qnode_id.
    Return a dictionary of the form
    { input_curie: edge_id }"""
    # get input qnode id
    input_qnode_id = mcq_definition.group_node.qnode_id
    # Get the member_ids
    member_ids = mcq_definition.group_node.curies
    # Get the id of the input_qnode
    input_qnode_uuid = mcq_definition.group_node.uuid
    # Loop over the knowledge graph edges and find the member_of edges that have the input_qnode_uuid
    # as the object. Add them to a member_of_edges dictionary with the subject of the edge as the key.
    member_of_edges = {}
    for edge_id, edge in in_message['message'].get('knowledge_graph', {}).get('edges', {}).items():
        if edge['object'] == input_qnode_uuid:
            member_of_edges[edge['subject']] = edge_id
    # Now loop over the member_ids and add any that are not in the member_of_edges to the knowledge graph
    # and add them to the member_of_edges dictionary.
    for member_id in member_ids:
        if member_id not in member_of_edges:
            edge_id = f"e_{member_id}_member_of_{'_'.join(input_qnode_uuid.split(':'))}"
            new_edge = create_knowledge_graph_edge(member_id, input_qnode_uuid, "biolink:member_of")
            add_member_of_klat(new_edge)
            add_edge_to_knowledge_graph(in_message, new_edge, edge_id)
            member_of_edges[member_id] = edge_id
    # We also want to make sure that all the member_ids are in the knowledge graph as nodes.
    for member_id in member_ids:
        if member_id not in in_message['message'].get('knowledge_graph', {}).get('nodes', {}):
            new_node = create_knowledge_graph_node(member_id, mcq_definition.group_node.semantic_type)
            add_node_to_knowledge_graph(in_message, member_id, new_node)
    return member_of_edges


def unify_enrichments(graph_results: list, property_results: list[dict]) -> list[EnrichmentResult]:
    """
    Convert both enrichment types to unified EnrichmentResult format.

    Args:
        graph_results: List of legacy Enrichment objects from coalesce_by_graph
        property_results: List of dicts from coalesce_by_property

    Returns:
        List of unified EnrichmentResult objects
    """
    unified = []

    # Convert graph enrichments
    for gr in (graph_results or []):
        try:
            unified.append(EnrichmentResult.from_graph_enrichment(gr))
        except Exception as e:
            logger.warning(f"Failed to convert graph enrichment: {e}")

    # Convert property enrichments
    for pr in (property_results or []):
        try:
            unified.append(EnrichmentResult.from_property_enrichment(pr))
        except Exception as e:
            logger.warning(f"Failed to convert property enrichment: {e}")

    return unified


def filter_enrichments(enrichments: list[EnrichmentResult], exclude_ids: set[str], max_rules=None) -> list[EnrichmentResult]:
    """
    Filter enrichments by p-value threshold and excluded IDs.
    Returns:
        Filtered and sorted list of EnrichmentResult objects
    """
    filtered = [e for e in enrichments if e.enriched_id not in exclude_ids]

    # Sort by p-value (most significant first)
    filtered.sort(key=lambda x: x.p_value)

    if max_rules is not None:
        filtered = filtered[:max_rules]

    return filtered


def group_enrichments_by_type(enrichments: list[EnrichmentResult]) -> dict[EnrichmentType, list[EnrichmentResult]]:
    """Group enrichments by their type (graph vs property)"""
    grouped = {t: [] for t in EnrichmentType}

    for e in enrichments:
        grouped[e.enrichment_type].append(e)

    return grouped


######################################
# EDGAR TRAPI RESPONSE BUILDING
###################################

def build_edgar_response(builder: EGARTRAPIBuilder, params: QueryParams, lookup_results: Lookup,
                         enrichments: list[EnrichmentResult], graph_inferred: list[tuple],
                         property_inferred: dict, result_length: int | None):
    """
    Build the complete TRAPI response using TRAPIBuilder.

    Structure:
    1. Input curie node
    2. Lookup nodes + UUID set node
    3. Enrichment nodes (rules)
    4. Inferred nodes (final results)
    5. All connecting edges and auxiliary graphs
    """
    # 1. Add input curie node
    builder.add_node(lookup_results.input_qnode_curie.new_curie,
                     lookup_results.input_qnode_curie.newnode_type or [params.output_semantic_type],
                     lookup_results.input_qnode_curie.name)

    # 2. Build lookup structure (UUID set + member nodes)
    uuid_node = "uuid:1"
    uuid_group_edges, lookup_edges, uuid_to_curie_edge_id = build_lookup_structure(builder, params, lookup_results,
                                                                                   uuid_node)

    # 3. Add enrichment nodes and edges
    enrichment_edges = build_enrichment_structure(builder, enrichments, uuid_node, uuid_group_edges)

    # 4. Add inferred nodes and final results
    results_cache = {}
    build_inference_results(builder, params, graph_inferred, property_inferred, lookup_results.link_ids,
                            uuid_to_curie_edge_id, enrichment_edges, results_cache)

    # 5. Finalize results (apply result_length limit here!)
    finalize_results(builder, results_cache, enrichments, result_length)


def build_lookup_structure(builder: EGARTRAPIBuilder, params: QueryParams, lookup_results: Lookup,
                           uuid_node: str) -> tuple[dict, dict, str]:
    """Build the lookup layer: input -> lookup_nodes -> UUID set"""

    uuid_group = lookup_results.link_ids

    # Extract just the predicate string, not the full JSON
    pred_json = orjson.loads(lookup_results.predicate) if isinstance(lookup_results.predicate,
                                                                     str) else lookup_results.predicate
    predicate_only = pred_json.get("predicate") if isinstance(pred_json, dict) else lookup_results.predicate

    # Create UUID set node
    builder.add_node(uuid_node, [params.output_semantic_type], uuid_node, is_set=True)
    builder.add_node_attribute(uuid_node, "biolink:member_ids", {"sources": uuid_group})

    uuid_group_edges = {}
    lookup_edges = {}

    for link in lookup_results.lookup_links:
        # Add lookup node
        builder.add_node(link.link_id, link.link_type or [], link.link_name)

        # Add edge: lookup_node -> input_curie (or reverse)
        edge_dict = edge_from_component(link.link_edge)
        if edge_dict:
            lookup_edge_id = builder.add_edge(
                edge_dict["subject"],
                edge_dict["predicate"],
                edge_dict["object"],
                sources=edge_dict.get("sources", [])
            )
            lookup_edges[link.link_id] = lookup_edge_id

        # Add member_of edge: lookup_node -> UUID
        member_edge_id = builder.add_edge(
            link.link_id,
            "biolink:member_of",
            uuid_node
        )
        uuid_group_edges[link.link_id] = member_edge_id

    # Add edge: UUID -> input_curie (or reverse)
    if params.is_source:
        uuid_to_curie_edge_id = builder.add_edge(
            params.curie, predicate_only, uuid_node
        )
    else:
        uuid_to_curie_edge_id = builder.add_edge(
            uuid_node, predicate_only, params.curie
        )

    # Create auxiliary graph for lookup
    aux_edges = list(uuid_group_edges.values()) + list(lookup_edges.values())
    aux_id = builder.add_auxiliary_graph(f"SG:_{uuid_to_curie_edge_id}", aux_edges)
    builder.add_support_graph_to_edge(uuid_to_curie_edge_id, aux_id, as_array=True)

    return uuid_group_edges, lookup_edges, uuid_to_curie_edge_id


def build_enrichment_structure(builder: EGARTRAPIBuilder, enrichments: list[EnrichmentResult],
                               uuid_node: str, uuid_group_edges: dict) -> dict:
    """Build the enrichment layer: lookup_nodes -> enriched_nodes -> UUID"""

    enrichment_edges = {}
    for enrichment in enrichments:
        # Add enrichment node
        builder.add_node(
            enrichment.enriched_id,
            list(enrichment.enriched_types),
            enrichment.enriched_name
        )

        # Add property to node if it's a property enrichment
        if enrichment.enrichment_type == EnrichmentType.PROPERTY:
            builder.add_node_attribute(
                enrichment.enriched_id,
                role_predicate,
                enrichment.enriched_id,
                attributes=[
                    {"attribute_type_id": "biolink:p-value", "value": enrichment.p_value}
                ]
            )

        # Build support edges and auxiliary graphs
        aux_graph_ids = []

        if enrichment.enrichment_type == EnrichmentType.GRAPH:
            prefix = 'e'
            # Graph enrichment: add edges from lookup nodes to enriched node
            for edge_dict in enrichment.support_edges:
                enrich_edge_id = builder.add_edge(
                    edge_dict["source"],
                    edge_dict["predicate"],
                    edge_dict["target"],
                    attributes=[{"attribute_type_id": "biolink:p_value", "value": enrichment.p_value}]
                )

                # Find which lookup node this connects to
                input_curie = edge_dict["target"] if edge_dict["source"] == enrichment.enriched_id else edge_dict[
                    "source"]
                member_edge = uuid_group_edges.get(input_curie)

                if member_edge:
                    aux_id = builder.add_auxiliary_graph(
                        f"SG:_{prefix}_{enrich_edge_id}",
                        [enrich_edge_id, member_edge]
                    )
                    aux_graph_ids.append(aux_id)
        else:
            # Property enrichment: add edges from linked curies to property
            prefix = 'n'
            for linked_curie in enrichment.linked_curies:
                enrich_edge_id = builder.add_edge(
                    linked_curie,
                    role_predicate,
                    enrichment.enriched_id,
                    attributes=[{"attribute_type_id": "biolink:p_value", "value": enrichment.p_value}]
                )

                member_edge = uuid_group_edges.get(linked_curie)
                if member_edge:
                    aux_id = builder.add_auxiliary_graph(
                        f"SG:_{prefix}_{enrich_edge_id}",
                        [enrich_edge_id, member_edge]
                    )
                    aux_graph_ids.append(aux_id)

        # Add enrichment -> UUID edge
        if enrichment.enrichment_type == EnrichmentType.GRAPH:
            enrichment_predicate = enrichment.predicate_only
            prefix = 'e'
        else:
            enrichment_predicate = "biolink:similar_to"
            prefix = 'n'

        enrichment_to_uuid_edge_id = builder.add_edge(
            enrichment.enriched_id,
            enrichment_predicate,
            uuid_node,
            edge_id=f"{prefix}_{enrichment.enriched_id}_{enrichment_predicate}_{uuid_node}",
            attributes=[{"attribute_type_id": "biolink:p_value", "value": enrichment.p_value}]
        )

        # Attach auxiliary graphs
        for aux_id in aux_graph_ids:
            builder.add_support_graph_to_edge(enrichment_to_uuid_edge_id, aux_id, as_array=True)

        enrichment_edges[enrichment.key] = {
            'edge_id': enrichment_to_uuid_edge_id,
            'p_value': enrichment.p_value,
            'enriched_id': enrichment.enriched_id,
            'enrichment_type': enrichment.enrichment_type
        }

    return enrichment_edges


def build_inference_results(builder: EGARTRAPIBuilder, params: QueryParams, graph_inferred: list[tuple],
                            property_inferred: dict, uuid_group: list[str], uuid_to_curie_edge_id: str,
                            enrichment_edges: dict, results_cache: dict):
    """Build the inference layer: enriched_nodes -> inferred_nodes -> input_curie"""

    # =========================================================================
    # STEP 1: Collect ALL evidence for each inferred node (both graph & property)
    # =========================================================================

    all_evidence = defaultdict(lambda: {'graph_rules': [], 'property_rules': [], 'node_info': None})

    # Collect graph inference evidence
    for enrichment, inferred_result in graph_inferred:
        enrichment_info = enrichment_edges.get(enrichment.key)
        if not enrichment_info:
            continue

        for link in inferred_result.lookup_links:
            if link.link_id in uuid_group:
                continue

            all_evidence[link.link_id]['graph_rules'].append({
                'enriched_node': enrichment.enriched_id,
                'enriched_predicate': enrichment.predicate,
                'p_value': enrichment.p_value,
                'link': link,
                'enrichment_edge_id': enrichment_info['edge_id'],
                'enrichment_key': enrichment.key
            })
            # Store node info from first encounter
            if all_evidence[link.link_id]['node_info'] is None:
                all_evidence[link.link_id]['node_info'] = {'name': link.link_name, 'types': link.link_type or []}

    # Collect property inference evidence
    property_to_enrichment = {}
    for key, info in enrichment_edges.items():
        if info.get('enrichment_type') == EnrichmentType.PROPERTY:
            property_to_enrichment[info['enriched_id']] = key

    for prop, inferred_data in property_inferred.items():
        enrichment_key = property_to_enrichment.get(prop)
        enrichment_info = enrichment_edges.get(enrichment_key) if enrichment_key else None

        if not enrichment_info:
            continue

        for link_id, link_name in zip(inferred_data.get("lookup_links", []), inferred_data.get("lookup_names", [])):
            if link_id in uuid_group:
                continue

            all_evidence[link_id]['property_rules'].append({
                'property': prop,
                'p_value': inferred_data['p_value'],
                'enrichment_edge_id': enrichment_info['edge_id'],
                'link_name': link_name
            })
            # Store node info if not already set by graph rules
            if all_evidence[link_id]['node_info'] is None:
                all_evidence[link_id]['node_info'] = {'name': link_name, 'types': [params.output_semantic_type]}

    # =========================================================================
    # STEP 2: Build results for each inferred node with combined scores
    # =========================================================================

    for inferred_id, evidence in all_evidence.items():
        graph_rules = evidence['graph_rules']
        property_rules = evidence['property_rules']
        node_info = evidence['node_info']

        if not graph_rules and not property_rules:
            continue

        # Combine ALL p-values from both graph and property rules
        all_pvalues = [r['p_value'] for r in graph_rules] + [r['p_value'] for r in property_rules]
        score_info = combine_rule_pvalues_to_score(all_pvalues, method="geometric")

        # Add inferred node
        builder.add_node(inferred_id, node_info['types'], node_info['name'])

        # Create final inferred edge
        if params.is_source:
            source, target = params.curie, inferred_id
        else:
            source, target = inferred_id, params.curie

        predicate_only = params.predicate_only
        inferred_edge_id = f"{source}_Inferred_to_{predicate_only}_{target}"

        builder.add_edge(
            source, predicate_only, target,
            edge_id=inferred_edge_id
        )

        # Add auxiliary graphs for each GRAPH rule
        for rule in graph_rules:
            edge_dict = edge_from_component(rule['link'].link_edge)
            if edge_dict:
                enriched_to_infer_id = builder.add_edge(
                    edge_dict["subject"],
                    edge_dict["predicate"],
                    edge_dict["object"]
                )

                aux_id = builder.add_auxiliary_graph(
                    f"e_Inferred_SG:_{inferred_edge_id}_via_{enriched_to_infer_id}",
                    [enriched_to_infer_id, rule['enrichment_edge_id'], uuid_to_curie_edge_id]
                )
                builder.add_support_graph_to_edge(inferred_edge_id, aux_id)

        # Add auxiliary graphs for each PROPERTY rule
        for rule in property_rules:
            prop_to_infer_id = builder.add_edge(inferred_id, role_predicate, rule['property'])

            aux_id = builder.add_auxiliary_graph(
                f"n_Inferred_SG:_{inferred_edge_id}_via_{prop_to_infer_id}",
                [prop_to_infer_id, rule['enrichment_edge_id'], uuid_to_curie_edge_id]
            )
            builder.add_support_graph_to_edge(inferred_edge_id, aux_id)

        # Create result binding with COMBINED score
        results_cache[inferred_id] = create_result_binding(
            params, inferred_id, inferred_edge_id, score_info['combined_score']
        )


def create_result_binding(params: QueryParams, inferred_id: str, edge_id: str, score: float) -> dict:
    """Create a TRAPI result binding"""
    return {
        "node_bindings": {
            params.input_qnode: [{"id": params.curie, "attributes": []}],
            params.output_qnode: [{"id": inferred_id, "attributes": []}]
        },
        "analyses": [{
            "edge_bindings": {
                params.qedge_id: [{"id": edge_id, "attributes": []}]
            },
            "resource_id": INFORES,
            "score": score,
            "attributes": []
        }]
    }


def finalize_results(builder: EGARTRAPIBuilder, results_cache: dict, enrichments: list[EnrichmentResult], result_length: int = None):
    """
    Sort results by score, limit to top N, prune unreferenced graph elements, and log metadata.
    """

    start_time = time.time()

    # Capture pre-pruning stats
    pre_nodes = len(builder.kg_nodes)
    pre_edges = len(builder.kg_edges)
    pre_aux = len(builder.aux_graphs)

    enrichment_ids_before = {e.enriched_id for e in enrichments}
    enrichments_before = len(enrichment_ids_before)

    # Sort and filter
    sorted_results = sorted(
        results_cache.values(),
        key=lambda x: x["analyses"][0].get("score", 0),
        reverse=True
    )

    kept_results = sorted_results[:result_length] if result_length else sorted_results

    builder.results.clear()
    builder.results.extend(kept_results)

    # Prune
    prune_start = time.time()
    prune_message(builder, kept_results)
    prune_time = time.time() - prune_start

    enrichments_after = sum(1 for e_id in enrichment_ids_before if e_id in builder.kg_nodes)

    # Capture post-pruning stats
    post_nodes = len(builder.kg_nodes)
    post_edges = len(builder.kg_edges)
    post_aux = len(builder.aux_graphs)

    # Calculate score stats
    scores = [r["analyses"][0].get("score", 0) for r in kept_results]

    # LOG COMPREHENSIVE METADATA
    builder.log("EDGAR finalization complete", level="INFO",
                metadata={"timing": {"total_seconds": round(time.time() - start_time, 3), "pruning_seconds": round(prune_time, 3)},
                          "results": {"total_before_filtering": len(results_cache), "total_after_filtering": len(kept_results), "limit_applied": result_length},
                          "scores": {"min": float(min(scores)) if scores else 0, "max": float(max(scores)) if scores else 0},
                          "enrichments": {"before_pruning": enrichments_before, "after_pruning": enrichments_after},
                          "knowledge_graph": {"before filtering": {"nodes": pre_nodes, "edges": pre_edges, "aux_graphs": pre_aux},
                                              "after filtering": {"nodes": post_nodes, "edges": post_edges, "aux_graphs": post_aux},
                                              "after pruning": {"nodes": pre_nodes - post_nodes, "edges": pre_edges - post_edges, "aux_graphs": pre_aux - post_aux}
                                              }
                          }
                )

    logger.info(
        f"Finalized {len(kept_results)}/{len(results_cache)} results, "
        f"enrichments {enrichments_after}/{enrichments_before}, "
        f"pruned {pre_nodes - post_nodes} nodes, {pre_edges - post_edges} edges in {time.time() - start_time:.2f}s"
    )


def ensure_empty_results(in_message: dict):
    """Ensure the message has valid empty results structure for TRAPI compliance"""
    if "message" not in in_message:
        in_message["message"] = {}

    msg = in_message["message"]

    if "knowledge_graph" not in msg:
        msg["knowledge_graph"] = {"nodes": {}, "edges": {}}

    if "results" not in msg:
        msg["results"] = []

    if "auxiliary_graphs" not in msg:
        msg["auxiliary_graphs"] = {}


def edge_from_component(edge: NewEdge) -> dict:
    """Convert NewEdge component to dict"""
    if not edge:
        return {}

    pred_json = orjson.loads(edge.predicate) if isinstance(edge.predicate, str) else edge.predicate
    predicate_only = pred_json.get("predicate") if isinstance(pred_json, dict) else edge.predicate

    return {
        "subject": edge.source,
        "predicate": predicate_only,
        "object": edge.target,
        "sources": getattr(edge, 'prov', []) or []
    }

######################################
#
# Everything after this is to be mined for spare parts then discarded.
#
###################################