from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum
import json
import orjson


###
# These classes are used to extract the meaning from the TRAPI MCQ query into a more usable form
###

# TODO: Handle the case where we are not gifted a category for the group node
class MCQGroupNode:
    def __init__(self, query_graph):
        for qnode_id, qnode in query_graph["nodes"].items():
            if (qnode.get("set_interpretation", "") == "MANY") and (len(qnode.get("member_ids", [])) > 1):
                self.curies = qnode["member_ids"]
                self.qnode_id = qnode_id
                self.uuid = qnode["ids"][0]
                self.semantic_type = qnode["categories"][0]


class MCQEnrichedNode:
    def __init__(self, query_graph):
        for qnode_id, qnode in query_graph["nodes"].items():
            if qnode.get("set_interpretation", "") != "MANY" or len(qnode.get("member_ids", [])) == 0:
                self.qnode_id = qnode_id
                self.semantic_types = qnode["categories"]


class MCQEdge:
    def __init__(self, query_graph, groupnode_qnodeid):
        for qedge_id, qedge in query_graph["edges"].items():
            if qedge["subject"] == groupnode_qnodeid:
                self.group_is_subject = True
            else:
                self.group_is_subject = False
            self.qedge_id = qedge_id
            self.predicate_only = qedge.get("predicates", ["biolink:related_to"])[0]
            self.predicate = {"predicate": self.predicate_only}
            self.qualifiers = []
            qualifier_constraints = qedge.get("qualifier_constraints", [])
            if len(qualifier_constraints) > 0:
                qc = qualifier_constraints[0]
                self.qualifiers = qc.get("qualifier_set", [])
                for q in self.qualifiers:
                    qt = q["qualifier_type_id"]
                    key = qt.split(":")[-1] if ":" in qt else qt
                    self.predicate[key] = q["qualifier_value"]


class MCQDefinition:
    def __init__(self, in_message):
        query_graph = in_message["message"]["query_graph"]
        self.group_node = MCQGroupNode(query_graph)
        self.enriched_node = MCQEnrichedNode(query_graph)
        self.edge = MCQEdge(query_graph, self.group_node.qnode_id)


###
# These components are about holding the results of Graph enrichment in a TRAPI independent way
###

class NewNode:
    def __init__(self, newnode, newnodetype: list[str]):  #edge_pred_and_qual, newnode_is):
        self.new_curie = newnode
        self.newnode_type = newnodetype
        self.newnode_name = None


class NewEdge:
    def __init__(self, source, predicate: str, target):
        self.source = source
        self.predicate = predicate
        self.target = target

    def get_prov_link(self):
        return f"{self.source} {self.predicate} {self.target}"

    def get_sym_prov_link(self):
        return f"{self.target} {self.predicate} {self.source}"

    def add_prov(self, prov):
        self.prov = prov


