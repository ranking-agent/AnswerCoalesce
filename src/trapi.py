from src.components import MCQDefinition, NewEdge
from typing import Dict
import uuid
import orjson
import logging
from typing import Optional, Any

# This is the single place to create TRAPI elements.  It is the only place that should be creating TRAPI elements.
logger = logging.getLogger(__name__)
infores = "infores:answercoalesce"


def create_knowledge_graph_node(curie, categories, name=None):
    """
    Create a TRAPI knowledge graph node.
    """
    categories = categories if isinstance(categories, list) else [categories]
    return {
        "categories": categories,
        "name": name,
        "attributes": []
    }


def create_knowledge_graph_edge_from_component(input_edge: NewEdge):
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


def create_knowledge_graph_edge(subject, object, predicate, qualifiers=None, sources=None, attributes=None):
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


def add_node_to_knowledge_graph(response, node_id, node):
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


def add_enrichment_edge_to_knowledge_graph(response, edge):
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
    aux_graph_id = f"SG:_{direct_edge_id}"
    if "auxiliary_graphs" not in in_message["message"]:
        in_message["message"]["auxiliary_graphs"] = {}
    in_message["message"]["auxiliary_graphs"][aux_graph_id] = aux_graph
    return aux_graph_id


def add_enrichment_edge(in_message, enrichment, mcq_definition: MCQDefinition, aux_graph_ids):
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


def add_aux_graphs(new_edge, aux_graph_ids):
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


def add_enrichment_result(in_message, enriched_node, enrichment_score, enrichment_edge_id,
                          mcq_definition: MCQDefinition):
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
    result["analyses"][0]["score"] = enrichment_score


