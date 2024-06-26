from src.components import MCQDefinition, NewEdge, Lookup_params
from typing import Dict
import uuid
import orjson

#This is the single place to create TRAPI elements.  It is the only place that should be creating TRAPI elements.

infores = "infores:answercoalesce"


def create_knowledge_graph_node( curie, categories, name=None ):
    """
    Create a TRAPI knowledge graph node.
    """
    categories = categories if isinstance(categories, list) else [categories]
    return {
        "categories": categories,
        "name": name,
        "attributes": []
    }


def create_knowledge_graph_edge_from_component( input_edge: NewEdge ):
    # The NewEdge predicate has both the predicate and qualifiers in it:
    if not isinstance(input_edge.predicate, str):
        print("wtf")
    jsonpred = orjson.loads(input_edge.predicate)
    predicate_only = jsonpred["predicate"]
    qualifiers = []
    for key, value in jsonpred.items():
        if key != "predicate":
            qualifiers.append({"qualifier_type_id": f"biolink:{key}", "qualifier_value": value})
    return create_knowledge_graph_edge(input_edge.source, input_edge.target, predicate_only,
                                       qualifiers=qualifiers, sources=input_edge.prov)


def create_knowledge_graph_edge( subject, object, predicate, qualifiers=None, sources=None, attributes=None ):
    """
    Create a TRAPI knowledge graph edge.
    """
    if attributes is None:
        attributes = []
    if sources is None:
        sources = []
    edge = {
        "subject": subject,
        "object": object,
        "predicate": predicate,
        "attributes": attributes,
        "sources": sources
    }
    if qualifiers:
        edge["qualifiers"] = qualifiers
    if len(edge["sources"]) == 0:
        add_local_prov(edge)
    return edge


def add_node_to_knowledge_graph( response, node_id, node ):
    """
    Add a TRAPI knowledge graph node to a TRAPI knowledge graph.
    """
    if not response["message"].get("knowledge_graph"):
        response["message"]["knowledge_graph"] = {"nodes": {}, "edges": {}}
    if "nodes" not in response["message"]["knowledge_graph"]:
        response["message"]["knowledge_graph"]["nodes"] = {}
    nodes = response["message"]["knowledge_graph"]["nodes"]
    if node_id not in nodes:
        nodes[node_id] = node


def add_edge_to_knowledge_graph( response, edge: Dict, edge_id=None ):
    """
    Add a TRAPI knowledge graph edge to a TRAPI knowledge graph.
    """
    if "knowledge_graph" not in response["message"]:
        response["message"]["knowledge_graph"] = {"nodes": {}, "edges": {}}
    if "edges" not in response["message"]["knowledge_graph"]:
        response["message"]["knowledge_graph"]["edges"] = {}
    edges = response["message"]["knowledge_graph"]["edges"]
    if edge_id is None:
        edge_id = str(uuid.uuid4())
    edges[edge_id] = edge
    return edge_id


def add_enrichment_edge_to_knowledge_graph( response, edge ):
    """
    Add a TRAPI knowledge graph edge to a TRAPI knowledge graph.
    The edge is defined as NewEdge in components.
    The only tricky part is that the predicate there also has the quaifiers in it
    qualifiers look like:
    'qualifiers': [{'qualifier_type_id': 'biolink:object_direction_qualifier',
                    'qualifier_value': 'decreased'},
                    {'qualifier_type_id': 'biolink:qualified_predicate',
                    'qualifier_value': 'biolink:causes'},
                    {'qualifier_type_id': 'biolink:object_aspect_qualifier',
                    'qualifier_value': 'activity_or_abundance'}]
    """
    edges = response["message"]["knowledge_graph"]["edges"]
    new_edge = {
        "predicate": edge.predicate["predicate"],
        "subject": edge.source,
        "object": edge.target,
        "attributes": []
    }
    # is there anything else in the predicate? it's qualifiers
    if len(edge["predicate"]) > 1:
        new_edge["qualifiers"] = []
        for key, value in edge["predicate"].items():
            if key != "predicate":
                new_edge["qualifiers"].append({"qualifier_type_id": key, "qualifier_value": value})
    new_edge["sources"] = edge.prov
    new_edge_id = f"{edge.source}-{edge.predicate['predicate']}-{edge.target}"
    base = new_edge_id
    ned_count = 0
    while new_edge_id in edges:
        new_edge_id = f"{base}-{ned_count}"
        ned_count += 1
    edges[new_edge_id] = new_edge
    return new_edge_id


