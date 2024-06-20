from copy import deepcopy
from collections import defaultdict
import ast, json, uuid
from string import Template


###
# These classes are used to extract the meaning from the TRAPI MCQ query into a more usable form
###

# TODO: Handle the case where we are not gifted a category for the group node
class MCQGroupNode:
    def __init__( self, query_graph ):
        for qnode_id, qnode in query_graph["nodes"].items():
            if qnode.get("set_interpretation", "") == "MANY":
                self.curies = qnode["member_ids"]
                self.qnode_id = qnode_id
                self.uuid = qnode["ids"][0]
                self.semantic_type = qnode["categories"][0]


class MCQEnrichedNode:
    def __init__( self, query_graph ):
        for qnode_id, qnode in query_graph["nodes"].items():
            if qnode.get("set_interpretation", "") != "MANY":
                self.qnode_id = qnode_id
                self.semantic_types = qnode["categories"]


class MCQEdge:
    def __init__( self, query_graph, groupnode_qnodeid ):
        for qedge_id, qedge in query_graph["edges"].items():
            if qedge["subject"] == groupnode_qnodeid:
                self.group_is_subject = True
            else:
                self.group_is_subject = False
            self.qedge_id = qedge_id
            self.predicate_only = qedge.get("predicates", ["biolink:related_to"])[0]
            self.predicate = {"predicate": self.predicate_only}
            self.qualifiers = []
            qualifier_constraints = qedge.get("qualifiers_constraints", [])
            if len(qualifier_constraints) > 0:
                qc = qualifier_constraints[0]
                self.qualifiers = qc.get("qualifier_set", [])
                for q in self.qualifiers:
                    self.predicate[q["qualifier_type_id"]] = q["qualifier_value"]


class MCQDefinition:
    def __init__( self, in_message ):
        query_graph = in_message["message"]["query_graph"]
        self.group_node = MCQGroupNode(query_graph)
        self.enriched_node = MCQEnrichedNode(query_graph)
        self.edge = MCQEdge(query_graph, self.group_node.qnode_id)


###
# These components are about holding the results of Graph enrichment in a TRAPI independent way
###

class NewNode:
    def __init__( self, newnode, newnodetype: list[str] ):  #edge_pred_and_qual, newnode_is):
        self.new_curie = newnode
        self.newnode_type = newnodetype
        self.newnode_name = None


class NewEdge:
    def __init__( self, source, predicate: str, target ):
        self.source = source
        self.predicate = predicate
        self.target = target

    def get_prov_link( self ):
        return f"{self.source} {self.predicate} {self.target}"

    def get_sym_prov_link( self ):
        return f"{self.target} {self.predicate} {self.source}"

    def add_prov( self, prov ):
        self.prov = prov


class Lookup_params:
    def __init__( self, in_message ):
        for qedge_id, qedges in in_message.get("message", {}).get("query_graph", {}).get("edges", {}).items():
            subject = in_message.get("message", {}).get("query_graph", {}).get("nodes", {})[qedges["subject"]]
            object = in_message.get("message", {}).get("query_graph", {}).get("nodes", {})[qedges["object"]]
            if subject.get("ids", []):
                is_source = True
            else:
                is_source = False
            if is_source:
                curies = subject["ids"][0]
                input_qnode = qedges["subject"]
                output_qnode = qedges["object"]
                semantic_type = object.get("categories", [])[0]
            else:
                curie = object["ids"][0]
                input_qnode = qedges["object"]
                output_qnode = qedges["subject"]
                semantic_type = subject.get("categories", [])[0]
            predicate_parts = {"predicate": qedges["predicates"][0]}
            qualifier_constraints = qedges.get("qualifier_constraints", [])
            if len(qualifier_constraints) > 0:
                qc = qualifier_constraints[0]
                qs = qc.get("qualifier_set", [])
                for q in qs:
                    predicate_parts[q["qualifier_type_id"].split(":")[1]] = q["qualifier_value"]
            predicate_parts = json.dumps(predicate_parts, sort_keys=True)
        self.is_source = is_source
        self.curie = curie
        self.predicate_parts = predicate_parts
        self.input_qnode = input_qnode
        self.output_qnode = output_qnode
        self.output_semantic_type = semantic_type
        self.qedge_id = qedge_id


