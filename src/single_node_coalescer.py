from collections import defaultdict
from copy import deepcopy
# from datetime import datetime as dt
from reasoner_pydantic import Response as PDResponse
from reasoner_pydantic import KnowledgeGraph
from src.components import Opportunity, Answer
from src.property_coalescence.property_coalescer import coalesce_by_property
from src.graph_coalescence.graph_coalescer import coalesce_by_graph, coalesce_by_graph_
from src.set_coalescence.set_coalescer import coalesce_by_set


def coalesce(answerset, method='all', predicates_to_exclude=None, properties_to_exclude=None, nodesets_to_exclude=None, pvalue_threshold=0, limit=None):
    """
    Given a set of answers coalesce them and return some combined answers.
    In this case, we are going to first look for places where answers are all the same
    except for a single node.
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

        patches += coalesce_by_graph_(coalescence_opportunities, predicates_to_exclude, pvalue_threshold, limit)

        new_answers = patch_answers_(answerset, coalescence_opportunities, patches)

        new_answerset = new_answers['message']

    else:
        # reformat answerset
        # # NB: we could remove this once it's certain that every query is trapi1.4 compliant
        answerset['results'] = is_trapi1_4(answerset['results'])

        # Look for places to combine
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
            patches += coalesce_by_graph(coalescence_opportunities, predicates_to_exclude, pvalue_threshold)

        # print('lets patch')
        #Enrichment done and commonalities found, at this point we can rewrite the results
        new_answers, aux_graphs, updated_qg, updated_kg = patch_answers(answerset, patches)

        new_answerset = {'query_graph': updated_qg, 'knowledge_graph': updated_kg, 'results': new_answers, 'auxiliary_graphs': aux_graphs}

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

def patch_answers_(answerset, nodeset, patches):
    # probably only good for the prop coalescer
    # We want to maintain a single kg, and qg.
    qg = answerset.get('query_graph', {})
    # kg = answerset.get('knowledge_graph', {})
    i = 0
    kg_indexes = {}
    pydantic_kgraph = KnowledgeGraph.parse_obj({"nodes": {}, "edges": {}})
    result = PDResponse(**{
        "message": {"query_graph": {"nodes": {}, "edges": {}},
                    "knowledge_graph": {"nodes": {}, "edges": {}},
                    "results": []}}).dict(exclude_none=True)
    if patches:
        for patch in patches:
            # Patches: includes all enriched nodes attached to a certain enrichment by an edge as well as the enriched nodes +attributes
            i += 1
            print(f'{i} / {len(patches)}')
            new_answer, updated_kg, kg_indexes = patch.apply_(nodeset, result['message']['knowledge_graph'], kg_indexes, i)
            # .apply adds the enrichment and edges to the kg and return individual enriched node attached to a certain enrichment by an edge
            pydantic_kgraph.update(KnowledgeGraph.parse_obj(updated_kg))
            # Construct the final result message, currently empty
            result["message"]["results"].extend(new_answer)
        result["message"]["query_graph"] = qg
        result["message"]["knowledge_graph"] = pydantic_kgraph.dict()

    return result

def patch_answers(answerset, patches):
    # probably only good for the prop coalescer
    # We want to maintain a single kg, and qg.
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']

    answers = [Answer(ans, qg, kg) for ans in is_trapi1_4(answerset['results'])]
    new_answers = []
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
            print(f'{i} / {len(patches)}')

            all_new_answer, qg, kg, kg_indexes = patch.apply(answers, qg, kg, kg_indexes, i)
            # .apply adds the enrichment and edges to the kg and return individual enriched node attached to a certain enrichment by an edge

        """Serialize the answer back to ReasonerStd JSON 1.0"""
        for answer in all_new_answer:
            new_answers.append(answer.to_json())
            auxiliary_graphs.update(answer.get_auxiliarygraph())
        aux_g = auxiliary_graphs
        return new_answers, dict(sorted(aux_g.items(), key=lambda x: int(x[0].split('_')[3]))), qg, kg
    else:
        for answer in answers:
            new_answers.append(answer.to_json())
        return new_answers, auxiliary_graphs, qg, kg

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
            opportunity['question_id'] = qg_id  #genes
            opportunity['question_type'] = category
        else:
            opportunity['answer_id'] = qg_id #chemical
            opportunity['answer_type'] = node_data["categories"][0] if "categories" in node_data and node_data["categories"] else None
            opportunity['qg_curies'] = allnodes

    for qg_eid, edge_data in query_graph.get("edges", {}).items():
        alledges[qg_eid] = edge_data['predicates'][0]

    opportunity['answer_edge'] = alledges

    return opportunity

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


    # answers = [Answer(ans, question, graph) for ans in is_trapi1_4(answerset['results'])]
    answers = [Answer(ans, question, graph) for ans in answerset['results']]
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