class EGARTRAPIBuilder:
    """
    Builder for TRAPI message responses.

    Encapsulates all modifications to the knowledge graph, auxiliary graphs,
    and results. Provides idempotent operations that won't create duplicates.

    Usage:
        builder = TRAPIBuilder(in_message)
        builder.add_node("MONDO:0005148", ["biolink:Disease"], "Type 2 diabetes")
        builder.add_edge("DRUG:123", "biolink:treats", "MONDO:0005148")
        # Message is modified in place
    """

    def __init__(self, message: dict):
        """
        Initialize builder with a TRAPI message.

        Args:
            message: The full TRAPI message dict (modified in place)
        """
        self._message = message
        self._ensure_structure()

    def _ensure_structure(self):
        """Ensure all required message components exist"""
        # logs go at root level, not inside message
        self._message.setdefault("logs", [])

        msg = self._message.setdefault("message", {})
        msg.setdefault("query_graph", {"nodes": {}, "edges": {}})
        kg = msg.setdefault("knowledge_graph", {})
        kg.setdefault("nodes", {})
        kg.setdefault("edges", {})
        msg.setdefault("auxiliary_graphs", {})
        msg.setdefault("results", [])

    @property
    def message(self) -> dict:
        """Get the underlying message dict"""
        return self._message

    @property
    def kg_nodes(self) -> dict:
        """Direct access to knowledge graph nodes"""
        return self._message["message"]["knowledge_graph"]["nodes"]

    @property
    def kg_edges(self) -> dict:
        """Direct access to knowledge graph edges"""
        return self._message["message"]["knowledge_graph"]["edges"]

    @property
    def aux_graphs(self) -> dict:
        """Direct access to auxiliary graphs"""
        return self._message["message"]["auxiliary_graphs"]

    @property
    def results(self) -> list:
        """Direct access to results list"""
        return self._message["message"]["results"]

    @property
    def logs(self) -> list:
        """Direct access to logs list (at root level, not inside message)"""
        return self._message.setdefault("logs", [])

    # ==================== Node Operations ====================

    def add_node(
            self,
            curie: str,
            categories: list[str],
            name: Optional[str] = None,
            attributes: Optional[list[dict]] = None,
            is_set: bool = False,
            **extra
    ) -> str:
        """
        Add a node to the knowledge graph. Idempotent.

        Args:
            curie: Node identifier
            categories: Biolink categories (e.g., ["biolink:Gene"])
            name: Human-readable name
            attributes: List of attribute dicts
            is_set: Whether this is a set/group node
            **extra: Additional node properties

        Returns:
            The curie (for chaining)
        """
        if curie in self.kg_nodes:
            return curie

        node = {
            "categories": categories,
            "attributes": attributes or []
        }

        if name:
            node["name"] = name

        if is_set:
            node["is_set"] = True

        node.update(extra)
        self.kg_nodes[curie] = node

        return curie

    def add_node_attribute(
            self,
            curie: str,
            attribute_type_id: str,
            value: Any,
            **extra
    ):
        """Add an attribute to an existing node"""
        if curie not in self.kg_nodes:
            logger.warning(f"Cannot add attribute to non-existent node: {curie}")
            return

        attr = {
            "attribute_type_id": attribute_type_id,
            "value": value,
            **extra
        }
        self.kg_nodes[curie].setdefault("attributes", []).append(attr)

    def add_member_ids(self, set_curie: str, member_ids: list[str]):
        """Add member_ids attribute to a set node"""
        self.add_node_attribute(
            set_curie,
            "biolink:member_ids",
            {"sources": member_ids}
        )

    def get_node(self, curie: str) -> Optional[dict]:
        """Get a node by curie, or None if not found"""
        return self.kg_nodes.get(curie)

    def remove_node(self, curie: str) -> Optional[dict]:
        """Remove and return a node"""
        return self.kg_nodes.pop(curie, None)

    # ==================== Edge Operations ====================

    def add_edge(
            self,
            subject: str,
            predicate: str,
            obj: str,
            edge_id: Optional[str] = None,
            attributes: Optional[list[dict]] = None,
            sources: Optional[list[dict]] = None,
            qualifiers: Optional[list[dict]] = None,
            **extra
    ) -> str:
        """
        Add an edge to the knowledge graph. Idempotent.

        Args:
            subject: Subject node curie
            predicate: Biolink predicate (can be JSON string with qualifiers or plain predicate)
            obj: Object node curie
            edge_id: Custom edge ID (auto-generated if not provided)
            attributes: List of attribute dicts
            sources: List of source/provenance dicts (default provenance added if None)
            qualifiers: List of qualifier dicts (if predicate is JSON, qualifiers are extracted from it)
            **extra: Additional edge properties

        Returns:
            The edge_id
        """
        # Parse predicate - it might be JSON with qualifiers
        predicate_only, parsed_qualifiers = self._parse_predicate(predicate)

        # Use provided qualifiers or parsed ones
        final_qualifiers = qualifiers if qualifiers is not None else parsed_qualifiers

        # Generate edge_id that includes qualifier info for uniqueness
        if edge_id is None:
            edge_id = self._make_edge_id(subject, predicate_only, obj, final_qualifiers)

        if edge_id in self.kg_edges:
            return edge_id

        # Always include sources - use default provenance if none provided
        if sources is None or len(sources) == 0:
            sources = self._default_sources()

        edge = {
            "subject": subject,
            "predicate": predicate_only,
            "object": obj,
            "attributes": attributes or [],
            "sources": sources
        }

        if final_qualifiers:
            edge["qualifiers"] = final_qualifiers

        edge.update(extra)
        self.kg_edges[edge_id] = edge

        return edge_id

    def _parse_predicate(self, predicate: str) -> tuple[str, list[dict]]:
        """
        Parse predicate which may be JSON with qualifiers.

        Returns:
            (predicate_only, qualifiers_list)
        """
        if not predicate:
            return "biolink:related_to", []

        # Try to parse as JSON
        if isinstance(predicate, str) and predicate.startswith('{'):
            try:
                pred_dict = orjson.loads(predicate)
                predicate_only = pred_dict.get("predicate", "biolink:related_to")

                # Extract qualifiers from the dict
                qualifiers = []
                for key, value in pred_dict.items():
                    if key != "predicate":
                        # Add biolink: prefix if not present
                        qualifier_type = f"biolink:{key}" if not key.startswith("biolink:") else key
                        qualifiers.append({
                            "qualifier_type_id": qualifier_type,
                            "qualifier_value": value
                        })

                return predicate_only, qualifiers
            except (orjson.JSONDecodeError, TypeError, AttributeError):
                pass

        # Plain predicate string
        return predicate, []

    def _make_edge_id(
            self,
            subject: str,
            predicate: str,
            obj: str,
            qualifiers: Optional[list[dict]] = None
    ) -> str:
        """
        Generate a unique edge ID that includes qualifier info.

        This ensures edges with different qualifiers get different IDs:
        - biolink:affects + increased != biolink:affects + decreased
        """
        base_id = f"{subject}_{predicate}_{obj}"

        if not qualifiers:
            return base_id

        # Sort qualifiers for consistent ID generation
        qualifier_parts = []
        for q in sorted(qualifiers, key=lambda x: x.get("qualifier_type_id", "")):
            qtype = q.get("qualifier_type_id", "").replace("biolink:", "")
            qval = q.get("qualifier_value", "")
            qualifier_parts.append(f"{qtype}={qval}")

        if qualifier_parts:
            return f"{base_id}_{'_'.join(qualifier_parts)}"

        return base_id

    def _default_sources(self) -> list[dict]:
        """Return default provenance/sources for edges created by AnswerCoalesce"""
        return [
            {
                "resource_id": "infores:answercoalesce",
                "resource_role": "primary_knowledge_source"
            }
        ]

    def add_edge_from_dict(self, edge_dict: dict, edge_id: Optional[str] = None) -> str:
        """Add an edge from a dict representation"""
        return self.add_edge(
            subject=edge_dict["subject"],
            predicate=edge_dict["predicate"],
            obj=edge_dict.get("object") or edge_dict.get("target"),
            edge_id=edge_id,
            attributes=edge_dict.get("attributes"),
            sources=edge_dict.get("sources")
        )

    def add_edge_attribute(
            self,
            edge_id: str,
            attribute_type_id: str,
            value: Any,
            **extra
    ):
        """Add an attribute to an existing edge"""
        if edge_id not in self.kg_edges:
            logger.warning(f"Cannot add attribute to non-existent edge: {edge_id}")
            return

        attr = {
            "attribute_type_id": attribute_type_id,
            "value": value,
            **extra
        }
        self.kg_edges[edge_id].setdefault("attributes", []).append(attr)

    def get_edge(self, edge_id: str) -> Optional[dict]:
        """Get an edge by ID, or None if not found"""
        return self.kg_edges.get(edge_id)

    def remove_edge(self, edge_id: str) -> Optional[dict]:
        """Remove and return an edge"""
        return self.kg_edges.pop(edge_id, None)

    # ==================== Auxiliary Graph Operations ====================

    def add_auxiliary_graph(self, graph_id: str, edge_ids: list[str]) -> str:
        """
        Add an auxiliary graph.

        Args:
            graph_id: Unique identifier for the aux graph
            edge_ids: List of edge IDs in this graph

        Returns:
            The graph_id
        """
        self.aux_graphs[graph_id] = {
            "edges": edge_ids,
            "attributes": []  # Required by TRAPI spec
        }
        return graph_id

    def add_support_graph_to_edge(self, edge_id: str, aux_graph_id: str, as_array: bool = False):
        """
        Attach a support graph to an edge.

        Adds or appends to the biolink:support_graphs attribute.
        """
        edge = self.kg_edges.get(edge_id)
        if not edge:
            logger.warning(f"Cannot add support graph to non-existent edge: {edge_id}")
            return

        if as_array:
            # Lookup edge format: ONE attribute with ARRAY value
            for attr in edge.get("attributes", []):
                if attr.get("attribute_type_id") == "biolink:support_graphs":
                    if aux_graph_id not in attr["value"]:
                        attr["value"].append(aux_graph_id)
                    return

            # No existing support_graphs attribute, create one
            edge.setdefault("attributes", []).append({
                "attribute_type_id": "biolink:support_graphs",
                "value": [aux_graph_id]
            })
        else:
            edge.setdefault("attributes", []).append({
                "attribute_type_id": "biolink:support_graphs",
                "value": aux_graph_id,
                "attribute_source": "infores:answercoalesce"
            })

    def remove_auxiliary_graph(self, graph_id: str) -> Optional[dict]:
        """Remove and return an auxiliary graph"""
        return self.aux_graphs.pop(graph_id, None)

    def remove_edge_with_support_graphs(self, edge_id: str):
        """
        Remove an edge and cascade delete its support graphs and their edges.

        This cleans up:
        1. The edge itself
        2. All auxiliary graphs referenced by the edge
        3. All edges within those auxiliary graphs (if they start with prefixes)
        """
        edge = self.kg_edges.get(edge_id)
        if not edge:
            return

        # Find and remove support graphs
        for attr in edge.get("attributes", []):
            if attr.get("attribute_type_id") == "biolink:support_graphs":
                for sg_id in attr.get("value", []):
                    sg = self.aux_graphs.pop(sg_id, None)
                    if sg:
                        # Remove edges that were created for this aux graph
                        for aux_edge_id in sg.get("edges", []):
                            # Only remove generated edges (prefixed), not original edges
                            if aux_edge_id.startswith(('e_', 'n_', 'aux_', 'enrich_')):
                                self.kg_edges.pop(aux_edge_id, None)

        # Remove the main edge
        self.kg_edges.pop(edge_id, None)

    # ==================== Result Operations ====================

    def add_result(
            self,
            node_bindings: dict[str, list[dict]],
            analyses: list[dict]
    ):
        """
        Add a result to the message.

        Args:
            node_bindings: Map of qnode_id -> list of {"id": curie} bindings
            analyses: List of analysis dicts with edge_bindings
        """
        self.results.append({
            "node_bindings": node_bindings,
            "analyses": analyses
        })

    def create_node_binding(self, qnode_id: str, curie: str) -> dict:
        """Helper to create a node binding entry"""
        return {qnode_id: [{"id": curie}]}

    def create_edge_binding(self, qedge_id: str, edge_id: str) -> dict:
        """Helper to create an edge binding entry"""
        return {qedge_id: [{"id": edge_id}]}

    # ==================== Logging ====================

    def log(self, message: str, level: str = "INFO", **extra):
        """Add a log entry to the message"""
        log_entry = {
            "level": level,
            "message": message,
            **extra
        }
        self.logs.append(log_entry)

    def log_error(self, message: str, **extra):
        """Add an error log entry"""
        self.log(message, level="ERROR", **extra)
        logger.error(message)

    # ==================== Utilities ====================

    def node_exists(self, curie: str) -> bool:
        """Check if a node exists"""
        return curie in self.kg_nodes

    def edge_exists(self, edge_id: str) -> bool:
        """Check if an edge exists"""
        return edge_id in self.kg_edges

    def get_result_count(self) -> int:
        """Get number of results"""
        return len(self.results)

    def clear_results(self):
        """Clear all results (useful for rebuilding)"""
        self.results.clear()