@dataclass
class QueryParams:
    """
    Parsed query parameters from TRAPI message.
    """
    curie: str
    predicate_parts: str  # JSON string with predicate + all qualifiers
    is_source: bool
    input_qnode: str
    output_qnode: str
    output_semantic_type: str
    input_semantic_type: str
    qedge_id: str

    @property
    def predicate_only(self) -> str:
        """Extract just the predicate from predicate_parts JSON"""
        return json.loads(self.predicate_parts).get("predicate")

    @property
    def predicate_dict(self) -> dict:
        """Get predicate_parts as dict"""
        return json.loads(self.predicate_parts)

    @classmethod
    def from_message(cls, in_message: dict) -> Optional['QueryParams']:
        """
        Parse TRAPI message into query parameters.

        Returns None if the message doesn't contain valid query parameters.
        """
        qg = in_message.get("message", {}).get("query_graph", {})
        edges = qg.get("edges", {})
        nodes = qg.get("nodes", {})

        if not edges:
            return None

        # Process first edge (single-curie infer queries have one edge)
        for qedge_id, qedge in edges.items():
            subject_node = nodes.get(qedge.get("subject"), {})
            object_node = nodes.get(qedge.get("object"), {})

            # Determine direction: which node has the input curie?
            subject_has_ids = bool(subject_node.get("ids"))
            object_has_ids = bool(object_node.get("ids"))

            if subject_has_ids:
                is_source = True
                curie = subject_node["ids"][0]
                input_qnode = qedge["subject"]
                output_qnode = qedge["object"]
                input_semantic_type = subject_node.get("categories", ["biolink:NamedThing"])[0]
                output_semantic_type = object_node.get("categories", ["biolink:NamedThing"])[0]
            elif object_has_ids:
                is_source = False
                curie = object_node["ids"][0]
                input_qnode = qedge["object"]
                output_qnode = qedge["subject"]
                input_semantic_type = object_node.get("categories", ["biolink:NamedThing"])[0]
                output_semantic_type = subject_node.get("categories", ["biolink:NamedThing"])[0]
            else:
                # Neither node has IDs - invalid for infer query
                return None

            if not curie:
                return None

            predicate_parts = cls._build_predicate_parts(qedge)

            return cls(
                curie=curie,
                predicate_parts=predicate_parts,
                is_source=is_source,
                input_qnode=input_qnode,
                output_qnode=output_qnode,
                output_semantic_type=output_semantic_type,
                input_semantic_type=input_semantic_type,
                qedge_id=qedge_id
            )

        return None

    @staticmethod
    def _build_predicate_parts(qedge: dict) -> str:
        """Build predicate JSON string with all qualifiers from the query edge."""
        parts = {"predicate": qedge.get("predicates", ["biolink:related_to"])[0]}

        for qc in qedge.get("qualifier_constraints", []):
            for q in qc.get("qualifier_set", []):
                qualifier_type = q.get("qualifier_type_id", "")
                key = qualifier_type.split(":")[-1] if ":" in qualifier_type else qualifier_type
                parts[key] = q.get("qualifier_value")

        return json.dumps(parts, sort_keys=True)


@dataclass
class LookupLink:
    """A single link from lookup results"""
    link_id: str
    link_name: Optional[str]
    link_type: list[str]
    link_edge: Optional[dict] = None  # Edge connecting to input curie


@dataclass
class LookupResult:
    """
    Result of initial lookup for a curie.

    Cleaner replacement for the Lookup class.
    """
    input_curie: str
    input_name: Optional[str]
    input_types: list[str]
    predicate: str
    is_source: bool
    link_ids: list[str]
    links: list[LookupLink]
    score: Optional[float] = None

    @classmethod
    def from_legacy_lookup(cls, lookup: Any) -> 'LookupResult':
        """Convert legacy Lookup object"""
        links = [
            LookupLink(
                link_id=ll.link_id,
                link_name=ll.link_name,
                link_type=ll.link_type,
                link_edge={
                    "source": ll.link_edge.source,
                    "predicate": ll.link_edge.predicate,
                    "target": ll.link_edge.target
                } if hasattr(ll, 'link_edge') and ll.link_edge else None
            )
            for ll in lookup.lookup_links
        ]

        return cls(
            input_curie=lookup.input_qnode_curie.new_curie,
            input_name=lookup.input_qnode_curie.name,
            input_types=lookup.input_qnode_curie.newnode_type or [],
            predicate=lookup.predicate,
            is_source=lookup.is_source,
            link_ids=lookup.link_ids,
            links=links,
            score=lookup.score
        )


