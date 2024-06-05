from collections import defaultdict
from itertools import chain
import os, logging, requests, asyncio, json, uuid
from copy import deepcopy
from reasoner_pydantic import Response as PDResponse, KnowledgeGraph

from src.property_coalescence.property_coalescer import coalesce_by_property
from src.graph_coalescence.graph_coalescer import coalesce_by_graph, create_nodes_to_links, get_node_types, filter_links_by_node_type, get_node_names, add_provs
from src.set_coalescence.set_coalescer import coalesce_by_set
from src.components import MCQDefinition, Lookup_params, Lookup
from src.trapi import create_knowledge_graph_edge, create_knowledge_graph_edge_from_component, \
    create_knowledge_graph_node, add_node_to_knowledge_graph, add_edge_to_knowledge_graph, add_auxgraph_for_enrichment, \
    add_enrichment_edge, add_enrichment_result, add_member_of_klat

logger = logging.getLogger(__name__)
ROBOKOP_URL = "https://aragorn.renci.org/robokop/query"
MAX_CONNS = os.environ.get("MAX_CONNECTIONS", 5)
NRULES = int(os.environ.get("MAXIMUM_ROBOKOPKG_RULES", 11))
TRACK = {}

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

    input_ids = lookup_results.link_ids

    graph_enrichment_results = await coalesce_by_graph(input_ids,
                                                 params.output_semantic_type,
                                                 predicate_constraints=parameters.get("predicates_to_exclude", []),
                                                 pvalue_threshold=parameters.get("pvalue_threshold", 1e-6),
                                                 result_length=parameters.get("result_length", 100),
                                                 filter_predicate_hierarchies=True
                                                 )
    graph_enrichment_results = filter_graph_enrichment_results(graph_enrichment_results, input_ids + [params.curie],
                                                               pvalue_threshold=parameters.get("pvalue_threshold", 1e-6),
                                                               result_length=parameters.get("result_length", 100))
    # lookup_results = merge_lookup_and_graph_enrichment_results(graph_enrichment_results, lookup_results)# I need this to run faster for now
    # property_enrichment_results = await coalesce_by_property(input_ids, params.output_semantic_type)
    return await create_infer_trapi_response(in_message, params, lookup_results, input_ids, graph_enrichment_results)

def lookup( curie, predicate_parts, is_source=False, output_semantic_type=None ):
    """Given an infer query, look up internally the non-inferred answers to the query.
    Return them as a list of curies"""
    #TODO: Ola to implement based on current lookup
    link_ids = create_nodes_to_links(curie, param_predicates=predicate_parts)
    links = []
    all_ids = list(frozenset(chain.from_iterable(link_ids.values()))) + curie
    all_node_types = get_node_types(all_ids)
    all_node_names = get_node_names(all_ids)

    for curie_nodes, id_links in link_ids.items():
        link_id = filter_links_by_node_type({curie_nodes: id_links}, [output_semantic_type], all_node_types)
        for curie_node, id_link in link_id.items():
            links.append(Lookup(curie_node, predicate_parts[0], is_source, all_node_names, all_node_types, id_link, output_semantic_type))
    add_provs(links)

    return links



# should probably just be a call out to something property coalescer instead
async def property_enrich(input_ids):
    """Given a list of ids, find the property based enrichments for each.  Returns a list of enrichments.  Each
     enrichment is a dictionary with the form:
     {
        "enriched_property": curie,
        "attached_nodes": the list of input curies that have direct edges to the enriched_node,
        "enrichment_attributes": the p-value and other stats for the enrichment
     }
     """
    #TODO: Ola to implement based on coalesce

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
    add_enrichment_result(in_message, enrichment.enriched_node, enrichment_kg_edge_id, mcq_definition)

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



async def create_infer_trapi_response(in_message, params, lookup_results, input_ids, enrichment_results):
    """Create a TRAPI EDGAR answer. Go out and get the provenance or other features as needed."""
    # TODO: Ola to implement
    enrichment_ids, enrichment_predicates = uniqufy_enrichment_ids_and_predicates(enrichment_results)
    inferred_results = lookup(enrichment_ids, enrichment_predicates, output_semantic_type=params.output_semantic_type)

    # Temporarily add the lookup and enrichment results to the KG
    create_partial_results(in_message, params, lookup_results, enrichment_results)
    # create_partial_result_from_enrichment(in_message, )

    create_inference_results(in_message, params, input_ids, lookup_results, enrichment_results, inferred_results)

    return in_message



def create_partial_results(in_message, params, lookup_results, enrichment_results):
    """
    Each result maps one input curie to its lookup result.  For each result we need to
     1.  Add the curie node to the knowledge graph
     2. Add the edges between the curie node and the lookup nodes to the knowledge graph
     3. Add the lookup nodes to the knowledge graph
    """
    # In a single curie trapi, lookup_results is meant to be of length 1
    # 1. add the curie node to the knowledge graph
    node = create_knowledge_graph_node(lookup_results.input_qnode_curie.new_curie,
                                             lookup_results.input_qnode_curie.newnode_type,
                                             lookup_results.input_qnode_curie.name)
    add_node_to_knowledge_graph(in_message, lookup_results.input_qnode_curie.new_curie, node)

    # 2. Make the group node
    group_uuid = str(uuid.uuid4())

    node = create_knowledge_graph_node(group_uuid, [params.output_semantic_type], 'LookupGroup')
    node["attributes"].append({"member_ids": [lookup_results.link_ids]})
    add_node_to_knowledge_graph(in_message, group_uuid, node)


    # 3. Add the edges between the curie node and individual lookup nodes to the knowledge graph
    member_of_edges = {}
    for lookup_link in lookup_results.lookup_links:
        add_edge_from_link(in_message, lookup_link.link_edge, edge_prefix = "Lookup")#, return_edge=True)
        # Let's put the kg_edge_id for the link in the link instance NOPE
        # lookup_result.add_linked_kg_edges_id(link_edge_id)
        node = create_knowledge_graph_node(lookup_link.link_id,
                                                 lookup_link.link_type,
                                                 lookup_link.link_name)
        add_node_to_knowledge_graph(in_message, lookup_link.link_id, node)

        # 4. Add C2(in lookup nodes) - member_of - Group
        group_member_edge_id = f"{lookup_link.link_id}_member_of_{group_uuid}"
        group_member_new_edge = create_knowledge_graph_edge(lookup_link.link_id, group_uuid, "biolink:member_of")
        # trapi.add_member_of_klat(group_members_new_edge)
        add_edge_to_knowledge_graph(in_message, group_member_new_edge, group_member_edge_id)
        member_of_edges[lookup_link.link_id] = group_member_edge_id

    for enrichment in enrichment_results:
        # 1.(possibly) add the new node to the knowledge graph
        node = create_knowledge_graph_node(enrichment.enriched_node.id, enrichment.enriched_node.category,
                                                 enrichment.enriched_node.name)
        add_node_to_knowledge_graph(in_message, enrichment.enriched_node.id, node)
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
        add_enrichment_result(in_message, enrichment.enriched_node, enrichment_kg_edge_id, mcq_definition)

        # await create_result_from_enrichment(in_message, enrichment, member_of_edges, mcq_definition)



def add_edge_from_link(in_message, link, edge_prefix = '', return_edge=False):
    # 1. Separate link into component parts
    source = link.source
    target = link.target
    predicate = link.predicate
    prov = link.prov
    # 2. Add the edges between the curie node and lookup nodes to the knowledge graph
    edge_id = f"{source}_{edge_prefix}_{predicate}_{target}"
    new_edge = create_knowledge_graph_edge(source, target, predicate, sources=prov)
    add_edge_to_knowledge_graph(in_message, new_edge, edge_id)

    if return_edge:
        return edge_id, new_edge

