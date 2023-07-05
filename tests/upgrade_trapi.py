"""TRAPI 0.9.2 to 1.0.0. to 1.4"""
from collections import defaultdict
import pydantic
from typing import Literal, List
from pydantic import BaseModel
from enum import Enum


# Currently in use
def upgrade_Node(node):
    """Upgrade Node from 0.9.2 to 1.0.0."""
    node = {**node}
    new = dict()
    if "categories" in node:
        new["categories"] = [
            upgrade_BiolinkEntity(node_type)  # node.type is a list[str]
            for node_type in node.get("categories", [])
        ]
    if "name" in node:
        new["name"] = node.get("name", '')
    if "attributes" in node and node['attributes']:
        # add remaining properties as attributes
        new["attributes"] = [
            {
                "attribute_type_id": node_attr.get('attribute_type_id', None),
                "value": node_attr.get('value', None),
                "value_type_id":node_attr.get("value_type_id", None),
                "original_attribute_name": node_attr.get('original_attribute_name', None)
            }
            for node_attr in node.get('attributes', [])
        ]
    else:
        new["attributes"] = []

    return new


# Currently in use
def upgrade_Edge(edge):
    """Upgrade Edge from 0.9.2 to 1.4.0."""
    possible_roles = ('aggregator_knowledge_source', 'primary_knowledge_source', 'supporting_data_source')

    edge = {**edge}
    new = {
        "subject": edge.get("subject"),
        "object": edge.get("object"),
        "predicate": edge.get("predicate"),
        "qualifiers": edge.get("qualifiers"),
    }
    if edge:
        # add remaining properties as attributes
        new["attributes"] = [
            {
                "attribute_type_id": edge_attr.get('attribute_type_id', None),
                "value": edge_attr.get('value', None),
                "value_type_id":edge_attr.get("value_type_id", None),
                "original_attribute_name": edge_attr.get('original_attribute_name', None)
            }
            for edge_attr in edge.get('attributes', [])
        ]
        new['sources'] = [
            {
                "resource_id": edge_attr.get('attribute_source', None),
                "resource_role":edge_attr.get("attribute_type_id", None).replace('biolink:', '')
            }
            for edge_attr in edge.get('attributes', [])
            if edge_attr.get('attribute_source') and
               'infores' in edge_attr.get('attribute_source') and
               edge_attr.get("attribute_type_id") in possible_roles
        ]
        # Found some weird
        # D.1_strider: '22873063' has 'knowledge_source' instead of 'primary_knowledge_source'
        # Edge attribute has attribute_type_id as 'biolink:aggregator_knowledge_source'

        if new['sources']:
            # Major hitches to submit a PR, would check this later
            sources = []
            for source in new['sources']:
                source1 = {'resource_id': 'infores:automat-robokop', 'resource_role': 'aggregator_knowledge_source'}
                source2 = {'resource_id': 'infores:aragorn', 'resource_role': 'aggregator_knowledge_source'}
                source1['upstream_resource_ids'] = [source.get('resource_id', None)]
                source2['upstream_resource_ids'] = [source1.get('resource_id', None)]
                sources.extend([source1, source2])
            new['sources'] = new['sources'] + sources
    return new


def upgrade_KnowledgeGraph(kgraph):
    """Upgrade KnowledgeGraph from 0.9.2 to 1.0.0."""
    return {
        "nodes": {
            knode: upgrade_Node(kgraph["nodes"][knode])
            for knode in kgraph["nodes"]
        },
        "edges": {
            kedge : upgrade_Edge(kgraph["edges"][kedge])
            for kedge in kgraph["edges"]
        },
    }



# Currently in use
def upgrade_results(results):
    if isinstance(results, list):
        upgraded_trapi1_4 = []
        for result in results:
            upgraded_result = {
                "node_bindings": result["node_bindings"],
                "analyses": [
                    {
                        "resource_id": result.get('resource_id', "infores:automat-robokop"),
                        "edge_bindings": result.get("edge_bindings", {}),
                        "score": result.get("score", 0.)
                    }
                ]
            }
            upgraded_trapi1_4.append(upgraded_result)
    else:
        upgraded_trapi1_4 = {
                "node_bindings": results["node_bindings"],
                "analyses": [
                    {
                        "edge_bindings": results.get("edge_bindings", {}),
                        "score": results.get("score", 0.)
                    }
                ]
            }
    return upgraded_trapi1_4