def add_auxgraph_for_enrichment( in_message, direct_edge_id, member_of_ids, new_curie ):
    """
    Add an auxilary graph to the TRAPI response for enrichment.
    In this case, we have a direct edge from an input_id to the enriched node.  That edge is in the KG, and its
    id is direct_edge_id.  The member_of_ids holds edge_ids of the edges connecting the set query node to the
    input id, indexted by the input id. So we need to look at the direct edge, figure out which one is the input,
    and then grab the edge id from the member_of_ids.
    Once we have these two ids, we can create the auxialiry graph which will consist of
    (set uuid)-[member_of]-(input curie)-[enriched_edge]-(enriched_node)
    """
    # get the direct edge
    direct_edge = in_message["message"]["knowledge_graph"]["edges"][direct_edge_id]
    # get the input and output curies
    subject_curie = direct_edge["subject"]
    object_curie = direct_edge["object"]
    # figure out which one is the input
    if subject_curie == new_curie:
        input_curie = object_curie
    else:
        input_curie = subject_curie
    # get the member_of edge ids
    member_of_edge_id = member_of_ids[input_curie]
    # create the aux graph
    aux_graph = {
        "edges": [
            direct_edge_id,
            member_of_edge_id
        ],
        "attributes": []
    }
    aux_graph_id = f"SG:_{direct_edge_id}"
    if "auxiliary_graphs" not in in_message["message"]:
        in_message["message"]["auxiliary_graphs"] = {}
    in_message["message"]["auxiliary_graphs"][aux_graph_id] = aux_graph
    return aux_graph_id


def add_enrichment_edge( in_message, enrichment, mcq_definition: MCQDefinition, aux_graph_ids ):
    """
    Add an enrichment edge to the TRAPI response.
    The enrichment edge is an inferred edge connecting the enriched node to the input node.
    It doesn't need to match the predicate / qualifiers of the input edge, b/c it can be a subclass.
    """
    #Create the edge, orienting it correctly
    epred = orjson.loads(enrichment.predicate)
    new_edge = {
        "predicate": epred["predicate"],
        "attributes": [{"attribute_type_id": "biolink:p_value", "value": enrichment.p_value}]
    }
    if mcq_definition.edge.group_is_subject:
        new_edge["subject"] = mcq_definition.group_node.uuid
        new_edge["object"] = enrichment.enriched_node.new_curie
    else:
        new_edge["object"] = mcq_definition.group_node.uuid
        new_edge["subject"] = enrichment.enriched_node.new_curie
    # Add any qualifiers
    qualifiers = []
    for key, value in epred.items():
        if key != "predicate":
            qualifiers.append({"qualifier_type_id": f"biolink:{key}", "qualifier_value": value})
    new_edge["qualifiers"] = qualifiers
    # Add provenance
    add_local_prov(new_edge)
    # Add KL/AT
    add_prediction_klat(new_edge)
    # Add the auxiliary graphs
    add_aux_graphs(new_edge, aux_graph_ids)
    # Add the edge to the KG
    new_edge_id = str(uuid.uuid4())
    edges = in_message["message"]["knowledge_graph"]["edges"]
    edges[new_edge_id] = new_edge
    return new_edge_id


def convert_qualifier_constraint_to_qualifiers( qualifier_constraints ):
    """
    Convert a list of TRAPI qualifier constraints to TRAPI qualifiers.
    """
    if len(qualifier_constraints) == 0:
        return []
    qc = qualifier_constraints[0]
    if len(qc) == 0:
        return []
    qs = qc["qualifier_set"]
    qualifiers = qs
    return qualifiers