def create_partial_result_from_enrichment(in_message, enrichment_results):
    """
    Each enrichment maps one or more links from the lookup efforts.  For each result we need to
     1.  Add the enriched node to the knowledge graph
     2. Add the edges between the enriched node and the lookup nodes to the knowledge graph
    """

    # add individual enrichment nodes and edges between them and lookup links
    for enriched_result in enrichment_results:
        # 1. add the enriched node to the knowledge graph
        new_node = create_knowledge_graph_node(enriched_result.enriched_node.new_curie, enriched_result.enriched_node.newnode_type,
                                                     enriched_result.enriched_node.newnode_name)
        add_node_to_knowledge_graph(in_message, enriched_result.enriched_node.new_curie, new_node)

        for link in enriched_result.links:
            # 2. Add the edges between the enriched curie node and lookup nodes to the knowledge graph
            eid = add_edge_from_link(in_message, link, edge_prefix="Enriched", return_edge=True)
            enriched_result.add_linked_kg_edges_id(eid)

def create_inference_results(in_message, params, input_ids, lookup_results, enrichment_results, inferred_results):
    """Each INFERRED is a result.  For each INFERRED we need to"""
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

    input_qnode_curie = params.curie
    predicate_part = params.predicate_parts
    output_semantic_type = params.output_semantic_type
    is_source = params.is_source
    lookup_ids = lookup_results.link_ids

    sg_mapping_dict = {}
    auxg_mapping_dict = {}


    # 1.Make the groupset id for the new nodes to the knowledge graph
    member_of_edgarset = set()
    inferred_group_uuid = str(uuid.uuid4())

    for i, inferred_result in enumerate(inferred_results):

        # 2. Add the edges between enriched node and the group node And its support graph
        enr2group_edge_id, enr2group_edge, enr2group_aux_graph_ids = add_enriched_to_all_inferred_groupnode(inferred_group_uuid, inferred_result, sg_mapping_dict)
        add_edge_to_knowledge_graph(in_message, enr2group_edge, enr2group_edge_id)
        member_edges_list = []
        inferred2curies_list = []
        for j, link in enumerate(inferred_result.lookup_links):

            # 3. Add the edges between the enriched node and inferred nodes to the knowledge graph (NO SUPPORT NEEDED)
            infer_to_enrich_eid,  infer_to_enrich_edge = add_edge_from_link(in_message, link.link_edge, edge_prefix = 'Inferred', return_edge=True)
            # Let's put the kg_edge_id for the link in the link instance
            # inferred_result.add_linked_kg_edges_id(infer_to_enrich_eid)
            auxg_mapping_dict.setdefault(enr2group_aux_graph_ids, []).append(infer_to_enrich_eid)

            # Process every individual inferred nodes
            inferred_id = inferred_result.link_ids[j]

            if inferred_id not in input_ids:

                # 4. Add the edges between the individual inferred node and the qg curie nodes by the qg_predicate to the knowledge graph
                inferred_edge_id, inferred_edge = create_inferred_edge(inferred_id, input_qnode_curie, predicate_part, is_source, return_edge=True)
                inferred2curies_list.append(inferred_edge_id)

                # Add the individual Inferred edge to the KG
                add_edge_to_knowledge_graph(in_message, inferred_edge, inferred_edge_id)

                # the straight/long supportg between inferred node and qg curie
                straight_aux_g = f"{inferred_id}_Inferred_to_{predicate_part}_{input_qnode_curie}"




                #Save the group_edge_id for the group to inferred support graph
                # group_qgcurie_support_edges.append(group_edge_id)


                # make and add the support_graph_id to the KG_edge for individual inferred node and the qg nodes
                # make_and_add_support_graph(aux_graph_ids0, inferred_edge)
                # trapi.add_aux_graphs(inferred_edge, support_graph_id)

                # support pattern: X - group
                # aux_graph_ids1_edges = [edge_id]


                # Add the support edges to the auxilliary graph
                # add_aux_graph(in_message, aux_graph_ids0, [infer_to_enrich_eid])

        # phys - X
        sg_mapping_dict.setdefault(straight_aux_g, []).extend(enrichment_results[i].link_kg_edges_ids)

                # 5. On the inferred edge add support graph

        # 7. add the group node to the KG
        new_node = create_knowledge_graph_node(inferred_group_uuid, output_semantic_type, "inferred_set")
        # 7b add its members to the attributes
        add_node_to_knowledge_graph(in_message, inferred_group_uuid, new_node)

        # 8. we need inferred group node--original_predicate--qg_curies: group-AD
        group_inferred_edge_id, group_inferred_edge = create_inferred_edge(inferred_group_uuid, input_qnode_curie, predicate_part,
                                                         is_source, return_edge=True)
        members2input_aux_graph_ids = f"{inferred_group_uuid}_rel_by_{predicate_part}_to_{input_qnode_curie}"
        sg_mapping_dict.setdefault(group_inferred_edge_id, []).append(members2input_aux_graph_ids)
        auxg_mapping_dict.setdefault(members2input_aux_graph_ids, []).extend(member_edges_list+inferred2curies_list)

        #
        # # support pattern: group - AD
        # aux_graph_ids2_edges = [group_inferred_edge_id]

        # Add the Inferred edge to the KG
        add_edge_to_knowledge_graph(in_message, group_inferred_edge, group_inferred_edge_id)

        # # Add the support edges to the auxilliary graph
        # add_aux_graph(in_message, aux_graph_ids, group_qgcurie_support_edges)

        # complete_inferred_support = f"Reasons{i}"
        # complete_inferred_gupport_edges = aux_graph_ids2_edges+aux_graph_ids1_edges+aux_graph_ids0_edges
        # add_aux_graph(in_message, complete_inferred_support, complete_inferred_gupport_edges)

    for edge, sg_list in sg_mapping_dict.items():
        in_message["message"]["knowledge_graph"]["edges"][edge]["attributes"].append({
            "attribute_type_id": "biolink:support_graphs",
            "value": sg_list,
            "attribute_source": "infores:answercoalesce"
        })

    for aug, auxedges in auxg_mapping_dict.items():
        in_message["message"]["auxiliary_graphs"][aug]= {"edges": auxedges}

    return in_message
def add_enriched_to_all_inferred_groupnode(inferred_group_uuid, inferred_result, sg_mapping_dict):
    if inferred_result.is_source:
        source = inferred_result.input_qnode_curie.new_curie
        target = inferred_group_uuid
    else:
        source = inferred_group_uuid
        target = inferred_result.input_qnode_curie.new_curie
    predicate = inferred_result.predicate
    enriched_to_inferredgroup_edge = create_knowledge_graph_edge(source, target, predicate)

    edge_id = f"{inferred_result.input_qnode_curie.new_curie}_{predicate}_group_{target}"
    aux_graph_ids = f"{source}_rel_by_{predicate}_to_{target}"
    sg_mapping_dict.setdefault(edge_id, []).append(aux_graph_ids)
    # make_and_add_support_graph(aux_graph_ids, enriched_to_inferredgroup_edge) #GeneX-group
    # trapi.add_aux_graphs(enriched_to_inferredgroup_edge, aux_graph_ids)

    # trapi.add_member_of_klat(new_edge)
    return edge_id, enriched_to_inferredgroup_edge, aux_graph_ids

def make_and_add_support_graph(aux_graph_ids,new_edge):

    """
    Add the auxiliary graphs to an edge.
    """

    new_edge.update({"attributes":[
        {
            "attribute_type_id": "biolink:support_graphs",
            "value": aux_graph_ids,
            "attribute_source": "infores:answercoalesce"
        }]}
    )