# Currently in use
def upgrade_Message(message):
    """Upgrade Message from 0.9.2 to 1.0.0."""
    new = dict()
    if "query_graph" in message:
        new["query_graph"] = message["query_graph"]
    if "knowledge_graph" in message:
        new["knowledge_graph"] = upgrade_KnowledgeGraph(message["knowledge_graph"])
    if "results" in message:
        new["results"] = upgrade_results(message["results"])
    return new


# Not in use
def upgrade_BiolinkEntity(biolink_entity):
    """Upgrade BiolinkEntity from 0.9.2 to 1.0.0."""
    if biolink_entity.startswith("biolink:"):
        return biolink_entity
    return "biolink:" + pascal_case(biolink_entity)

# Not in use
def upgrade_BiolinkRelation(biolink_relation):
    """Upgrade BiolinkRelation (0.9.2) to BiolinkPredicate (1.0.0)."""
    if biolink_relation is None:
        return None
    if biolink_relation.startswith("biolink:"):
        return biolink_relation
    return "biolink:" + snake_case(biolink_relation)

# Not in use
def upgrade_QNode(qnode):
    """Upgrade QNode from 0.9.2 to 1.0.0."""
    qnode = {**qnode}
    qnode.pop("id")
    new = dict()
    if "type" in qnode:
        new["category"] = upgrade_BiolinkEntity(qnode.pop("type"))
    if "curie" in qnode:
        new["id"] = qnode.pop("curie")
    # add remaining properties verbatim
    new = {
        **new,
        **qnode,
    }
    return new


# Not in use
def upgrade_QEdge(qedge):
    """Upgrade QEdge from 0.9.2 to 1.0.0."""
    qedge = {**qedge}
    qedge.pop("id")
    new = {
        "subject": qedge.pop("source_id"),
        "object": qedge.pop("target_id"),
    }
    if "type" in qedge:
        new["predicate"] = upgrade_BiolinkRelation(qedge.pop("type"))
    if "relation" in qedge:
        new["relation"] = qedge.pop("relation")
    # add remaining properties verbatim
    new = {
        **new,
        **qedge,
    }
    return new

# Not in use
def upgrade_QueryGraph(qgraph):
    """Upgrade QueryGraph from 0.9.2 to 1.0.0."""
    return {
        "nodes": {
            qnode["id"]: upgrade_QNode(qnode)
            for qnode in qgraph["nodes"]
        },
        "edges": {
            qedge["id"]: upgrade_QEdge(qedge)
            for qedge in qgraph["edges"]
        },
    }

# Not in use
def upgrade_NodeBinding(node_binding):
    """Upgrade NodeBinding from 0.9.2 to 1.0.0."""
    for kg_id in ensure_list(node_binding["kg_id"]):
        new = {
            "id": kg_id,
        }
        for key, value in node_binding.items():
            if key in ("qg_id", "kg_id"):
                continue
            new[key] = value
        yield new

# Not in use
def upgrade_EdgeBinding(edge_binding):
    """Upgrade EdgeBinding from 0.9.2 to 1.0.0."""
    for kg_id in ensure_list(edge_binding["kg_id"]):
        new = {
            "id": kg_id,
        }
        for key, value in edge_binding.items():
            if key in ("qg_id", "kg_id"):
                continue
            new[key] = value
        yield new



def upgrade_Result(result):
    """Upgrade Result from 0.9.2 to 1.0.0."""
    result = {**result}
    new = {
        "node_bindings": defaultdict(list),
        "edge_bindings": defaultdict(list),
    }
    for node_binding in result.pop("node_bindings"):
        new["node_bindings"][node_binding["qg_id"]].extend(
            upgrade_NodeBinding(node_binding)
        )
    for edge_binding in result.pop("edge_bindings"):
        new["edge_bindings"][edge_binding["qg_id"]].extend(
            upgrade_EdgeBinding(edge_binding)
        )
    new = {
        **new,
        **result,
    }
    return new


def upgrade_Query(query):
    """Upgrade Query from 0.9.2 to 1.0.0."""
    query = {**query}
    return {
        "message": upgrade_Message(query.pop("message")),
        **query,
    }