def add_local_prov( edge ):
    """
    Add the provenance information to an enrichment edge.
    """
    new_provenance = {"resource_id": infores,
                      "resource_role": "primary_knowledge_source"}
    edge["sources"] = [new_provenance]


def add_klat( edge, kl, at ):
    """
    Add the knowledge level and attribute type to an edge.
    """
    attributes = edge["attributes"]
    attributes += [
        {
            "attribute_type_id": "biolink:agent_type",
            "value": at,
            "attribute_source": infores
        },
        {
            "attribute_type_id": "biolink:knowledge_level",
            "value": kl,
            "attribute_source": infores
        }
    ]


def add_prediction_klat( edge ):
    add_klat(edge, "prediction", "computational_model")


#TODO: what are the appropriate KL/AT if we are adding member_of edges?
def add_member_of_klat( edge ):
    add_klat(edge, "???", "???")


def add_aux_graphs( new_edge, aux_graph_ids ):
    """
    Add the auxiliary graphs to an edge.
    """
    new_edge["attributes"].append(
        {
            "attribute_type_id": "biolink:support_graphs",
            "value": aux_graph_ids,
            "attribute_source": infores
        }
    )


def add_enrichment_result( in_message, enriched_node, enrichment_edge_id, mcq_definition: MCQDefinition ):
    if "results" not in in_message["message"]:
        in_message["message"]["results"] = []
    result = {"node_bindings": {}, "analyses": [{"edge_bindings": {}, "resource_id": infores, "attributes": []}]}
    in_message["message"]["results"].append(result)
    # There should be a node binding from the input (group) node qnode_id to the input node uuid
    result["node_bindings"][mcq_definition.group_node.qnode_id] = [
        {"id": mcq_definition.group_node.uuid, "attributes": []}]
    # There should be a node binding from the enriched node qnode_id to the enriched node curie
    result["node_bindings"][mcq_definition.enriched_node.qnode_id] = [{"id": enriched_node.new_curie, "attributes": []}]
    # There should be an edge binding from the enrichment edge qedge_id to the enrichment edge uuid
    result["analyses"][0]["edge_bindings"][mcq_definition.edge.qedge_id] = [
        {"id": enrichment_edge_id, "attributes": []}]


def create_edgar_enrichment_edge( enrichment_pvalue, input_edge=None, source=None, target=None, predicate_only=None ):
    """
    Add an enrichment edge to the TRAPI response.
    The enrichment edge is an inferred edge connecting the enriched node to the input lookup node.

    one can either use the input edge object OR specify the source, target and predicate_only.
    The former works for graph_enrichment while the latter for property_enrichment

    """
    if input_edge:
        method = "graph_enrichment"
        enrichment_edge = create_knowledge_graph_edge_from_component(input_edge)
        new_edge_id = f"e_{enrichment_edge.get('subject')}_{enrichment_edge.get('predicate')}_{enrichment_edge.get('object')}"
    else:
        method = "property_enrichment"
        enrichment_edge = create_knowledge_graph_edge(source, target, predicate_only)
        new_edge_id = f"n_{source}_{predicate_only}_{target}"

    enrichment_edge["attributes"].append({"attribute_type_id": "scoring_method", "value": method})
    enrichment_edge["attributes"].append({"attribute_type_id": "biolink:p_value", "value": enrichment_pvalue})
    # Add provenance
    add_local_prov(enrichment_edge)
    # Add KL/AT
    add_prediction_klat(enrichment_edge)
    # Add the auxiliary graphs
    # add_aux_graphs(new_edge, aux_graph_ids)
    # Add the edge to the KG

    return new_edge_id, enrichment_edge