def add_aux_graph(in_message, support_graph_id, support_edges):
    if in_message["message"]["auxiliary_graphs"] == None:
        in_message["message"]["auxiliary_graphs"] = {}

    edges = in_message["message"]["auxiliary_graphs"].setdefault(support_graph_id, {}).setdefault("edges", [])
    edges.extend(support_edges)


def create_inferred_edge(new_node, qg_curie, qg_predicate, is_source = False, return_edge = False):
    # 1. Make the link into component parts
    if is_source:
        source = qg_curie
        target = new_node
    else:
        source = new_node
        target = qg_curie
    predicate = qg_predicate

    # 2. Add the edges between the curie node and lookup nodes to the knowledge graph
    edge_id = f"Inferred_{source}_{predicate}_{target}"
    new_edge = create_knowledge_graph_edge(source, target, predicate)

    if return_edge:
        return edge_id, new_edge

def uniqufy_enrichment_ids_and_predicates(enrichment_results):
    seen_nodes = set()
    filtered_nodes = []
    filtered_predicates = []

    for node, pred in zip([enrichment_result.enriched_node.new_curie for enrichment_result in enrichment_results],
                          [enrichment_result.predicate for enrichment_result in enrichment_results]):
        if (node,pred.get("predicate")) in seen_nodes:
            continue
        filtered_nodes.append(node)
        filtered_predicates.append(json.dumps(pred))
        seen_nodes.add((node, pred.get("predicate")))
    return filtered_nodes, filtered_predicates
def filter_graph_enrichment_results(enrichment_results, input_ids, pvalue_threshold=None, result_length=None):
    """We do not want a circle, so, we filter out lookup and inout curies from the enrichment results."""
    results = [enrichment_result for enrichment_result in enrichment_results if
     enrichment_result.enriched_node.new_curie not in input_ids]

    # if pvalue_threshold:
    #     results = [enrichment_result for enrichment_result in results if enrichment_result.p_value < pvalue_threshold]
    #
    # if result_length:
    #    results =  results[:result_length]

    return results
def merge_lookup_and_graph_enrichment_results(enrichment_results, lookup_results):
    """We do not want a circle, so, we filter out lookup and inout curies from the enrichment results."""
    for enrichment_result in enrichment_results:
        # Find the index positions of matches using filter and a generator expression
        lookup_indices = list(filter(lambda idx: lookup_results.link_ids[idx] in enrichment_result.linked_curies, range(len(lookup_results.link_ids))))

        lookup_results.add_enrichment(lookup_indices, enrichment_result.enriched_node, enrichment_result.predicate, enrichment_result.is_source, enrichment_result.p_value)
    return lookup_results

def uniqufy_enrichment_link(enrichment_link_dict):
    return set(chain.from_iterable(enrichment_link_dict.values()))


######################################
#
# Everything after this is to be mined for spare parts then discarded.
#
###################################

async def coalesce(answerset, method='all', mode = 'coalesce', predicates_to_exclude=[], properties_to_exclude=[], nodesets_to_exclude=[], pvalue_threshold=0, result_length=0):
    """
    Given a set of answers coalesce them and return some combined answers.
    In this case, we are going to first look for places where answers are all the same
    except for a single node.
    For this prototype, the answers must all be the same shape.
    There are plenty of ways to extend this, including adding edges to the coalescent
    entities.
    """

    # Look for places to combine
    patches = []

    if mode == 'query':
        set_opportunity = {}
        for qg_id, node_data in answerset.get("query_graph", {}).get("nodes", {}).items():
            if 'ids' in node_data and node_data.get('is_set'):
                set_opportunity = get_opportunity(answerset)
        coalescence_opportunities = set_opportunity
    else:
        if mode == 'infer':
            # We need to do lookup first before coalescing
            response, status_code = lookup(answerset)
            if status_code != 200:
                # uncomment this to save the result to the directory

                # with open("lookup.json", 'w+') as tf:
                #     json.dump(answerset, tf, indent=4)
                # new_answerset = json.load(tf)
                logger.error(f'Error: {status_code} from {ROBOKOP_URL}')
                return answerset
            else:
                answerset = response['message']

        # Either way
        coalescence_opportunities = identify_coalescent_nodes(answerset)

    if method in ['all', 'set']:
        # set query is only reasonable if there are more than one edges in the qgraph.  Usually if you're
        # asking a 1 hop you want to see the answers individually.  THis will do nothing but smush them together
        # and make them hard to read.
        n_query_edges = len(answerset.get('query_graph', {}).get('edges', {}))
        if n_query_edges > 1:
            patches += coalesce_by_set(coalescence_opportunities, nodesets_to_exclude, pvalue_threshold)

    if method in ['all', 'property']:
        patches += coalesce_by_property(coalescence_opportunities, properties_to_exclude, pvalue_threshold)

    if method in ['all', 'graph']:
        patches += coalesce_by_graph(coalescence_opportunities, mode, predicates_to_exclude, pvalue_threshold, result_length)

    # print('lets patch')
    # Enrichment done and commonalities found, at this point we can rewrite the results
    if mode == 'query':
        new_answers = patch_answers_(answerset, coalescence_opportunities, patches)
        new_answerset = new_answers['message']
        return new_answerset
    else:
        new_answers, aux_graphs, updated_qg, updated_kg = patch_answers(answerset, patches)
        new_answerset = {'query_graph': updated_qg, 'knowledge_graph': updated_kg, 'results': new_answers,
                         'auxiliary_graphs': aux_graphs}

        if mode == 'infer':
            if aux_graphs:
                new_answerset = await enrichment_based_infer(new_answerset, answerset, predicates_to_exclude)
                return new_answerset['message']
            else:
                logger.error(f'Empty Auxiliary_graphs; No enriched result')
                return response.json()
        else:
            return new_answerset

def transform_trapi(results):
    if isinstance(results, list):
        transformed_trapi1_4_data = []
        for result in results:
            transformed_result = {
                "node_bindings": result["node_bindings"],
                "analyses": [
                    {
                        "resource_id": result.get("resource_id", "automat-robokop"),
                        "edge_bindings": result.get("edge_bindings", {}),
                        "score": result.get("score", 0.)
                    }
                ]
            }
            transformed_trapi1_4_data.append(transformed_result)
    else:
        transformed_trapi1_4_data = {
                "node_bindings": results["node_bindings"],
                "analyses": [
                    {
                        "edge_bindings": results.get("edge_bindings", {}),
                        "score": results.get("score", 0.)
                    }
                ]
            }
    return transformed_trapi1_4_data

def is_trapi1_4(results):
    if all('analyses' in result for result in results):
        return results
    else:
        return transform_trapi(results)
def patch_answers(answerset, patches):
    # probably only good for the prop coalescer
    # We want to maintain a single kg, and qg.
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']

    answers = [Answer(ans, qg, kg) for ans in is_trapi1_4(answerset['results'])]
    all_new_answer = []
    i = 0
    # If there are lots of patches, then we end up spending lots of time finding edges and nodes in the kg
    # as we update it.  kg_indexes are the indexes required to find things quickly.  apply both
    # looks in there, and updates it
    kg_indexes = {}
    auxiliary_graphs = defaultdict(dict)
    if patches:
        for patch in patches:
            # Patches: includes all enriched nodes attached to a certain enrichment by an edge as well as the enriched nodes +attributes
            i += 1
            answers, qg, kg, kg_indexes = patch.apply(answers, qg, kg, kg_indexes, i)
            # .apply adds the enrichment and edges to the kg and return individual enriched node attached to a certain enrichment by an edge

            """Serialize the answer back to ReasonerStd JSON 1.0"""
            # for answer in new_answers:
            #     all_new_answer.append(answer.to_json())
            #     auxiliary_graphs.update(answer.get_auxiliarygraph())
            # aux_g = auxiliary_graphs
        for answer in answers:
            all_new_answer.append(answer.to_json())
            auxiliary_graphs.update(answer.get_auxiliarygraph())
        aux_g = auxiliary_graphs
        return all_new_answer, dict(sorted(aux_g.items(), key=lambda x: int(x[0].split('_')[3]))), qg, kg
    else:
        for answer in answers:
            all_new_answer.append(answer.to_json())
        return all_new_answer, auxiliary_graphs, qg, kg
