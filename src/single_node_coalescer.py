from collections import defaultdict
from itertools import chain
import os, logging, json, orjson, uuid

from src.property_coalescence.property_coalescer import coalesce_by_property, lookup_nodes_by_properties
from src.graph_coalescence.graph_coalescer import coalesce_by_graph, create_nodes_to_links, get_node_types, filter_links_by_node_type, get_node_names, add_provs

from src.set_coalescence.set_coalescer import coalesce_by_set
from src.scoring import pvalue_to_sigmoid
from src.components import MCQDefinition, Lookup_params, Lookup
from src.trapi import create_knowledge_graph_edge, create_knowledge_graph_edge_from_component, \
    create_knowledge_graph_node, add_node_to_knowledge_graph, add_edge_to_knowledge_graph, add_auxgraph_for_enrichment, \
    add_enrichment_edge, add_enrichment_result, add_member_of_klat, add_auxgraph_for_lookup, create_edgar_enrichment_edge, add_edgar_enrichment_to_uuid_edge,create_edgar_inferred_edge, add_auxgraph_for_inference, add_node_property, add_edgar_final_result, stitch_inferred_edge_id, make_edgar_final_result

logger = logging.getLogger(__name__)
role_predicate = "biolink:has_chemical_role"


async def multi_curie_query(in_message, parameters):
    """Takes a TRAPI multi-curie query and returns a TRAPI multi-curie answer."""
    # Get the list of nodes that you want to enrich:
    mcq_definition = MCQDefinition(in_message)
    enrichment_results = await coalesce_by_graph(mcq_definition.group_node.curies,
                                                 mcq_definition.group_node.semantic_type,
                                                 node_constraints= mcq_definition.enriched_node.semantic_types,
                                                 predicate_constraints=[mcq_definition.edge.predicate],
                                                 predicate_constraint_style="include",
                                                 pvalue_threshold=parameters["pvalue_threshold"],
                                                 result_length=parameters["result_length"])
    return await create_mcq_trapi_response(in_message, enrichment_results, mcq_definition)

async def infer(in_message, parameters):
    """Takes a TRAPI infer query and returns a TRAPI infer answer."""
    params = Lookup_params( in_message )
    # We are dealing with a single curie so just the top result works
    lookup_results = lookup( [params.curie],
                             [params.predicate_parts],
                             params.is_source,
                             params.output_semantic_type )[0]
    graph_enrichment_results = await coalesce_by_graph(lookup_results.link_ids,
                                                       params.output_semantic_type,
                                                       predicate_constraints=parameters.get("predicates_to_exclude", []),
                                                       pvalue_threshold=parameters.get("pvalue_threshold", 1e-6),
                                                       filter_predicate_hierarchies=True
                                                       )

    # GC returns the input curie as part of the enriched node. Such needs to be filtered out,
    # Picking the top n in the GC then coming here to filter out the inout curie enrichment further reduces the
    # enrichment results length. Isn't it better to filter EDGAR top n in edgar itself?
    graph_enrichment_results = filter_graph_enrichment_results(graph_enrichment_results,
                                                               lookup_results.link_ids + [params.curie],
                                                               pvalue_threshold=parameters.get("pvalue_threshold", 1e-5),
                                                               result_length=parameters.get("result_length", 100))

    property_enrichment_results = await property_enrich(lookup_results.link_ids, params, parameters)
    return await make_inference(in_message, params, lookup_results=lookup_results,
                                graph_enrichment_results=graph_enrichment_results,
                                property_enrichment_results=property_enrichment_results)


def lookup( curie, predicate_parts, is_source=False, output_semantic_type=None ):
    """Given an infer query, look up internally the non-inferred answers to the query.
    get the list of curies
    make sure that each has the node name and the node type and provenance"""
    # TODO: Ola to implement based on current lookup
    link_ids = create_nodes_to_links(curie, param_predicates=predicate_parts)
    link_ids = {node: links for node, links in link_ids.items() if links}

    links = []
    all_ids = unify_link_ids(link_ids) + curie
    all_node_names, all_node_types = get_node_name_and_type(all_ids)

    for curie_nodes, id_links in link_ids.items():
        link_id = filter_links_by_node_type({curie_nodes: id_links}, [output_semantic_type], all_node_types)
        for curie_node, id_link in link_id.items():
            links.append(Lookup(curie_node, predicate_parts[0], is_source, all_node_names, all_node_types, id_link,
                                output_semantic_type))
    add_provs(links)

    return links