def add_edgar_enrichment_to_uuid_edge( in_message, uuid, aux_graph_ids, predicate_only, enrichment ):
    """
    Add an enrichment edge to the TRAPI response.
    The enrichment edge is an inferred edge connecting the enriched node to the input node.
    It doesn't need to match the predicate / qualifiers of the input edge, b/c it can be a subclass.
    """

    predicate_only = predicate_only if "predicate" not in predicate_only else orjson.loads(predicate_only).get("predicate")

    new_edge = {
        "predicate": predicate_only,
        "attributes": [],
        "qualifiers": []
    }

    if isinstance(enrichment, str):
        # if it is a property node
        new_edge["object"] = uuid
        new_edge["subject"] = enrichment

    else:
        if enrichment.is_source:
            new_edge["object"] = uuid
            new_edge["subject"] = enrichment.enriched_node.new_curie
        else:
            new_edge["subject"] = uuid
            new_edge["object"] = enrichment.enriched_node.new_curie

    # Add provenance
    add_local_prov(new_edge)

    # Add the auxiliary graphs
    add_aux_graphs(new_edge, aux_graph_ids)
    # Add the edge to the KG
    new_edge_id = f"e_{new_edge.get('subject')}_{new_edge.get('predicate')}_{new_edge.get('object')}"

    edges = in_message["message"]["knowledge_graph"]["edges"]
    edges[new_edge_id] = new_edge
    return new_edge_id


def create_edgar_inferred_edge( new_node, qg_curie, qg_predicate, is_source=False ):
    # 1. Make the link into component parts
    if is_source:
        source = qg_curie
        target = new_node
    else:
        source = new_node
        target = qg_curie

    epred = orjson.loads(qg_predicate)

    predicate_only = epred.get("predicate")

    new_edge = create_knowledge_graph_edge(source, target, predicate_only)
    # Add any qualifiers
    qualifiers = []
    for key, value in epred.items():
        if key != "predicate":
            qualifiers.append({"qualifier_type_id": f"biolink:{key}", "qualifier_value": value})

    new_edge["qualifiers"] = qualifiers

    # 2. Add the edges between the curie node and lookup nodes to the knowledge graph
    edge_id = f"{source}_Inferred_to_{predicate_only}_{target}"

    return edge_id, new_edge


def add_auxgraph_for_inference( in_message, enriched_node, direct_inferred_edge_id, enriched_to_infer_edge_id,
                                enrichment_edges, uuid_to_curie_edge_id ):
    """
    Add an auxilary graph to the TRAPI response for edgar.
    In this case, we have a direct edge from an input_id to the inferred node.  That edge is in the KG, and its
    id is direct_inferred_edge.  The member_of_edges holds edge_ids of the edges connecting the set enriched node to the
    lookup id, indexed by the lookup id. The enriched_edges holds edge_ids of the edges connecting each enriched node to the
    inferred id, indexed by the enriched_node id. So we need to look at the direct direct_inferred_edge, figure out which one is the input,
    and then grab the edge id from the member_of_ids and the enrichment edge ids from the enriched_edges.
    Once we have these three ids, we can create the auxiliary graph which will consist of
    (input curie)-(lookup_node)-[member_of]-(set uuid)-[enriched_edge]-(enriched_node)-(inferred_node)

     (enriched_node)-(inferred_node): enriched_to_infer_edge
     (input curie)-(inferred_node): direct_inferred_edge
    """
    prefix = "n" if "ROLE" in enriched_node else "e"

    # get the direct edge1: [member_of]-(set uuid)-[enriched_edge]-(enriched_node)
    enriched_to_uuid_edge_id = enrichment_edges[enriched_node]

    # create the aux graph
    aux_graph = {
        "edges": [enriched_to_infer_edge_id, enriched_to_uuid_edge_id, uuid_to_curie_edge_id],
        "attributes": []
    }
    aux_graph_id = f"{prefix}_Inferred_SG:_{direct_inferred_edge_id}"
    if "auxiliary_graphs" not in in_message["message"]:
        in_message["message"]["auxiliary_graphs"] = {}
    in_message["message"]["auxiliary_graphs"][aux_graph_id] = aux_graph

    # to check
    # checkchek = in_message["message"]["knowledge_graph"]["edges"][direct_inferred_edge_id]
    add_aux_graphs(in_message["message"]["knowledge_graph"]["edges"][direct_inferred_edge_id], aux_graph_id)