def patch_answers_(answerset, nodeset, patches):
    # probably only good for the prop coalescer
    # We want to maintain a single kg, and qg.
    qg = answerset.get('query_graph', {})
    i = 0
    kg_indexes = {}
    pydantic_kgraph = KnowledgeGraph.parse_obj({"nodes": {}, "edges": {}})
    result = PDResponse(**{
        "message": {"query_graph": {"nodes": {}, "edges": {}},
                    "knowledge_graph": {"nodes": {}, "edges": {}},
                    "results": []}}).dict(exclude_none=True)
    kg = result['message']['knowledge_graph']
    if patches:
        for patch in patches:
            # Patches: includes all enriched nodes attached to a certain enrichment by an edge as well as the enriched nodes +attributes
            i += 1
            new_answer, updated_kg, kg_indexes = patch.apply_(nodeset, kg, kg_indexes, i)
            # .apply adds the enrichment and edges to the kg and return individual enriched node attached to a certain enrichment by an edge
            pydantic_kgraph.update(KnowledgeGraph.parse_obj(updated_kg))

            # Construct the final result message, currently empty
            result["message"]["results"].extend(new_answer)
        result["message"]["query_graph"] = qg
        result["message"]["knowledge_graph"] = pydantic_kgraph.dict()

    return result
def identify_coalescent_nodes(answerset):
    """Given a set of answers, locate answersets that are equivalent except for a single
    element.  For instance if we have an answer (a)-(b)-(c) and another answer (a)-(d)-(c)
    we will return (a)-(*)-(c) [b,d].
    Note that the goal is not to coalesce every answer in the set into a single thing, but to
    find all the possible coalescent locations of 2 or more answers.
    The return value is a list of groupings. Each grouping is a tuple consiting of
    1) The fixed portions of the coalescent graph expressed as bindings, and stored
       as a set of tuples
    2) the question graph id and type of the node that is varying across the solutions
    3) a set of kg_id's that are the variable bindings to the qg_id.
    e.g. if the qg for the example above were (qa)-[qp1:t1]-(qb)-[qp2:t2]-(qc) then we would
    return a list with one value that would look like:
    [ (set(('qa','a'),('qc','c'),('qp1','t1'),('qp2','t2')), ('qb','disease'), set('b','d') )]"""
    # In this implementation, we characterize each result with a frozendict that we can compare.
    # This is essentially just the node and edge bindings for the answer, except for 1) one node
    # that is allowed to vary and 2) the edges attached to that node, that are allowed to vary in
    # identity but must remain constant in type.
    question = answerset['query_graph']
    graph = answerset['knowledge_graph']


    answers = [Answer(ans, question, graph) for ans in is_trapi1_4(answerset['results'])]
    # answers = [Answer(ans, question, graph) for ans in answerset['results']]
    varhash_to_answers = defaultdict(list)
    varhash_to_qg = {}
    varhash_to_kg = defaultdict(set)
    varhash_to_answer_indices = defaultdict(list)
    varhash_to_kga_map = defaultdict(dict)
    # make a map of kg edges to type. Is done here globally to save time.
    kg_edgetypes = {edge_id: edge['predicate'] for edge_id, edge in graph['edges'].items()}
    for answer_i, answer in enumerate(answers):
        hashes = make_answer_hashes(answer, kg_edgetypes, question)
        for hash_item, qg_id, kg_id in hashes:
            varhash_to_kga_map[hash_item][answer_i] = kg_id
            varhash_to_answers[hash_item].append(answer_i)
            qg_type = question['nodes'][qg_id]['categories'] if 'categories' in question['nodes'][qg_id] else graph['nodes'][question['nodes'][qg_id]['ids'][0]]['categories']
            if isinstance(qg_type, list):
                qg_type = [qg_type[0]]
            else:
                qg_type = [qg_type]
            varhash_to_qg[hash_item] = (qg_id, qg_type)
            varhash_to_kg[hash_item].update(kg_id)
            varhash_to_answer_indices[hash_item].append(answer_i)
    coalescent_nodes = []
    for hash_item, answer_indices in varhash_to_answers.items():
        if len(answer_indices) > 1 and len(varhash_to_kg[hash_item]) > 1:
            # We have more than one answer that matches this pattern, and there is more than one kg node
            # in the variable spot.
            opportunity = Opportunity(hash_item, varhash_to_qg[hash_item], varhash_to_kg[hash_item], varhash_to_answer_indices[hash_item], varhash_to_kga_map[hash_item])
            if opportunity.get_qg_semantic_type() is not None:
                coalescent_nodes.append(opportunity)
    return coalescent_nodes
def make_answer_hashes(result, kg_edgetypes, question):
    """Given a single answer, find the hash for each answer node and return it along
    with the answer node that was varied, and the kg node id for that qnode in this answer"""
    # First combine the node and edge bindings into a single dictionary,
    # bindings = make_bindings(question, result)
    # we dont need to make bindings
    bindings = result.make_bindings()
    hashes = []
    for qg_id, kg_ids in result.node_bindings.items():
        newhash = make_answer_hash(bindings, kg_edgetypes, question, qg_id)
        hashes.append((newhash, qg_id, kg_ids))
    return hashes
def make_answer_hash(bindings, kg_edgetypes, question, qg_id):
    """given a combined node/edge bindings dictionary, plus the knowledge graph it points to and the question graph,
    create a key that characterizes the answer, except for one of the nodes (and its edges).
    The node that we're allowing to vary doesn't enter the hash.  The edges connected to that node, we replace
    by their types. That will then allow other answers with a different node but the same types of connections to
    that node to look the same under this hashing function"""
    # for some reason, the bindings are to lists?  Just grabbing the first (and only) element to the new bindings.
    #  Doing this because a result is now structured
    #  1. node_bindings
    #         # 2. Analyses
    #         #       a. edge_bindings, and
    #         #       b. score
    quick_bindings = {}
    quick_bindings.update(dict(bindings['node_bindings'].items()))
    for analysis in bindings['analyses']:
        quick_bindings.update(dict(analysis['edge_bindings'].items()))
    singlehash = {x: frozenset(y) for x, y in quick_bindings.items()}

    # take out the binding for qg_id
    del singlehash[qg_id]
    # Now figure out which edges hook to qg_id
    # Note that we're keeping source and target edges separately.  If the question doesn't define a direction,
    # we might end up with edges pointing either way, and we need to compare that as well.
    sedges = [edge_id for edge_id, edge in question['edges'].items() if edge['subject'] == qg_id]
    tedges = [edge_id for edge_id, edge in question['edges'].items() if edge['object'] == qg_id]
    # sedges = list(filter( lambda x: x['subject'] == qg_id, question['edges']))
    # tedges = list(filter( lambda x: x['object'] == qg_id, question['edges']))

    # The double comprehension is a bit of a mess, but our singlehash values are sets
    # What is happening is that a given s or t edge, we want a map from that qgid (the id in sedges) we want to
    # get the kg edges.  That's a set, we loop over it, and get the edgetypes from the kg for each, and make
    # a new set with all those types in it.  At the end, we have a map from an edge qg_id to a frozenset of
    # types for that edge for this answer.
    sedge_types = {se: frozenset([kg_edgetypes[x] for x in singlehash[se]]) for se in sedges}
    tedge_types = {se: frozenset([kg_edgetypes[x] for x in singlehash[se]]) for se in tedges}
    # Add in the edge types to our hash. this overwrites the qgid -> kgid mapping with type mapping
    singlehash.update(sedge_types)
    singlehash.update(tedge_types)
    # Take the original qgid connected edges out of the hash
    # for edge in sedges+tedges:
    #    del singlehash[f'{edge["id"]}']
    # Now we need to add back in types for the qg_id related edges.
    h = [xi for xi in singlehash.items()]
    h.sort()
    return tuple(h)