def properties_lookup( properties, semantic_type ):
    """
    Returns property_inferred_results (dict),
    """
    if not properties:
        return {}

    property_inferred_results, nodeset = lookup_nodes_by_properties(properties, semantic_type, return_nodeset=True)
    node_names = get_node_names(nodeset)
    for property, properties in property_inferred_results.items():
        properties["lookup_names"] = [node_names.get(link) for link in properties["lookup_links"]]
    return property_inferred_results


async def property_enrich( input_ids, params, parameters ):
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
    node = create_knowledge_graph_node(enrichment.enriched_node.new_curie, enrichment.enriched_node.newnode_type, enrichment.enriched_node.newnode_name)
    add_node_to_knowledge_graph(in_message, enrichment.enriched_node.new_curie, node )
    aux_graph_ids = []
    for edge in enrichment.links:
        # 2. Add the edges between the new node and the member nodes to the knowledge graph
        trapi_edge = create_knowledge_graph_edge_from_component(edge)
        direct_edge_id = add_edge_to_knowledge_graph(in_message, edge=trapi_edge)
        # 3. Create an auxiliary graph for each element of the member_id consisting of the edge from the member_id to the new node
        aux_graph_id = add_auxgraph_for_enrichment(in_message, direct_edge_id, member_of_edges, enrichment.enriched_node.new_curie)
        aux_graph_ids.append(aux_graph_id)
    # 4. Add the inferred edge from the new node to the input uuid to the knowledge graph and
    # 5. Add the auxiliary graphs created above to the inferred edge
    enrichment_kg_edge_id = add_enrichment_edge(in_message, enrichment, mcq_definition, aux_graph_ids)
    # 6. Create a new result
    # 7. In the result, create the node_bindings
    # 8. In the result, create the analysis and add edge_bindings to it.
    # 9. Make a score out of the enrichment pvalue
    enrichment_pval = pvalue_to_sigmoid(enrichment.p_value)
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
    for edge_id, edge in in_message['message'].get('knowledge_graph',{}).get('edges',{}).items():
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
        if member_id not in in_message['message'].get('knowledge_graph',{}).get('nodes',{}):
            new_node = create_knowledge_graph_node(member_id, mcq_definition.group_node.semantic_type)
            add_node_to_knowledge_graph(in_message, member_id, new_node)
    return member_of_edges


async def make_inference( in_message, params, lookup_results, graph_enrichment_results=[],
                          property_enrichment_results=[] ):
    """Create a TRAPI EDGAR answer. Go out and get the provenance or other features as needed."""
    # TODO: Ola to implement

    # 1. Make Inference
    enrichment_ids, enrichment_predicates = unify_link_ids(graph_enrichment_results)

    graph_inferred_results = lookup(enrichment_ids, enrichment_predicates,
                                    output_semantic_type=params.output_semantic_type)

    # inferred_set = {link_id for res in graph_inferred_results for link_id in res.link_ids}
    # distinct_inferred_set = inferred_set - set(lookup_results.link_ids)

    property_inferred_results = properties_lookup(property_enrichment_results, params.output_semantic_type)

    create_infer_trapi_response(in_message, params, lookup_results, graph_enrichment_results, graph_inferred_results,
                                property_inferred_results)

    return in_message