class Lookup:
    def __init__( self, curie, predicate, is_source, node_names, node_types, lookup_ids,
                  params_output_semantic_type=[] ):
        self.predicate = predicate
        self.is_source = is_source
        self.link_ids = lookup_ids

        self.add_input_node(curie, node_types)
        self.add_input_node_name(node_names)
        self.add_links(node_names, node_types)
        self.add_linked_edges(curie, is_source)

    def add_input_node( self, curie, node_types ):
        """Optionally, we can patch by adding a new node, which will share a relationship of
        some sort to the curies in self.set_curies.  The remaining parameters give the edge_type
        of those edges, as well as defining whether the edge points to the newnode (newnode_is = 'target')
        or away from it (newnode_is = 'source') """
        self.input_qnode_curie = NewNode(curie, node_types.get(curie, None))

    def add_input_node_name( self, node_names ):
        self.input_qnode_curie.name = node_names.get(self.input_qnode_curie.new_curie, None)

    def add_links( self, nodenames, nodetypes ):
        self.lookup_links = [Lookup_Links(link_id, nodenames.get(link_id), nodetypes.get(link_id)) for link_id in
                             self.link_ids]

    def add_linked_edges( self, input_node, input_node_is_source ):
        """Add edges between the newnode (curie) and the curies that they were linked to"""
        if input_node_is_source:
            for i, new_ids in enumerate(self.link_ids):
                self.lookup_links[i].link_edge = NewEdge(input_node, self.predicate, new_ids)
        else:
            for i, new_ids in enumerate(self.link_ids):
                self.lookup_links[i].link_edge = NewEdge(new_ids, self.predicate, input_node)

    def get_prov_links( self ):
        return [link.link_edge.get_prov_link() for link in self.lookup_links]

    def add_provenance( self, prov ):
        for link in self.lookup_links:
            if prov.get(link.link_edge.get_prov_link()):
                link.link_edge.add_prov(prov[link.link_edge.get_prov_link()])
            else:
                link.link_edge.add_prov(prov[link.link_edge.get_sym_prov_link()])

    def add_enrichment( self, lookup_indices, enriched_node, predicate, is_source, pvalue ):
        for index in lookup_indices:
            if hasattr(self.lookup_links[index], 'enrichments'):
                self.lookup_links[index].enrichments.append(
                    Link_enrichment(enriched_node, predicate, is_source, pvalue))
            else:
                self.lookup_links[index].enrichments = [Link_enrichment(enriched_node, predicate, is_source, pvalue)]


class Lookup_Links:
    def __init__( self, link_id, link_name, link_type ):
        self.link_edge = None
        self.link_id = link_id
        self.link_name = link_name
        self.link_type = link_type


class Link_enrichment:
    def __init__( self, enriched_node, predicate, is_source, pvalue ):
        self.enriched_node = enriched_node
        self.predicate = predicate
        self.is_source = is_source
        self.p_value = pvalue


class Enrichment:
    def __init__( self, p_value, newnode: str, predicate: str, is_source, ndraws, n, total_node_count, curies,
                  node_type: list[str] ):
        """Here the curies are the curies that actually link to newnode, not just the input curies."""
        self.p_value = p_value
        self.linked_curies = curies
        self.enriched_node = None
        self.predicate = predicate
        self.is_source = is_source
        self.provmap = {}
        self.add_extra_node(newnode, node_type)
        self.add_extra_edges(newnode, predicate, is_source)
        self.counts = [ndraws, n, total_node_count]

    def add_extra_node( self, newnode, newnodetype: list[str] ):
        """Optionally, we can patch by adding a new node, which will share a relationship of
        some sort to the curies in self.set_curies.  The remaining parameters give the edge_type
        of those edges, as well as defining whether the edge points to the newnode (newnode_is = 'target')
        or away from it (newnode_is = 'source') """
        self.enriched_node = NewNode(newnode, newnodetype)

    def add_extra_node_name_and_label( self, name_dict, label_dict ):
        self.enriched_node.newnode_name = name_dict.get(self.enriched_node.new_curie, None)
        self.enriched_node.newnode_type = label_dict.get(self.enriched_node.new_curie, [])

    def add_extra_edges( self, newnode, predicate: str, newnode_is_source ):
        """Add edges between the newnode (curie) and the curies that they were linked to"""
        if newnode_is_source:
            self.links = [NewEdge(newnode, predicate, curie) for curie in self.linked_curies]
        else:
            self.links = [NewEdge(curie, predicate, newnode) for curie in self.linked_curies]

    def get_prov_links( self ):
        return [link.get_prov_link() for link in self.links]

    def add_provenance( self, prov ):
        for link in self.links:
            provlink = link.get_prov_link()
            symprovlink = link.get_sym_prov_link()
            if prov.get(provlink):
                link.add_prov(prov[provlink])
            else:
                link.add_prov(prov[symprovlink])