def get_opportunity(answerset):
    query_graph = answerset.get("query_graph", {})
    nodes = query_graph.get("nodes", {})
    allnodes = {}
    opportunity = {}
    alledges = {}

    for qg_id, node_data in nodes.items():
        if 'ids' in node_data and node_data.get('is_set'):
            category = node_data.get("categories", ["biolink:NamedThing"])[0]
            nodeset = set(node_data.get("ids", []))
            for node in nodeset:
                allnodes[node] = category
            opportunity['question_id'] = qg_id  # genes
            opportunity['question_type'] = category
        else:
            opportunity['answer_id'] = qg_id  # chemical
            opportunity['answer_type'] = node_data["categories"][0] if "categories" in node_data and node_data[
                "categories"] else None
            opportunity['qg_curies'] = allnodes

    for qg_eid, edge_data in query_graph.get("edges", {}).items():
        edgepredicate = {}
        edgepredicate['predicate'] = edge_data['predicates']
        if 'qualifier_constraints' in edge_data and len(edge_data.get('qualifier_constraints', []))>0:
            for i in edge_data.get('qualifier_constraints', [])[0].get('qualifier_set'):
                val = list(i.values())
                edgepredicate[val[0].split(':')[1]] = val[1]
        alledges[qg_eid] = edgepredicate

    opportunity['answer_edge'] = alledges
    return opportunity
def robokop_lookup(answerset):
    question_node = None
    query_graph = answerset.get("query_graph", {})
    for qg_id, node_data in query_graph.get("nodes", {}).items():
        if node_data.get('ids'):
            question_node = qg_id
            break

    for edge_data in query_graph.get("edges", {}).values():
        edge_data.pop("knowledge_type", None)

    lookup_response = requests.post(ROBOKOP_URL, json={"message":answerset})
     # logger.error(f'{ROBOKOP_URL} not reacheable' )
    return lookup_response, question_node
def drop_lookup_subclasses(lookup_result, question_qnode):
    question_qnode_ids = lookup_result['query_graph']['nodes'][question_qnode]['ids'][0] #MONDO....
    results = []
    for i, res in enumerate(lookup_result['results']):
        if res['node_bindings'][question_qnode][0]['id'] != question_qnode_ids:
            continue
        results.append(lookup_result['results'][i])
    lookup_result['results'] = results
    return lookup_result
def enrichment_based_infer(coalesced_message, lookup_message, predicates_to_exclude):
    qg = lookup_message.get("query_graph", {})
    for qg_id, node_data in qg.get("nodes", {}).items():
        if node_data.get('ids', []):
            question_qnode = qg_id
            # qnode_ids = node_data['ids'][0]
            question_category = node_data.get('categories', [])
        else:
            answer_qnode = qg_id

    for edge_id, _ in qg.get("edges", {}).items():
        qg_edge = edge_id

    track_question2lookup_edges(lookup_message, question_qnode, answer_qnode)
    track_lookup2enrich_edges(coalesced_message, question_qnode, answer_qnode)
    enriched_results = filter_enriched_message(coalesced_message)
    if not enriched_results:
        logger.exception(f"ROBOKOP Enrichment returned 0 enriched results")
        return {"message": lookup_message}, 200
    else:
        logger.info(f"{len(enriched_results)} of the {len(lookup_message['results'])} lookup results is enriched")
        messages_result = robokop_enrich_multistrider(coalesced_message, enriched_results, lookup_message, question_qnode, answer_qnode, question_category, qg_edge, predicates_to_exclude)
        return messages_result
def track_question2lookup_edges(rmsg, question_qnode, answer_node):
    # ab = {}
    ab_edges = {}
    qnode_ids = rmsg['query_graph']['nodes'][question_qnode]['ids'][0] #MONDO....
    for r in rmsg["results"]:
        b = r["node_bindings"][question_qnode][0]['id']
        a = r["node_bindings"][answer_node][0]['id']
        if b != qnode_ids:
            continue
        # ab.setdefault(a, []).append(b)
        for qedge in r['analyses'][0]['edge_bindings']:
            ab_edges.setdefault(a, []).extend([e['id'] for e in r['analyses'][0]['edge_bindings'][qedge]])
    # TRACK['ab'] = ab
    TRACK['ab_edges'] = ab_edges
def track_lookup2enrich_edges(rmsg, question_qnode, answer_node):
    # af = {}
    af_edges = {}
    af_edges_attributes = {}
    fa = {}
    auxg = rmsg["auxiliary_graphs"]
    for r in rmsg["results"]:
        a = r["node_bindings"][answer_node][0]['id']
        for enrich_key in r["enrichments"]:
            # Let's exclude property enriched results for now
            if enrich_key.startswith('_n_ac'):
                continue
            attributes = auxg.get(enrich_key, {}).get("attributes", {})
            f = [atrb.get("value") for atrb in attributes if ((atrb["attribute_type_id"]=="biolink:subject") or  (atrb["attribute_type_id"]=="biolink:object")) ][0]
            f_pred = [atrb.get("value") for atrb in attributes if (atrb["attribute_type_id"]=="biolink:predicate")][0]
            af_edges.setdefault((f,f_pred), set()).update(auxg.get(enrich_key, {}).get("edges", {}))
            af_edges_attributes[(f,f_pred)] = attributes
            # af.setdefault(a, set()).add(f)
            fa.setdefault((f,f_pred), set()).add(a)
    # TRACK['af'] = af
    TRACK['fa'] = fa
    TRACK['af_edges'] = af_edges
    TRACK['af_edges_attributes'] = af_edges_attributes
def filter_enriched_message(coalesced_message):
    """Decides whether the input is an enriched message."""
    # check to ensure there are auxiliary graphs in the message
    # this will fail if the input looks like e.g.:
    #  "auxiliary_graphs": None
    # message = coalesced_message
    if "auxiliary_graphs" not in coalesced_message:
        return None

    enriched_results = filter(lambda result: result.get('enrichments'), coalesced_message.get('results', []))
    return list(enriched_results)
async def robokop_enrich_multistrider(coalesced_message, enriched_results, lookup_message, question_qnode, answer_qnode, question_category, qg_edge, predicates_to_exclude):
    enrichment_rules, pe_finalresult_list, updated_kg = expand_enriched_results(coalesced_message, enriched_results, question_qnode, answer_qnode, finaltype = question_category)
    qg = (coalesced_message["query_graph"]).copy()
    mergedresults = await parse_robokop_messages(lookup_message, updated_kg, enrichment_rules, qg, question_qnode, answer_qnode, qg_edge, predicates_to_exclude)
    return mergedresults
