from src.components import  MCQDefinition, NewEdge
from typing import Dict
import uuid
import orjson
#This is the single place to create TRAPI elements.  It is the only place that should be creating TRAPI elements.

infores = "infores:answercoalesce"



def create_knowledge_graph_node(curie,categories,name=None):
    """
    Create a TRAPI knowledge graph node.
    """
    return {
        "categories": categories,
        "name": name,
        "attributes": []
    }

def create_knowledge_graph_edge_from_component(input_edge: NewEdge):
    # The NewEdge predicate has both the predicate and qualifiers in it:
    jsonpred = orjson.loads(input_edge.predicate)
    predicate_only = jsonpred["predicate"]
    qualifiers = []
    for key,value in jsonpred.items():
        if key != "predicate":
            qualifiers.append({"qualifier_type_id":key,"qualifier_value":value})
    return create_knowledge_graph_edge(input_edge.source, input_edge.target, predicate_only,
                                       qualifiers=qualifiers, sources=input_edge.prov)


def create_knowledge_graph_edge(subject, object, predicate, qualifiers=None, sources=[], attributes=[]):
    """
    Create a TRAPI knowledge graph edge.
    """
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

def add_node_to_knowledge_graph(response,node_id,node):
    """
    Add a TRAPI knowledge graph node to a TRAPI knowledge graph.
    """
    if "knowledge_graph" not in response["message"]:
        response["message"]["knowledge_graph"] = {"nodes": {}, "edges": {}}
    if "nodes" not in response["message"]["knowledge_graph"]:
        response["message"]["knowledge_graph"]["nodes"] = {}
    nodes = response["message"]["knowledge_graph"]["nodes"]
    if node_id not in nodes:
        nodes[node_id] = node

def add_edge_to_knowledge_graph(response, edge: Dict, edge_id=None):
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

def add_enrichment_edge_to_knowledge_graph(response,edge):
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
        for key,value in edge["predicate"].items():
            if key != "predicate":
                new_edge["qualifiers"].append({"qualifier_type_id":key,"qualifier_value":value})
    new_edge["sources"] = edge.prov
    new_edge_id = f"{edge.source}-{edge.predicate['predicate']}-{edge.target}"
    base = new_edge_id
    ned_count = 0
    while new_edge_id in edges:
        new_edge_id = f"{base}-{ned_count}"
        ned_count += 1
    edges[new_edge_id] = new_edge
    return new_edge_id

def add_auxgraph_for_enrichment(in_message, direct_edge_id, member_of_ids, new_curie):
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
    aux_graph_id = str(uuid.uuid4())
    if "auxiliary_graphs" not in in_message["message"]:
        in_message["message"]["auxiliary_graphs"] = {}
    in_message["message"]["auxiliary_graphs"][aux_graph_id] = aux_graph
    return aux_graph_id

def add_enrichment_edge(in_message, enrichment, mcq_definition: MCQDefinition, aux_graph_ids):
    """
    Add an enrichment edge to the TRAPI response.
    The enrichment edge is an inferred edge connecting the enriched node to the input node.
    It should match the predicate and query direction of the input query graph
    """
    edges = in_message["message"]["knowledge_graph"]["edges"]
    #Create the edge, orienting it correctly
    new_edge = {
        "predicate": mcq_definition.edge.predicate_only,
        "attributes": []
    }
    if mcq_definition.edge.group_is_subject:
        new_edge["subject"] = mcq_definition.group_node.uuid
        new_edge["object"] = enrichment.enriched_node.new_curie
    else:
        new_edge["object"] = mcq_definition.group_node.uuid
        new_edge["subject"] = enrichment.enriched_node.new_curie
    # Add any qualifiers
    new_edge["qualifiers"] = mcq_definition.edge.qualifiers
    # Add provenance
    add_local_prov(new_edge)
    # Add KL/AT
    add_prediction_klat(new_edge)
    # Add the auxiliary graphs
    add_aux_graphs(new_edge,aux_graph_ids)
    # Add the edge to the KG
    new_edge_id = str(uuid.uuid4())
    edges[new_edge_id] = new_edge
    return new_edge_id

def convert_qualifier_constraint_to_qualifiers(qualifier_constraints):
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

def add_local_prov(edge):
    """
    Add the provenance information to an enrichment edge.
    """
    new_provenance = {"resource_id": infores,
                      "resource_role": "primary_knowledge_source"}
    edge["sources"] = [new_provenance]

def add_klat(edge, kl, at):
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

def add_prediction_klat(edge):
    add_klat(edge, "prediction", "computational_model")

#TODO: what are the appropriate KL/AT if we are adding member_of edges?
def add_member_of_klat(edge):
    add_klat(edge, "???", "???")

def add_aux_graphs(new_edge,aux_graph_ids):
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

def add_enrichment_result(in_message, enriched_node, enrichment_edge_id, mcq_definition: MCQDefinition):
    if "results" not in in_message["message"]:
        in_message["message"]["results"] = []
    result = {"node_bindings": {}, "analyses": [{"edge_bindings": {}, "resource_id": infores, "attributes": []}]}
    in_message["message"]["results"].append(result)
    # There should be a node binding from the input (group) node qnode_id to the input node uuid
    result["node_bindings"][mcq_definition.group_node.qnode_id] = [{"id": mcq_definition.group_node.uuid, "attributes": []}]
    # There should be a node binding from the enriched node qnode_id to the enriched node curie
    result["node_bindings"][mcq_definition.enriched_node.qnode_id] = [{"id": enriched_node.new_curie, "attributes": []}]
    # There should be an edge binding from the enrichment edge qedge_id to the enrichment edge uuid
    result["analyses"][0]["edge_bindings"][mcq_definition.edge.qedge_id] = [{"id": enrichment_edge_id, "attributes": []}]
