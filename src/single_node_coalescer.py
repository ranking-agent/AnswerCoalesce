from reasoner_pydantic import Response as PDResponse
from reasoner_pydantic import KnowledgeGraph
from src.graph_coalescence.graph_coalescer import coalesce_by_graph_


def coalesce(answerset):
    """
    Given a set of answers coalesce them and return some combined answers.
    In this case, we are going to first look for places where answers are all the same.
    For this prototype, the answers must all be the same shape.
    There are plenty of ways to extend this, including adding edges to the coalescent
    entities.
    """
    patches = []
    set_opportunity = {}

    for qg_id, node_data in answerset.get("query_graph", {}).get("nodes", {}).items():
        if 'ids' in node_data and node_data.get('is_set'):
            set_opportunity = get_opportunity(answerset)

    if set_opportunity:
        coalescence_opportunities = set_opportunity

        patches += coalesce_by_graph_(coalescence_opportunities)

        new_answers = patch_answers_(answerset, coalescence_opportunities, patches)

        new_answerset = new_answers['message']

    return new_answerset

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