def finalenrich2lookup_edges(rmsg, question_qnode, answer_qnode, qg_edge, qg_predicate, predicates_to_exclude):
    original_query_graph = rmsg["message"]["query_graph"]
    qnode_ids = original_query_graph['nodes'][question_qnode]["ids"][0]
    rmsg_edges = rmsg["message"]["knowledge_graph"]["edges"]
    aux_graphs = {}
    new_graph_edges = {}
    result = {"message": {"knowledge_graph": {"nodes": {}, "edges": {}}, "results": [], "auxiliary_graphs": {}}}
    result["message"]["knowledge_graph"] = rmsg["message"]["knowledge_graph"].copy()
    af_edges = TRACK.get('af_edges', {})
    fa = TRACK.get('fa',{})
    af_edges_attributes = TRACK.get('af_edges_attributes', {})
    ab_edges = TRACK.get('ab_edges', {})
    binding_dict = {}
    for r in rmsg["message"]["results"]:
        mid = list(set(r['node_bindings'].keys()).difference([answer_qnode]))[0]
        new_a2f_edges = [e['id'] for bdedge in r['analyses'][0]['edge_bindings'] for e in
                  r['analyses'][0]['edge_bindings'].get(bdedge)]  # Serves as edges for auxgraph3
        f = r["node_bindings"][mid][0]['id']

        #To uphold the exclusion of those bad predicates in the enrichment calculation
        f_preds = [rmsg_edges[edge_0].get("predicate") for edge_0 in new_a2f_edges if rmsg_edges[edge_0].get("predicate") not in predicates_to_exclude]
        if not f_preds:
            continue
        enrichmentas = [e for f_pred in f_preds if (f, f_pred) in fa for e in fa[(f, f_pred)]]
        # meaning that the (enrichment node and its predicate does not map to any lookup node)
        if not enrichmentas:
            continue
        new_a_binding = r["node_bindings"][answer_qnode]
        new_a = r["node_bindings"][answer_qnode][0]['id']
        resource_id = 'infores:aragorn-robokop'
        # bindings: b --> a_new

        one_result = {'node_bindings': {}, 'analyses': []}
        new_b_binding = [{'id': qnode_ids, 'qnode_id': qnode_ids}]
        sources = [{'resource_id': 'infores:robokop',
                                'resource_role': 'aggregator_knowledge_source',
                                'upstream_resource_ids': ['infores:automat-robokop']}]
        newkgedge = {'subject': new_a_binding[0]['id'], 'predicate': qg_predicate, 'object': qnode_ids,
                     'sources': sources,
                     'qualifiers': []}
        tempedge = newkgedge.copy()
        tempedge['sources'] = str(tempedge['sources'])
        if 'qualifiers' in tempedge:
            tempedge['qualifiers'] = str(tempedge['qualifiers'])
        if 'attributes' in tempedge:
            tempedge['attributes'] = str(tempedge['attributes'])
        kgedge = str(hash(frozenset(tempedge.items())))
        if kgedge not in new_graph_edges:
            new_graph_edges.update({kgedge: newkgedge})
        eb = {qg_edge: [{'id': kgedge}]}
        one_result['node_bindings'].update({question_qnode: new_b_binding})
        one_result['node_bindings'].update({answer_qnode: new_a_binding})
        one_result['analyses'].append({'resource_id': resource_id, 'edge_bindings': eb})

        if new_a in binding_dict:
            existing_bd = binding_dict[new_a]
            if {'id': kgedge} in existing_bd['analyses'][0]['edge_bindings'][qg_edge]:
                continue
            else:
                existing_bd['analyses'][0]['edge_bindings'][qg_edge].append({'id': kgedge, 'attributes': []})
        else:
            binding_dict[new_a] = one_result


            # make new knowledge graph edges

            # b-a-f-a_new
            # bindings: b --> a_new
            # auxg2: a_new --> f
            # auxg1: f --> a
            # auxg0: a --> b
        # auxgnew: a_new --> f
        enrichmentaf_edges = [af_edge for f_pred in
                              f_preds for af_edge in af_edges.get((f, f_pred), {}) if af_edge]
        enrichmentaf_attributes = [af_edges_attributes.get((f, f_pred), {}) for f_pred in
                                   f_preds]

        # auxg1^0: f --> a ^ a --> b
        ab_old_edges = [ab_edges.get(enrichmenta) for enrichmenta in enrichmentas]  # Serves as edges for auxgraph2
        b_2_old_a_edge = {edge for edge_list in ab_old_edges if edge_list is not None for edge in edge_list}
        support_edges = new_a2f_edges + enrichmentaf_edges + list(b_2_old_a_edge)

        aux_graph_id = f'{new_a}--{"_".join(f_preds)}--{f}--{"_".join(f_preds)}--{len(enrichmentas)} {answer_qnode}--{qg_predicate}--{qnode_ids}'

        if aux_graph_id in aux_graphs:
            # Extend the existing edges for the given aux_graph_id
            aux_graphs[aux_graph_id]['edges'].extend(support_edges)
        else:
            # Create a new entry if aux_graph_id doesn't exist
            aux_graphs.setdefault(aux_graph_id, {}).update({'edges': support_edges, 'attributes': make_trapi_attributes(enrichmentaf_attributes)})

        aux_graphs[aux_graph_id]['edges'] = list(set(aux_graphs[aux_graph_id]['edges']))

        # update the kg edges with the support graphs
        if new_graph_edges.get(kgedge, {}):
            if new_graph_edges.get(kgedge, {}).get("attributes", []):
                if new_graph_edges[kgedge].get("attributes", [])[0].get(
                        "value",
                        []) and aux_graph_id not in new_graph_edges[kgedge].get("attributes", [])[0].get(
                        "value", []):
                    new_graph_edges[kgedge].get("attributes", [])[0].get(
                        "value", []).extend([aux_graph_id])
            else:
                new_graph_edges[kgedge].update({'attributes': [
                    {'attribute_type_id': "biolink:support_graphs",
                     "value": [aux_graph_id]}]})


    result["message"]["query_graph"] = original_query_graph
    result["message"]["results"] = list(binding_dict.values())
    result["message"]["knowledge_graph"]["edges"].update(new_graph_edges)
    result["message"]["auxiliary_graphs"].update(aux_graphs)

    return result
def make_trapi_attributes(attributes_data):
    result_dict = defaultdict(lambda: {'attribute_type_id': None, 'value': []})

    for sublist in attributes_data:
        for entry in sublist:
            attribute_type_id = entry['attribute_type_id']
            value = entry['value']

            result_dict[attribute_type_id]['attribute_type_id'] = attribute_type_id

            if isinstance(value, list):
                result_dict[attribute_type_id]['value'].extend(value)
            else:
                result_dict[attribute_type_id]['value'].append(value)

    result_list = list(result_dict.values())

    return result_list

def expand_enriched_results(coalesced_message, enriched_results, question_qnode, answer_qnode, finaltype=[]):
    """
        Performs rule expansion for enrichmentbased creative mode,
        :param coalesced_message from answer coalesce:
        :param params: contains the answer_qnode and question_qnode
        :param guid:
        :return:
            :Graph Enriched rules:
            :Property enrichment results:
            :A new knowledge graph updated with property enriched edges
                :new_results --treats-->questionnode_ids
    """
    logs = coalesced_message.get('logs', [])
    auxiliary_graphs = coalesced_message['auxiliary_graphs']

    qg = deepcopy(coalesced_message["query_graph"])
    kg = coalesced_message["knowledge_graph"]
    for eid, edge in qg["edges"].items():
        if "knowledge_type" in edge:
            del edge["knowledge_type"]
    # To avoid repeating operations for the enriched nodes
    # since an enrichment appears in multiple results
    done = set()
    enrichment_rules = []  # enrichment_rules contains the expanded rules eg ?Chemical- predicate->enrichedgene1 converted to trapi query graph

    pe_finalresult_list = []
    for result in enriched_results:
        for enrichment in result['enrichments']:
            if enrichment in done:
                continue
            if auxiliary_graphs[enrichment].get('edges'):
                auxg_edgeattributes = auxiliary_graphs[enrichment]['attributes']
                genriched_res = GEnrichment(kg, qg, auxg_edgeattributes, answer_qnode, logs)
                # genriched_res = Enrichment(None, auxg_edgelist, kg, qg, question_qnode, answer_qnode, logs)
                enrichment_rules.extend(genriched_res.make_rules(finaltype))
            else:
                pass
                #TODO Property enrichment section
                # attribute_list = auxiliary_graphs[enrichment]['attributes']
                # role = next(iter({value['id'] for key, value in nb.items() if key == 'biolink:chemical_role'}))

                # property_list = get_enriched_property(attribute_list)
                # # penriched_res = Enrichment(result, [], kg, qg, question_qnode, answer_qnode, logs)
                # penriched_res = PEnrichment(result, kg, qg, question_qnode, answer_qnode, auxiliary_graphs)
                # result_bindings, status_code = penriched_res.get_property_creativeresult(enrichment, property_list, guid)
                # if result_bindings:
                #     pe_finalresult_list.extend(result_bindings)

            done.add(enrichment)
    # The updated KG
    # kg = penriched_res.kg
    # parse messages/rules to get final results
    # mergedresults, merges_status = await parse_messages(lookup_kg, enrichment_rules, qg, guid, params)

    return enrichment_rules, pe_finalresult_list, kg
