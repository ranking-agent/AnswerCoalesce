import uuid
#This is the single place to create TRAPI elements.  It is the only place that should be creating TRAPI elements.

infores = "infores:answercoalesce"

async def get_mcq_components(in_message):
    """Parse the input message and extract the defining information of the query in a TRPAPI independent way.
    In MCQ there are two query nodes, one is the group node, with the input curies and the other is the enriched node,
    which is the output. There is also a single edge connecting the group node to the enriched node.
    This is the structure:
    MCQ = {"group_node": {"curies": [],
                          "qnode_id": None,
                          "uuid": None},
           "enriched_node": {"qnode_id": None,
                             "semantic_type": None},
           "edge": {"predicate": None,
                    "qedge_id": None,
                    "group_is_subject": None}}
    The qnode_ids and qedge_id are the keys in the "nodes" and "edges" dictionaries in the query_graph.
    Predicate is a dictionary containing the predicate and any qualifiers.
    """
    MCQ = {"group_node": {"curies": [], "qnode_id": None, "uuid": None},
           "enriched_node": {"qnode_id": None, "semantic_type": None},
           "edge": {"predicate": None, "qedge_id": None, "group_is_subject": None}}
    query_graph = in_message["message"]["query_graph"]
    for qnode_id, qnode in query_graph["nodes"].items():
        if qnode.get("set_interpretation","") == "MANY":
            MCQ["group_node"]["curies"] = qnode["member_ids"]
            MCQ["group_node"]["qnode_id"] = qnode_id
            MCQ["group_node"]["uuid"] = qnode["ids"][0]
        else:
            MCQ["enriched_node"]["qnode_id"] = qnode_id
            MCQ["enriched_node"]["semantic_types"] = qnode["categories"]
    for qedge_id, qedge in query_graph["edges"].items():
        if qedge["subject"] == MCQ["group_node"]["qnode_id"]:
            MCQ["edge"]["group_is_subject"] = True
        else:
            MCQ["edge"]["group_is_subject"] = False
        MCQ["edge"]["qedge_id"] = qedge_id
        MCQ["edge"]["predicate"] = qedge["predicate"]
        qualifier_constraints = qedge.get("qualifiers_constraints",[])
        if len(qualifier_constraints) > 0:
            qc = qualifier_constraints[0]
            qs = qc.get("qualifier_set",[])
            for q in qs:
                MCQ["edge"]["predicate"][q["qualifier_type_id"]] = q["qualifier_value"]
    return MCQ

def create_knowledge_graph_node(curie,category,name):
    """
    Create a TRAPI knowledge graph node.
    """
    return {
        "category": [category],
        "id": curie,
        "name": name,
        "attributes": []
    }

def add_node_to_knowledge_graph(response,node):
    """
    Add a TRAPI knowledge graph node to a TRAPI knowledge graph.
    """
    nodes = response["message"]["knowledge_graph"]["nodes"]
    if node.new_curie not in nodes:
        nodes[node.new_curie] = create_knowledge_graph_node(node.new_curie,node.category,node.name)

def add_edge_to_knowledge_graph(response,edge):
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
    in_message["message"]["auxiliary_graphs"][aux_graph_id] = aux_graph
    return aux_graph_id

def add_enrichment_edge(in_message, enrichment, aux_graph_ids, input_qnode_id):
    """
    Add an enrichment edge to the TRAPI response.
    The enrichment edge is an inferred edge connecting the enriched node to the input node.
    It should match the predicate and query direction of the input query graph
    """
    edges = in_message["message"]["knowledge_graph"]["edges"]
    query_graph = in_message["message"]["query_graph"]
    for qid, qnode in query_graph["nodes"].items():
        if qnode.get("ids",["no"])[0] == input_qnode_id:
            input_qid = qid
        else:
            enriched_qid = qid
    qg_edges = query_graph["edges"]
    # is the predicate pointing to or from the group(input) node?
    for qge_id, edge in qg_edges.items():
        if edge["subject"] == input_qid:
            group_is_subject = True
        else:
            group_is_subject = False
        predicate = edge["predicate"]
        qualifier_constraints = edge.get("qualifiers_constraints",[])
    #Create the edge, orienting it correctly
    new_edge = {
        "predicate": predicate,
        "attributes": []
    }
    if group_is_subject:
        new_edge["subject"] = input_qnode_id
        new_edge["object"] = enrichment.enriched_node.new_curie
    else:
        new_edge["object"] = input_qnode_id
        new_edge["subject"] = enrichment.enriched_node.new_curie
    # Add any qualifiers
    qualifiers = convert_qualifier_constraint_to_qualifiers(qualifier_constraints)
    new_edge["qualifiers"] = qualifiers
    # Add provenance
    add_enrichment_prov(new_edge,enrichment)
    # Add KL/AT
    add_prediction_klat(new_edge)
    # Add the auxiliary graphs
    add_aux_graphs(new_edge,aux_graph_ids)
    # Add the edge to the KG
    new_edge_id = str(uuid.uuid4())
    edges[new_edge_id] = new_edge

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

def add_enrichment_prov(new_edge,enrichment):
    """
    Add the provenance information to an enrichment edge.
    """
    new_provenance = {"resource_id": infores,
                      "resource_role": "primary_knowledge_source"}
    new_edge["sources"] = [new_provenance]

def add_prediction_klat(new_edge):
    """
    Add the knowledge level and attribute type to an edge.
    """
    source = {"name": infores}
    attributes = new_edge["attributes"]
    attributes += [
        {
            "attribute_type_id": "biolink:agent_type",
            "value": "computational_model",
            "attribute_source": source
        },
        {
            "attribute_type_id": "biolink:knowledge_level",
            "value": "prediction",
            "attribute_source": source
        }
    ]

def add_aux_graphs(new_edge,aux_graph_ids):
    """
    Add the auxiliary graphs to an edge.
    """
    new_edge["attributes"].append(
        {
            "attribute_type_id": "biolink:support_graphs",
            "value": aux_graph_ids
        }
    )

def add_enrichment_result(in_message, enriched_node, enrichment_edge_id):
    if "results" not in in_message["message"]:
        in_message["message"]["results"] = []
    result = {"node_bindings": {}, "analyses": [{"edge_bindings": {}, "attributes": []}]}
    in_message["message"]["results"].append(result)