def prune_message(builder: EGARTRAPIBuilder, kept_results: list):
    """
    Remove nodes, edges, and auxiliary graphs not referenced by kept results.
    Handles EDGAR's support_graphs format: multiple separate attributes with string values.
    """
    from collections import deque

    referenced_nodes = set()
    referenced_edges = set()
    referenced_aux_graphs = set()

    # Collect edges from results
    for result in kept_results:
        # Collect nodes from node_bindings
        for qnode_id, bindings in result.get("node_bindings", {}).items():
            for binding in bindings:
                referenced_nodes.add(binding["id"])

        # Collect edges from analyses
        for analysis in result.get("analyses", []):
            for qedge_id, bindings in analysis.get("edge_bindings", {}).items():
                for binding in bindings:
                    edge_id = binding["id"]
                    referenced_edges.add(edge_id)

                    # Get support_graphs from inference edge attribute
                    edge = builder.kg_edges.get(edge_id)
                    if edge:
                        for attr in edge.get("attributes", []):
                            if attr.get("attribute_type_id") == "biolink:support_graphs":
                                aux_graph_id = attr.get("value")
                                if aux_graph_id:
                                    referenced_aux_graphs.add(aux_graph_id)

    # BFS through nested auxiliary graphs
    aux_queue = deque(referenced_aux_graphs)
    processed_aux = set()

    while aux_queue:
        aux_graph_id = aux_queue.popleft()

        if aux_graph_id in processed_aux:
            continue

        processed_aux.add(aux_graph_id)
        aux_graph = builder.aux_graphs.get(aux_graph_id)

        if not aux_graph:
            continue

        # Process edges in this auxiliary graph
        for edge_id in aux_graph.get("edges", []):
            referenced_edges.add(edge_id)

            edge = builder.kg_edges.get(edge_id)
            if edge:
                # Collect nodes from edge
                referenced_nodes.add(edge["subject"])
                referenced_nodes.add(edge["object"])

                # Look for nested support graphs ie (lookupSet-enrichment) supports
                for attr in edge.get("attributes", []):
                    if attr.get("attribute_type_id") == "biolink:support_graphs":
                        nested_aux_ids = attr.get("value")
                        for nested_aux_id in nested_aux_ids:
                            if nested_aux_id and nested_aux_id not in processed_aux:
                                aux_queue.append(nested_aux_id)
                                referenced_aux_graphs.add(nested_aux_id)

    # Prune unreferenced elements
    all_nodes = set(builder.kg_nodes.keys())
    nodes_to_remove = all_nodes - referenced_nodes
    for node_id in nodes_to_remove:
        del builder.kg_nodes[node_id]

    all_edges = set(builder.kg_edges.keys())
    edges_to_remove = all_edges - referenced_edges
    for edge_id in edges_to_remove:
        del builder.kg_edges[edge_id]

    all_aux_graphs = set(builder.aux_graphs.keys())
    aux_to_remove = all_aux_graphs - referenced_aux_graphs
    for aux_id in aux_to_remove:
        del builder.aux_graphs[aux_id]

    logger.info(
        f"Pruned KG for {len(kept_results)} results: "
        f"removed {len(nodes_to_remove)} nodes, {len(edges_to_remove)} edges, "
        f"{len(aux_to_remove)} aux graphs"
    )


def make_edge_id(subject: str, predicate: str, obj: str) -> str:
    """Generate a standard edge ID"""
    return f"{subject}_{predicate}_{obj}"


def make_enrichment_key(enriched_id: str, predicate: str, p_value: float) -> str:
    """Generate a unique key for an enrichment result"""
    return f"{enriched_id}|{predicate}|{p_value}"