async def parse_robokop_messages(lookup_message, updated_kg, rule_qgs,  qg, question_qnode, answer_qnode, qg_edge, predicates_to_exclude):
    original_predicate = [qg['edges'][edge]['predicates'][0] for edge in qg['edges']][0]
    logger.info(f"sending {len(rule_qgs)} rules to {ROBOKOP_URL}")
    result_messages = []
    tasks = []
    for message in list(rule_qgs):
        tasks.append(asyncio.create_task(make_lookup_request(message)))
    responses = await asyncio.gather(*tasks)

    total_results = 0
    for response, status_code in responses:
        if status_code == 200:
            rmessage = PDResponse(**response).dict(exclude_none=True)
            filter_repeated_nodes(rmessage)
            num_results = len(rmessage["message"].get("results", []))
            total_results+=num_results
            if num_results > 0 and num_results < 10000: # more than this number of results and you're into noise.
                result_messages.append(rmessage)
        else:
            logger.error(f"{status_code} returned.")

    if len(result_messages) > 0:
        logger.info(f"Returned {total_results} results")
        # We have to stitch stuff together again

        mergedresults = combine_enriched_messages(original_predicate, qg,
                                           lookup_message, updated_kg, result_messages, question_qnode, answer_qnode, qg_edge, predicates_to_exclude)

        return mergedresults
    else:
        mergedresults = {"message": {"knowledge_graph": {"nodes": {}, "edges": {}}, "results": []}}
    # The merged results will have some expanded query, we want the original query.
    return mergedresults

async def make_lookup_request(message):
    return lookup(message['message'])

def filter_repeated_nodes(response):
    """We have some rules that include e.g. 2 chemicals.   We don't want responses in which those two
    are the same.   If you have A-B-A-C then what shows up in the ui is B-A-C which makes no sense."""
    original_result_count = len(response["message"].get("results",[]))
    if original_result_count == 0:
        return
    results = list(filter( lambda x: has_unique_nodes(x), response["message"]["results"] ))
    response["message"]["results"] = results
    if len(results) != original_result_count:
        filter_kgraph_orphans(response)

def has_unique_nodes(result):
    """Given a result, return True if all nodes are unique, False otherwise"""
    seen = set()
    for qnode, knodes in result["node_bindings"].items():
        knode_ids = frozenset([knode["id"] for knode in knodes])
        if knode_ids in seen:
            return False
        seen.add(knode_ids)
    return True

def filter_kgraph_orphans(message):
    """Remove from the knowledge graph any nodes and edges not references by a result, as well as any aux_graphs.
    We do this by starting at results, marking reachable nodes & edges, then remove anything that isn't marked
    There are multiple sources:
    1. Result node bindings
    2. Result.Analysis edge bindings
    3. Result.Analysis support graphs
    4. support graphs from edges found in 2
    5. For all the auxgraphs collect their edges and nodes
    Note that this will fail to find edges and nodes that are recursive.  So if an edge is supported by an edge,
    and that edge is supported by a third edge, then that third edge won't get marked, and will be removed.
    ATM, this is acceptable, but it'll need to be fixed.
    """
    #First, find all the result nodes and edges
    try:
        logger.info(f'filtering kgraph.')
        results = message.get('message',{}).get('results',[])
        nodes = set()
        edges = set()
        auxgraphs = set()
        #1. Result node bindings
        for result in results:
            for qnode,knodes in result.get('node_bindings',{}).items():
                nodes.update([ k['id'] for k in knodes ])
        #2. Result.Analysis edge bindings
        for result in results:
            for analysis in result.get('analyses',[]):
                for qedge, kedges in analysis.get('edge_bindings', {}).items():
                    edges.update([k['id'] for k in kedges])
        #3. Result.Analysis support graphs
        for result in results:
            for analysis in result.get('analyses',[]):
                for auxgraph in analysis.get('support_graphs',[]):
                    auxgraphs.add(auxgraph)
        # 4. Support graphs from edges in 2
        for edge in edges:
            for attribute in message.get('message',{}).get('knowledge_graph',{}).get('edges',{}).get(edge,{}).get('attributes',{}):
                if attribute.get('attribute_type_id',None) == 'biolink:support_graphs':
                    auxgraphs.update(attribute.get('value',[]))
        # 5. For all the auxgraphs collect their edges and nodes
        for auxgraph in auxgraphs:
            aux_edges = message.get('message',{}).get('auxiliary_graphs',{}).get(auxgraph,{}).get('edges',[])
            for aux_edge in aux_edges:
                if aux_edge not in message["message"]["knowledge_graph"]["edges"]:
                    logger.warning(f" aux_edge {aux_edge} not in knowledge_graph.edges")
                    continue
                edges.add(aux_edge)
                nodes.add(message["message"]["knowledge_graph"]["edges"][aux_edge]["subject"])
                nodes.add(message["message"]["knowledge_graph"]["edges"][aux_edge]["object"])
        #now remove all knowledge_graph nodes and edges that are not in our nodes and edges sets.
        kg_nodes = message.get('message',{}).get('knowledge_graph',{}).get('nodes',{})
        message['message']['knowledge_graph']['nodes'] = { nid: ndata for nid, ndata in kg_nodes.items() if nid in nodes }
        kg_edges = message.get('message',{}).get('knowledge_graph',{}).get('edges',{})
        message['message']['knowledge_graph']['edges'] = { eid: edata for eid, edata in kg_edges.items() if eid in edges }
        message["message"]["auxiliary_graphs"] = { auxgraph: adata for auxgraph, adata in message["message"].get("auxiliary_graphs",{}).items() if auxgraph in auxgraphs }
        logger.info(f'returning filtered kgraph.')
        return message,200
    except Exception as e:
        print(e)
        logger.error(e)
        return None,500

def combine_enriched_messages(original_predicate, qg,
                                           lookup_message, updated_kg, result_messages, question_qnode, answer_qnode, qg_edge, predicates_to_exclude):
    pydantic_kgraph = KnowledgeGraph.parse_obj({"nodes": {}, "edges": {}})
    for rm in result_messages:
        pydantic_kgraph.update(KnowledgeGraph.parse_obj(rm["message"]["knowledge_graph"]))

    pydantic_kgraph.update(KnowledgeGraph.parse_obj(updated_kg))

    result = PDResponse(**{
    "message": {"query_graph": {"nodes": {}, "edges": {}},
                "knowledge_graph": {"nodes": {}, "edges": {}},
                "results": [],
                "auxiliary_graphs": {}}}).dict(exclude_none=True)
    result["message"]["query_graph"] = qg
    result["message"]["knowledge_graph"] = pydantic_kgraph.dict()

    # The result with the direct lookup needs to be handled specially.   It's the one with the lookup query graph
    for result_message in result_messages:
        if not queries_equivalent(result_message["message"]["query_graph"], lookup_message.get('query_graph', {})):
            result["message"]["results"].extend(result_message["message"]["results"])
    lookup_results = lookup_message["results"]
    result = finalenrich2lookup_edges(result, question_qnode, answer_qnode, qg_edge, original_predicate, predicates_to_exclude)
    merged_result = merge_enriched_results_by_node(result, answer_qnode, lookup_results)
    return merged_result