def create_infer_trapi_response( in_message, params, lookup_results, graph_enrichment_results, graph_inferred_results,
                                 property_inferred_results ):
    """
    Combine all the results into inferred trapi message

    Lookup_results: A one-to-many outcome of the initial lookup effort. Has qg curie and the many lookup results(group)
    graph_enrichment_results: Has the enrichment_nodes and the lookup_uplinks that produced each enriched nodes
    graph_inferred_results: final_lookup results containing the enrichment_nodes, it's inferred results + inference properties
    property_inferred_results: Dictionary with key(properties) and values (inference properties)
    1. Add the curie node to the knowledge graph
    2. Make trapi message components out of the:
        1. lookup results
        2. the graph and property enrichment results
        3. the graph and property inferred results
    3. populate "message" - "results"
    """
    # In a single curie trapi, lookup_results is meant to be of length 1
    # 1. add the curie node to the knowledge graph
    add_edgar_input_curie(in_message, lookup_results)

    # 2. Add  input_curie -> individual lookup_nodes; individual lookup_nodes -> uuid_group to the kg
    uuid_to_curie_edge_id, uuid, uuid_group_edges, uuid_group, lookup_edges = add_edgar_curie_to_uuid_edge(
        in_message, lookup_results, params)

    # 3.Add enrichment results
    enrichment_edges = add_edgar_uuid_to_enrichment(in_message, uuid, uuid_group_edges,
                                                   graph_enrichment_results, property_inferred_results)

    # 4. Add the inferred nodes and edges and create result_bindings
    results_cache = {}
    # add_enrichment inference
    add_edgar_inference(results_cache, in_message, graph_inferred_results, property_inferred_results,
                                   uuid_group, uuid_to_curie_edge_id, enrichment_edges, params)

    # 5. Add the results to the trapi message
    add_edgar_final_result(in_message, results_cache)

    return in_message


def unify_link_ids( results ):
    if results == {}:
        return []

    if results == []:
        return [], []

    if isinstance(results, dict):
        # Takes care of inputs from create_node_to_links of the format:
        # {'node1': [links], 'node2': [links]...}; then return all the links as one list
        return list(frozenset(chain.from_iterable(results.values())))

    # Graph_Coalesce result? of the format:
    # [AnswerObject1, AnswerObject2, ....]; then return all the links in one list and their respective edges to the enrichment nodes in a separate list
    seen_nodes = set()
    filtered_nodes = []
    filtered_predicates = []

    for result in results:
        node, pred = result.enriched_node.new_curie, orjson.loads(result.predicate or '{}')
        if (node, pred.get("predicate")) in seen_nodes:
            continue
        filtered_nodes.append(node)
        filtered_predicates.append(json.dumps(pred))
        seen_nodes.add((node, pred.get("predicate")))
    return filtered_nodes, filtered_predicates



def get_node_name_and_type( input_ids ):
    return get_node_names(input_ids), get_node_types(input_ids)


def filter_graph_enrichment_results( enrichment_results, input_ids, pvalue_threshold=None, result_length=None ):
    """We do not want a circle, so, we filter out lookup and inout curies from the enrichment results."""
    if pvalue_threshold is None:
        pvalue_threshold = 1e-5

    if result_length is None:
        result_length = 100

    enrichment_result = [enrichment_result for enrichment_result in enrichment_results if
               enrichment_result.enriched_node.new_curie not in input_ids]

    # chk_best_rule = {}
    # for i, result in enumerate(results):
    #     # Group results by enriched_node
    #     chk_best_rule.setdefault(result.enriched_node.new_curie, []).append((result.predicate, result.p_value))
    # with open('MONDO0004979DrugfilteredSuper_bestrule.json', 'w') as json_file:
    #     json.dump(chk_best_rule, json_file, indent=4)

    enrichment_result = [result for result in enrichment_result if result.p_value < pvalue_threshold]
    enrichment_result = enrichment_result[:result_length]

    return enrichment_result


def add_edgar_input_curie( in_message, lookup_results ):
    node = create_knowledge_graph_node(lookup_results.input_qnode_curie.new_curie,
                                       lookup_results.input_qnode_curie.newnode_type,
                                       lookup_results.input_qnode_curie.name)
    add_node_to_knowledge_graph(in_message, lookup_results.input_qnode_curie.new_curie, node)