class Lookup:
    def __init__(self, curie, predicate, is_source, node_names, node_types, lookup_ids, params_output_semantic_type,
                 score=None):
        self.predicate = predicate
        self.is_source = is_source
        self.score = score

        # lookup_ids may be plain IDs or full links [id, pred, is_source]
        if lookup_ids and isinstance(lookup_ids[0], (list, tuple)):
            self.link_ids = [link[0] for link in lookup_ids]
            self._link_predicates = {link[0]: link[1] for link in lookup_ids}
        else:
            self.link_ids = lookup_ids
            self._link_predicates = {}

        self.add_input_node(curie, node_types)
        self.add_input_node_name(node_names)
        self.add_links(node_names, node_types)
        self.add_linked_edges(curie, is_source)

    def add_input_node(self, curie, node_types):
        """Optionally, we can patch by adding a new node, which will share a relationship of
        some sort to the curies in self.set_curies.  The remaining parameters give the edge_type
        of those edges, as well as defining whether the edge points to the newnode (newnode_is = 'target')
        or away from it (newnode_is = 'source') """
        self.input_qnode_curie = NewNode(curie, node_types.get(curie, None))

    def add_input_node_name(self, node_names):
        self.input_qnode_curie.name = node_names.get(self.input_qnode_curie.new_curie, None)

    def add_links(self, nodenames, nodetypes):
        self.lookup_links = [LookupLinks(link_id, nodenames.get(link_id), nodetypes.get(link_id)) for link_id in
                             self.link_ids]

    def add_linked_edges(self, input_node, input_node_is_source):
        """Add edges between the newnode (curie) and the curies that they were linked to.
        Uses per-link predicate from Redis when available, falls back to self.predicate."""
        if input_node_is_source:
            for i, link_id in enumerate(self.link_ids):
                pred = self._link_predicates.get(link_id, self.predicate)
                self.lookup_links[i].link_edge = NewEdge(input_node, pred, link_id)
        else:
            for i, link_id in enumerate(self.link_ids):
                pred = self._link_predicates.get(link_id, self.predicate)
                self.lookup_links[i].link_edge = NewEdge(link_id, pred, input_node)

    def add_linked_kg_edges_id(self, eid):
        """Add edges between the newnode (curie) and the curies that they were linked to as written in the KG"""
        self.link_kg_edges_ids.append(eid)

    def get_prov_links(self):
        return [link.link_edge.get_prov_link() for link in self.lookup_links]

    def add_provenance(self, prov):
        for link in self.lookup_links:
            provlink = link.link_edge.get_prov_link()
            symprovlink = link.link_edge.get_sym_prov_link()
            if prov.get(provlink):
                link.link_edge.add_prov(prov[provlink])
            elif prov.get(symprovlink):
                link.link_edge.add_prov(prov[symprovlink])
            else:
                link.link_edge.add_prov([])

    def add_enrichment(self, lookup_indices, enriched_node, predicate, is_source, pvalue):
        for index in lookup_indices:
            if hasattr(self.lookup_links[index], 'enrichments'):
                self.lookup_links[index].enrichments.append(LinkEnrichment(enriched_node, predicate, is_source, pvalue))
            else:
                self.lookup_links[index].enrichments = [LinkEnrichment(enriched_node, predicate, is_source, pvalue)]


class LookupLinks:
    def __init__(self, link_id, link_name, link_type):
        self.link_id = link_id
        self.link_name = link_name
        self.link_type = link_type


class LinkEnrichment:
    def __init__(self, enriched_node, predicate, is_source, pvalue):
        self.enriched_node = enriched_node
        self.predicate = predicate
        self.is_source = is_source
        self.p_value = pvalue


class Enrichment:
    def __init__(self, p_value, newnode: str, predicate: str, is_source, ndraws, n, total_node_count, curies,
                 node_type: list[str]):
        """Here the curies are the curies that actually link to newnode, not just the input curies."""
        self.links = []
        self.p_value = p_value
        self.linked_curies = curies
        self.enriched_node = None
        self.predicate = predicate
        self.is_source = is_source
        self.provmap = {}
        self.add_extra_node(newnode, node_type)
        self.add_extra_edges(newnode, predicate, is_source)
        self.counts = [ndraws, n, total_node_count]

    def add_extra_node(self, newnode, newnodetype: list[str]):
        """Optionally, we can patch by adding a new node, which will share a relationship of
        some sort to the curies in self.set_curies.  The remaining parameters give the edge_type
        of those edges, as well as defining whether the edge points to the newnode (newnode_is = 'target')
        or away from it (newnode_is = 'source') """
        self.enriched_node = NewNode(newnode, newnodetype)

    def add_extra_node_name_and_label(self, name_dict, label_dict):
        self.enriched_node.newnode_name = name_dict.get(self.enriched_node.new_curie, None)
        self.enriched_node.newnode_type = label_dict.get(self.enriched_node.new_curie, [])

    def add_extra_edges(self, newnode, predicate: str, newnode_is_source):
        """Add edges between the newnode (curie) and the curies that they were linked to"""
        if newnode_is_source:
            self.links = [NewEdge(newnode, predicate, curie) for curie in self.linked_curies]
        else:
            self.links = [NewEdge(curie, predicate, newnode) for curie in self.linked_curies]

    def get_prov_links(self):
        return [link.get_prov_link() for link in self.links]

    def add_provenance(self, prov):
        for link in self.links:
            provlink = link.get_prov_link()
            symprovlink = link.get_sym_prov_link()
            if prov.get(provlink):
                link.add_prov(prov[provlink])
            elif prov.get(symprovlink):
                link.add_prov(prov[symprovlink])
            else:
                link.add_prov([])