def add_auxgraph_for_lookup( in_message, uuid_to_curie_edge_id, member_of_edges, lookup_member_edges ):
    """
    Add an auxilary graph to the TRAPI response for edgar.
    In this case, we have a direct edge from an input_curie to the uuid_node.  That edge is in the KG, and its
    id is uuid_to_curie_edge.  The member_of_edges holds edge_ids of the edges connecting the set uuidnode node to the
    lookup id, indexed by the lookup id. So we need to look at the uuid_to_curie_edge, create the auxiliary graph which will consist of
    (input curie)-(lookup_node)-[member_of]-(set uuid
    """

    edges = list(member_of_edges.values()) + list(lookup_member_edges.values())
    # create the aux graph
    aux_graph = {
        "edges": edges,
        "attributes": []
    }
    aux_graph_id = f"SG:_{uuid_to_curie_edge_id}"
    if "auxiliary_graphs" not in in_message["message"]:
        in_message["message"]["auxiliary_graphs"] = {}
    in_message["message"]["auxiliary_graphs"][aux_graph_id] = aux_graph

    add_aux_graphs(in_message["message"]["knowledge_graph"]["edges"][uuid_to_curie_edge_id], aux_graph_id)


def make_edgar_final_result( result_dictionary, inferred_node, edge_id, params: Lookup_params ):
    if inferred_node not in result_dictionary:
        result = {"node_bindings": {}, "analyses": [{"edge_bindings": {}, "resource_id": infores, "attributes": []}]}
        # There should be a node binding from the inferred node to the input qg curie
        result["node_bindings"][params.input_qnode] = [{"id": params.curie, "attributes": []}]
        # There should be a node binding from the qg qnode_id to the inferred node
        result["node_bindings"][params.output_qnode] = [{"id": inferred_node, "attributes": []}]
        # There should be an edge binding from the inferred edge qedge_id to the qg edge id
        result["analyses"][0]["edge_bindings"][params.qedge_id] = [{"id": edge_id, "attributes": []}]
        result_dictionary[inferred_node] = result


def fetch_inferred_edge_id( link_id, params ):
    # 1. We'd fetch the existing inferred edge
    pred = orjson.loads(params.predicate_parts)
    predicate_only = pred.get("predicate")
    if params.is_source:
        source = params.curie
        target = link_id
    else:
        source = link_id
        target = params.curie

    return f"{source}_Inferred_to_{predicate_only}_{target}"


def add_edgar_final_result( in_message, results ):
    if "results" not in in_message["message"]:
        in_message["message"]["results"] = []
    in_message["message"]["results"].extend(list(results.values()))


def add_node_property( node, property, in_message=None, p_value=None ):
    """

    """
    if isinstance(node, str) and in_message:
        node = in_message["message"]["knowledge_graph"]["nodes"][node]

    if "attributes" not in node:
        node["attributes"] = []

    if p_value:
        attribute = {
            "attribute_type_id": "biolink:has_chemical_role",
            "value": property,
            "attributes": [
                {"attribute_type_id": "biolink:scoring_method", "value": "property_enrichment"},
                {"attribute_type_id": "biolink:p-value", "value": p_value},
                {"attribute_type_id": "biolink:agent_type", "value": "computational_model", "attribute_source": infores},
                {"attribute_type_id": "biolink:knowledge_level", "value": "predication", "attribute_source": infores}
            ]
        }
    else:
        attribute = {
            "attribute_type_id": "biolink:has_chemical_role",
            "value": property,
            "attributes": [
                {"attribute_type_id": "biolink:knowledge_level", "value": "assertion", "attribute_source": infores}
            ]
        }

    node["attributes"].append(attribute)