def add_edgar_curie_to_uuid_edge( in_message, lookup_results, params ):
    """
    Each result maps the input curie to its lookup result.  For each result we need to
         1.  Add the curie node to the knowledge graph
         2. Add the edges between the curie node and the lookup nodes to the knowledge graph
         3. Add the lookup nodes to the knowledge graph

    """
    uuid_group = lookup_results.link_ids
    lookup_predicate_only = orjson.loads(lookup_results.predicate).get("predicate")

    # 1. Make the set node
    uuid = "uuid:1"
    set_node = create_knowledge_graph_node(uuid, [params.output_semantic_type], uuid)
    add_member_attributes(set_node, uuid_group)
    add_node_to_knowledge_graph(in_message, uuid, set_node)

    # 2. Add the edges between the input curie node and lookup nodes to the knowledge graph
    uuid_group_edges = {};
    lookup_edges = {}
    for lookup_link in lookup_results.lookup_links:
        # 1. Let's add the individual lookup nodes to the kg
        node = create_knowledge_graph_node(lookup_link.link_id, lookup_link.link_type, lookup_link.link_name)
        add_node_to_knowledge_graph(in_message, lookup_link.link_id, node)

        # 2. Let's add the individual lookup nodes - predicate -> input curie to the kg
        trapi_edge = create_knowledge_graph_edge_from_component(lookup_link.link_edge)
        trapi_edge_id = f"{trapi_edge.get('subject')}_{trapi_edge.get('predicate')}_{trapi_edge.get('object')}"
        add_edge_to_knowledge_graph(in_message, trapi_edge, trapi_edge_id)

        lookup_edges[lookup_link.link_id] = trapi_edge_id

        # 3. Add C2(in lookup nodes) - member_of -> Group edges to the kg
        group_member_edge_id = f"{lookup_link.link_id}_member_of_{uuid}"
        group_member_new_edge = create_knowledge_graph_edge(lookup_link.link_id, uuid, "biolink:member_of")

        add_edge_to_knowledge_graph(in_message, group_member_new_edge, group_member_edge_id)
        uuid_group_edges[lookup_link.link_id] = group_member_edge_id

    # 3. Create the group_node to qg input curie
    if params.is_source:
        uuid_to_curie_edge_id = f"{params.curie}_{lookup_predicate_only}_{uuid}"
        group_to_curie_edge = create_knowledge_graph_edge(params.curie, uuid,
                                                          orjson.loads(params.predicate_parts).get("predicate"))
    else:
        uuid_to_curie_edge_id = f"{uuid}_{lookup_predicate_only}_{params.curie}"
        group_to_curie_edge = create_knowledge_graph_edge(uuid, params.curie,
                                                          orjson.loads(params.predicate_parts).get("predicate"))
    # 4, Add the group_node to qg input curie to the kg
    add_edge_to_knowledge_graph(in_message, edge=group_to_curie_edge, edge_id=uuid_to_curie_edge_id)
    add_auxgraph_for_lookup(in_message, uuid_to_curie_edge_id, uuid_group_edges, lookup_edges)

    return uuid_to_curie_edge_id, uuid, uuid_group_edges, uuid_group, lookup_edges