def queries_equivalent(query1,query2):
    """Compare 2 query graphs.  The nuisance is that there is flexiblity in e.g. whether there is a qualifier constraint
    as none or it's not in there or its an empty list.  And similar for is_set and is_set is False.
    """
    q1 = query1.copy()
    q2 = query2.copy()
    for q in [q1,q2]:
        for node in q["nodes"].values():
            if "is_set" in node and node["is_set"] is False:
                del node["is_set"]
            if "constraints" in node and len(node["constraints"]) == 0:
                del node["constraints"]
        for edge in q["edges"].values():
            if "attribute_constraints" in edge and len(edge["attribute_constraints"]) == 0:
                del edge["attribute_constraints"]
            if "qualifier_constraints" in edge and len(edge["qualifier_constraints"]) == 0:
                del edge["qualifier_constraints"]
    return q1 == q2
def merge_enriched_results_by_node(result_message, merge_qnode, lookup_results):
    """This assumes a single result message, with a single merged KG.  The goal is to take all results that share a
    binding for merge_qnode and combine them into a single result.
    Assumes that the results are not scored."""
    grouped_results = group_results_by_qnode(merge_qnode, result_message, lookup_results)
    original_qnodes = result_message["message"]["query_graph"]["nodes"].keys()
    # TODO : I'm sure there's a better way to handle this with asyncio
    new_results = []
    for r in grouped_results:
        new_result = merge_answer(result_message, r, grouped_results[r], original_qnodes)
        new_results.append(new_result)
    result_message["message"]["results"] = new_results
    return result_message
def group_results_by_qnode(merge_qnode, result_message, lookup_results):
    """merge_qnode is the qnode_id of the node that we want to group by
    result_message is the response message, and its results element  contains all of the creative mode results
    lookup_results is just a results element from the lookup mode query.
    """
    original_results = result_message["message"].get("results", [])
    # group results
    grouped_results = defaultdict( lambda: {"creative": [], "lookup": []})
    # Group results by the merge_qnode
    for result_set, result_key in [(original_results, "creative"), (lookup_results, "lookup")]:
        for result in result_set:
            answer = result["node_bindings"][merge_qnode]
            bound = frozenset([x["id"] for x in answer])
            grouped_results[bound][result_key].append(result)
    return grouped_results
def merge_answer(result_message, answer, results, qnode_ids, robokop=False):
    """Given a set of results and the node identifiers of the original qgraph,
    create a single message.
    result_message has to contain the original query graph
    The original qgraph is a creative mode query, which has been expanded into a set of
    rules and run as straight queries using either strider or robokopkg.
    results contains both the lookup results and the creative results, separated out by keys
    Each result coming in is now structured like this:
    result
        node_bindings: Binding to the rule qnodes. includes bindings to original qnode ids
        analysis:
            edge_bindings: Binding to the rule edges.
    To merge the answer, we need to
    0) Filter out any creative results that exactly replicate a lookup result
    1) create node bindings for the original creative qnodes
    2) convert the analysis of each input result into an auxiliary graph
    3) Create a knowledge edge corresponding to the original creative query edge
    4) add the aux graphs as support for this knowledge edge
    5) create an analysis with an edge binding from the original creative query edge to the new knowledge edge
    6) add any lookup edges to the analysis directly
    """
    # 0. Filter out any creative results that exactly replicate a lookup result
    # How does this happen?   Suppose it's an inferred treats.  Lookup will find a direct treats
    # But a rule that ameliorates implies treats will also return a direct treats because treats
    # is a subprop of ameliorates. We assert that the two answers are the same if the set of their
    # kgraph edges are the same.
    # There are also cases where subpredicates in rules can lead to the same answer.  So here we
    # also unify that.   If we decide to pass rules along with the answers, we'll have to be a bit
    # more careful.
    lookup_edgesets = [get_edgeset(result) for result in results["lookup"]]
    creative_edgesets = set()
    creative_results = []
    for result in results["creative"]:
        creative_edges = get_edgeset(result)
        if creative_edges in lookup_edgesets:
            continue
        elif creative_edges in creative_edgesets:
            continue
        else:
            creative_edgesets.add(creative_edges)
            creative_results.append(result)
    results["creative"] = creative_results
    # Create node bindings for the original creative qnodes and lookup qnodes
    mergedresult = {"node_bindings": {}, "analyses": []}
    serkeys = defaultdict(set)
    for q in qnode_ids:
        mergedresult["node_bindings"][q] = []
        for result in results["creative"] + results["lookup"]:
            for nb in result["node_bindings"][q]:
                serialized_binding = json.dumps(nb,sort_keys=True)
                if serialized_binding not in serkeys[q]:
                    mergedresult["node_bindings"][q].append(nb)
                    mergedresult["node_bindings"][q] = [{k: v for d in mergedresult["node_bindings"][q] for k, v in d.items()}]
                    serkeys[q].add(serialized_binding)

    # create an analysis with an edge binding from the original creative query edge to the new knowledge edge
    knowledge_edge_ids = creative_edgesets.union(lookup_edgesets)
    knowledge_edge_ids = set(list(kid)[0] for kid in knowledge_edge_ids)
    # create an analysis with an edge binding from the original creative query edge to the new knowledge edge
    qedge_id = list(result_message["message"]["query_graph"]["edges"].keys())[0]
    source = "infores:aragorn-robokop"
    analysis = {
        "resource_id": source,
        "edge_bindings": {qedge_id: [{"id": kid} for kid in knowledge_edge_ids]}
    }
    mergedresult["analyses"].append(analysis)

    # # add any lookup edges to the analysis directly
    # for result in results["lookup"]:
    #     for analysis in result["analyses"]:
    #         for qedge in analysis["edge_bindings"]:
    #             if qedge not in mergedresult["analyses"][0]["edge_bindings"]:
    #                 mergedresult["analyses"][0]["edge_bindings"][qedge] = []
    #             mergedresult["analyses"][0]["edge_bindings"][qedge].extend(analysis["edge_bindings"][qedge])
    return mergedresult
# TODO move into operations? Make a translator op out of this
def merge_results_by_node(result_message, merge_qnode, lookup_results, robokop=False):
    """This assumes a single result message, with a single merged KG.  The goal is to take all results that share a
    binding for merge_qnode and combine them into a single result.
    Assumes that the results are not scored."""
    grouped_results = group_results_by_qnode(merge_qnode, result_message, lookup_results)
    original_qnodes = result_message["message"]["query_graph"]["nodes"].keys()
    # TODO : I'm sure there's a better way to handle this with asyncio
    new_results = []
    for r in grouped_results:
        new_result = merge_answer(result_message, r, grouped_results[r], original_qnodes, robokop)
        new_results.append(new_result)
    result_message["message"]["results"] = new_results
    return result_message
def get_edgeset(result):
    """Given a result, return a frozenset of any knowledge edges in it"""
    edgeset = set()
    for analysis in result["analyses"]:
        for edge_id, edgelist in analysis["edge_bindings"].items():
            edgeset.update([e["id"] for e in edgelist])
    return frozenset(edgeset)