class EnrichmentType(Enum):
    """Type of enrichment source"""
    GRAPH = "graph"
    PROPERTY = "property"


@dataclass(frozen=True)
class EnrichmentResult:
    """
    Unified enrichment result for both graph and property enrichment.

    Frozen (immutable) so it can be used as dict key and cached safely.
    """
    enrichment_type: EnrichmentType
    enriched_id: str
    enriched_name: Optional[str]
    enriched_types: tuple[str, ...]  # immutable tuple instead of list
    predicate: str  # JSON string for graph, simple string for property
    p_value: float
    linked_curies: frozenset[str]
    counts: tuple[int, ...]  # (ndraws, n, total_node_count)
    is_source: bool
    # For graph enrichment - the NewEdge objects connecting to linked curies
    # Stored as tuple of dicts for immutability
    support_edges: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        """Unique identifier for this enrichment result"""
        return f"{self.enriched_id}|{self.predicate}|{self.p_value}"

    @property
    def predicate_only(self) -> str:
        """Extract just the predicate from predicate JSON"""
        try:
            return orjson.loads(self.predicate).get("predicate", self.predicate)
        except (orjson.JSONDecodeError, TypeError):
            return self.predicate

    @classmethod
    def from_graph_enrichment(cls, enrichment: Enrichment) -> 'EnrichmentResult':
        """
        Convert legacy Enrichment object to unified format.

        Args:
            enrichment: Legacy Enrichment object from component.py
        """
        # Convert NewEdge objects to dicts for immutability
        # Keep full JSON predicate so qualifiers (e.g. species_context_qualifier) are preserved
        support_edges = []
        for edge in (enrichment.links or []):
            support_edges.append({
                "source": edge.source,
                "predicate": edge.predicate,
                "target": edge.target,
                "prov": getattr(edge, 'prov', None)
            })

        return cls(
            enrichment_type=EnrichmentType.GRAPH,
            enriched_id=enrichment.enriched_node.new_curie,
            enriched_name=enrichment.enriched_node.newnode_name,
            enriched_types=tuple(enrichment.enriched_node.newnode_type or []),
            predicate=enrichment.predicate or '{}',
            p_value=enrichment.p_value,
            linked_curies=frozenset(enrichment.linked_curies),
            counts=tuple(enrichment.counts),
            is_source=enrichment.is_source,
            support_edges=tuple(support_edges),
        )

    @classmethod
    def from_property_enrichment(cls, prop_dict: dict) -> 'EnrichmentResult':
        """
        Convert property enrichment dict to unified format.

        Args:
            prop_dict: Dict with keys: enriched_property, p_value, linked_curies,
                      semantic_type, counts
        """
        return cls(
            enrichment_type=EnrichmentType.PROPERTY,
            enriched_id=prop_dict["enriched_property"],
            enriched_name=prop_dict["enriched_property"],  # property name is its own name
            enriched_types=("biolink:ChemicalRole",),
            predicate="biolink:has_chemical_role",
            p_value=prop_dict["p_value"],
            linked_curies=frozenset(prop_dict["linked_curies"]),
            counts=tuple(prop_dict["counts"]),
            is_source=False,
            support_edges=()  # Property enrichment doesn't have support edges
        )


@dataclass
class InferenceParams:
    """
    Runtime parameters for inference with sensible defaults.
    """
    predicate_constraints: list[str] | None = field(default_factory=list)
    property_constraints: list[str] | None = field(default_factory=list)
    node_constraints: list[str] | None = field(default_factory=list)
    predicate_constraint_style: str = "exclude"
    pvalue_threshold: float | None = 1e-5
    max_rules: int | None = 100
    max_results: int | None = 2000

    @classmethod
    def from_message(cls, in_message: dict) -> 'InferenceParams':
        """Extract inference parameters from TRAPI message"""
        params = in_message.get('parameters', {})
        return cls(
            predicate_constraints=params.get('predicate_constraints', None),
            predicate_constraint_style=params.get('predicate_constraint_style', 'exclude'),
            property_constraints=params.get('properties_constraints', None),
            node_constraints=params.get('node_constraints', None),
            pvalue_threshold=params.get('pvalue_threshold', 1e-5),
            max_rules=params.get('max_rules', None),
            max_results=params.get('max_results', None)
        )