def add_edgar_uuid_to_enrichment( in_message, uuid, uuid_group_edges, graph_enrichment_results=[],
                                 property_enrichment_results={} ):
    """
     Each INFERRED is a result.  For each INFERRED we need to
    Each enrichment is a result.  For each enrichment we need to
         1. add the new node to the knowledge graph
         2. Add the edges between the new node and the member nodes to the knowledge graph
         3. Create an auxiliary graph for each element of the member_id consisting of the edge from the member_id to the new node
            and the member_of edge connecting the member_id to the input node.
         4. Add the inferred edge from the new node to the input uuid to the knowledge graph
         5. Add the auxiliary graphs created above to the inferred edge
         6. Create a new result
         7. In the result, create the node_bindings
         8. In the result, create the analysis and add edge_bindings to it.

    """
    enriched_to_uuid_edges = {}
    for enrichment in graph_enrichment_results:
        # 1. add the new node to the knowledge graph
        node = create_knowledge_graph_node(enrichment.enriched_node.new_curie, enrichment.enriched_node.newnode_type,
                                           enrichment.enriched_node.newnode_name)
        add_node_to_knowledge_graph(in_message, enrichment.enriched_node.new_curie, node)

        aux_graph_ids = []
        for edge in enrichment.links:
            # 2. Add the edges between the new node and each node to the knowledge graph: GeneX-C1
            enrichment_edge_id, enrichment_edge = create_edgar_enrichment_edge(enrichment.p_value, input_edge=edge)
            add_edge_to_knowledge_graph(in_message, enrichment_edge, enrichment_edge_id)
            # 3. Create an auxiliary graph for each element of the member_id consisting of the edge from the
            # member_id to the enriched node
            aux_graph_id = add_auxgraph_for_enrichment(in_message, enrichment_edge_id, uuid_group_edges,
                                                       enrichment.enriched_node.new_curie)
            aux_graph_ids.append(aux_graph_id)

        # 4. Add the inferred edge from the new node to the input uuid to the knowledge graph and
        # 5. Add the auxiliary graphs created above to the inferred edge
        enrichment_kg_edge_id = add_edgar_enrichment_to_uuid_edge(in_message, uuid, aux_graph_ids, enrichment.predicate, enrichment)
        enriched_to_uuid_edges[enrichment.enriched_node.new_curie] = enrichment_kg_edge_id

    for property, properties in property_enrichment_results.items():
        p_value = properties["p_value"]
        # 1.  Create node from  properties and add the nodes to KG
        node = create_knowledge_graph_node(property, "biolink:ChemicalRole", property)
        add_node_property(node, property, p_value=p_value)
        add_node_to_knowledge_graph(in_message, property, node)

        aux_graph_ids = []
        for link in properties["linked_curies"]:
            # 2.  Add the properties to each lookup link nodes
            add_node_property(link, property, in_message=in_message, p_value=p_value)

            # 3. Add the edges between the new node and each node to the knowledge graph: GeneX-C1
            enrichment_edge_id, enrichment_edge = create_edgar_enrichment_edge(p_value, source=link, target=property,
                                                                               predicate_only=role_predicate)
            add_edge_to_knowledge_graph(in_message, enrichment_edge, enrichment_edge_id)
            # 3. Create an auxiliary graph for each element of the member_id consisting of the edge from the
            # member_id to the enriched node
            aux_graph_id = add_auxgraph_for_enrichment(in_message, enrichment_edge_id, uuid_group_edges, property)
            aux_graph_ids.append(aux_graph_id)

            # 4. Add the inferred edge from the new node to the input uuid to the knowledge graph and
            # 5. Add the auxiliary graphs created above to the inferred edge
        enrichment_kg_edge_id = add_edgar_enrichment_to_uuid_edge(in_message, uuid, aux_graph_ids,
                                                                   "biolink:similar_to", property)
        enriched_to_uuid_edges[property] = enrichment_kg_edge_id

    return enriched_to_uuid_edges


def add_edgar_inference( results_cache, in_message, graph_inferred_results, property_inferred_results,
                                    uuid_group, uuid_to_curie_edge_id, enrichment_edges, params ):
    for inferred_result in graph_inferred_results:
        enriched_node = inferred_result.input_qnode_curie.new_curie
        # get the direct edge1: [member_of]-(set uuid)-[enriched_edge]-(enriched_node)
        enriched_to_uuid_edge_id = enrichment_edges[enriched_node]

        for inferred_link in inferred_result.lookup_links:

            # Do Not re-store the lookup results
            if inferred_link.link_id in uuid_group:
                continue

            # 1. Make and add edge from the enriched nodes to the inferred result
            enriched_to_infer_edge = create_knowledge_graph_edge_from_component(inferred_link.link_edge)
            enriched_to_infer_edge_id = f"{enriched_to_infer_edge.get('subject')}_{enriched_to_infer_edge.get('predicate')}_{enriched_to_infer_edge.get('object')}"
            add_edge_to_knowledge_graph(in_message, enriched_to_infer_edge, enriched_to_infer_edge_id)

            # 2. Add the inferred nodes to the KG44
            if inferred_link.link_id in results_cache:
                # Meaning that the inference was gotten from 2 different enrichment nodes or same enrichment nodes but different enrichment edges
                direct_inferred_edge_id = stitch_inferred_edge_id(inferred_link.link_id, params)
                add_auxgraph_for_inference(in_message, enriched_node, direct_inferred_edge_id,
                                           enriched_to_infer_edge_id, enriched_to_uuid_edge_id, uuid_to_curie_edge_id)
                continue

            node = create_knowledge_graph_node(inferred_link.link_id, inferred_link.link_type,
                                               inferred_link.link_name)
            add_node_to_knowledge_graph(in_message, inferred_link.link_id, node)

            # 3. make and add the final_inferred edge to the KG
            direct_inferred_edge_id, direct_inferred_edge = create_edgar_inferred_edge(inferred_link.link_id,
                                                                                       params.curie,
                                                                                       params.predicate_parts,
                                                                                       params.is_source)

            add_edge_to_knowledge_graph(in_message, direct_inferred_edge, direct_inferred_edge_id)
            add_auxgraph_for_inference(in_message, enriched_node, direct_inferred_edge_id,
                                       enriched_to_infer_edge_id, enriched_to_uuid_edge_id, uuid_to_curie_edge_id)

            # 4. Create a new result; In the result, create the node_bindings, analysis and edge_bindings
            make_edgar_final_result(results_cache, inferred_link.link_id, direct_inferred_edge_id, params)

    # At this point all the graph enrichment inferred results are written in the "message"
    for property, inferred_result in property_inferred_results.items():

        p_value = inferred_result["p_value"]
        # get the direct edge1: [member_of]-(set uuid)-[enriched_edge]-(enriched_node)
        enriched_to_uuid_edge_id = enrichment_edges[property]

        # For a property with n inferred results:
        for link_id, link_name in zip(inferred_result["lookup_links"], inferred_result["lookup_names"]):
            # Do Not re-store the lookup results
            if link_id in uuid_group:
                continue

            # Make and add edge from the enriched nodes(properties) to the inferred result
            enriched_to_infer_edge = create_knowledge_graph_edge(link_id, property, role_predicate)
            enriched_to_infer_edge_id = f"{link_id}_{role_predicate}_{property}"
            add_edge_to_knowledge_graph(in_message, enriched_to_infer_edge, enriched_to_infer_edge_id)

            if link_id in results_cache:
                # Existing results ? the node is already created, Just:
                # 1. Add the property on the node
                # 2. Grab the inferred edge from the KG and add support graph to it
                add_node_property(link_id, property, in_message=in_message, p_value=p_value)
                direct_inferred_edge_id = stitch_inferred_edge_id(link_id, params)
                add_auxgraph_for_inference(in_message, property, direct_inferred_edge_id, enriched_to_infer_edge_id,
                                           enriched_to_uuid_edge_id, uuid_to_curie_edge_id)

                continue
            # 1. Add the inferred nodes to the KG44
            node = create_knowledge_graph_node(link_id, params.output_semantic_type, link_name)
            add_node_property(node, property, p_value=p_value)

            add_node_to_knowledge_graph(in_message, link_id, node)

            # 2. make and add the final_inferred edge to the KG PHYS-ALZ
            direct_inferred_edge_id, direct_inferred_edge = create_edgar_inferred_edge(link_id,
                                                                                       params.curie,
                                                                                       params.predicate_parts,
                                                                                       params.is_source)

            add_edge_to_knowledge_graph(in_message, direct_inferred_edge, direct_inferred_edge_id)

            add_auxgraph_for_inference(in_message, property, direct_inferred_edge_id, enriched_to_infer_edge_id,
                                       enriched_to_uuid_edge_id, uuid_to_curie_edge_id)

            # 3. Create a new result; In the result, create the node_bindings, analysis and edge_bindings
            make_edgar_final_result(results_cache, link_id, direct_inferred_edge_id, params)
            # stored.add(link_id)



def add_member_attributes( group_node, uuid_group ):
    group_node.setdefault("is_set", True)
    group_node.setdefault("attributes", []).append(
        {"attribute_type_id": "biolink:member_ids", "value": {"sources": uuid_group}})

    ######################################
#
# Everything after this is to be mined for spare parts then discarded.
#
###################################
