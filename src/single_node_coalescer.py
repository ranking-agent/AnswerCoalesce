from collections import defaultdict

# from datetime import datetime as dt

from src.components import Opportunity, Answer
from src.property_coalescence.property_coalescer import coalesce_by_property
from src.graph_coalescence.graph_coalescer import coalesce_by_graph


def coalesce(answerset, method='all', return_original=True):
    """
    Given a set of answers coalesce them and return some combined answers.
    In this case, we are going to first look for places where answers are all the same
    except for a single node.
    For this prototype, the answers must all be the same shape.
    There are plenty of ways to extend this, including adding edges to the coalescent
    entities.
    """

    # Look for places to combine
    coalescence_opportunities = identify_coalescent_nodes(answerset)

    patches = []

    if method in ['all', 'property']:
        patches += coalesce_by_property(coalescence_opportunities)

    if method in ['all', 'graph']:
        patches += coalesce_by_graph(coalescence_opportunities)

    # print('lets patch')
    new_answers, updated_qg, updated_kg = patch_answers(answerset, patches)

    if return_original:
        new_answers += answerset['results']

    new_answerset = {'query_graph': updated_qg, 'knowledge_graph': updated_kg, 'results': new_answers}

    return new_answerset


def patch_answers(answerset, patches):
    # probably only good for the prop coalescer
    # We want to maintain a single kg, and qg.
    qg = answerset['query_graph']
    kg = answerset['knowledge_graph']
    answers = [Answer(ans, qg, kg) for ans in answerset['results']]
    new_answers = []
    i = 0
    # If there are lots of patches, then we end up spending lots of time finding edges and nodes in the kg
    # as we update it.  kg_indexes are the indexes required to find things quickly.  apply both
    # looks in there, and updates it
    kg_indexes = {}
    for patch in patches:
        i += 1
        # print(f'{i} / {len(patches)}')
        new_answer, qg, kg, kg_indexes = patch.apply(answers, qg, kg, kg_indexes)
        if new_answer is not None:
            new_answers.append(new_answer.to_json())
    return new_answers, qg, kg


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
    answers = [Answer(ans, question, graph) for ans in answerset['results']]
    varhash_to_answers = defaultdict(list)
    varhash_to_qg = {}
    varhash_to_kg = defaultdict(set)
    varhash_to_answer_indices = defaultdict(list)
    for answer_i, answer in enumerate(answers):
        hashes = make_answer_hashes(answer, graph, question)
        for hash_item, qg_id, kg_id in hashes:
            varhash_to_answers[hash_item].append(answer_i)
            # qg_type = [node['type'] for node in question['nodes'] if node['id'] == qg_id][0]
            qg_type = question['nodes'][qg_id]['categories']
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
            opportunity = Opportunity(hash_item, varhash_to_qg[hash_item], varhash_to_kg[hash_item], varhash_to_answer_indices[hash_item])
            coalescent_nodes.append(opportunity)
    return coalescent_nodes


def make_answer_hashes(result, graph, question):
    """Given a single answer, find the hash for each answer node and return it along
    with the answer node that was varied, and the kg node id for that qnode in this answer"""
    # First combine the node and edge bindings into a single dictionary,
    # bindings = make_bindings(question, result)
    bindings = result.make_bindings()
    hashes = []
    # for qg_id in [x['qg_id'] for x in result['node_bindings']]:
    for qg_id, kg_ids in result.node_bindings.items():
        newhash = make_answer_hash(bindings, graph, question, qg_id)
        hashes.append((newhash, qg_id, kg_ids))
    return hashes


# def make_bindings(question, result):
#    """Given a question and a result, build a single bindings map, making sure that the same id is not
#    used for both a node and edge. Also remove any edge_bindings that are not part of the question, such
#    as support edges"""
#    question_nodes = [e['id'] for e in question['nodes']]
#    question_edges = [e['id'] for e in question['edges']]
#    bindings = defaultdict(list)
#    for nb in result['node_bindings']:
#        if nb['qg_id'] in question_nodes:
#            if isinstance(nb['kg_id'],list):
#                bindings[f'n_{nb["qg_id"]}'] += nb['kg_id']
#            else:
#                bindings[f'n_{nb["qg_id"]}'].append(nb['kg_id'])
#    for eb in result['edge_bindings']:
#        if eb['qg_id'] in question_edges:
#            if isinstance(nb['kg_id'],list):
#                bindings[f'e_{eb["qg_id"]}'] += eb['kg_id']
#            else:
#                bindings[f'e_{eb["qg_id"]}'].append(eb['kg_id'])
#    #bindings = {f'n_{nb["qg_id"]}': [nb['kg_id']] for nb in result['node_bindings'] if nb['qg_id'] in question_nodes}
#    #bindings.update( {f'e_{eb["qg_id"]}': [eb['kg_id']] for eb in result['edge_bindings'] if eb['qg_id'] in question_edges})
#    return bindings


def make_answer_hash(bindings, graph, question, qg_id):
    """given a combined node/edge bindings dictionary, plus the knowledge graph it points to and the question graph,
    create a key that characterizes the answer, except for one of the nodes (and its edges).
    The node that we're allowing to vary doesn't enter the hash.  The edges connected to that node, we replace
    by their types. That will then allow other answers with a different node but the same types of connections to
    that node to look the same under this hashing function"""
    # for some reason, the bindings are to lists?  Just grabbing the first (and only) element to the new bindings.
    singlehash = {x: frozenset(y) for x, y in bindings.items()}
    # take out the binding for qg_id
    del singlehash[qg_id]
    # Now figure out which edges hook to qg_id
    # Note that we're keeping source and target edges separately.  If the question doesn't define a direction,
    # we might end up with edges pointing either way, and we need to compare that as well.
    sedges = [edge_id for edge_id, edge in question['edges'].items() if edge['subject'] == qg_id]
    tedges = [edge_id for edge_id, edge in question['edges'].items() if edge['object'] == qg_id]
    # sedges = list(filter( lambda x: x['subject'] == qg_id, question['edges']))
    # tedges = list(filter( lambda x: x['object'] == qg_id, question['edges']))
    # make a map of kg edges to type.  probably move this out of make_answer_hash?
    kg_edgetypes = {edge_id: edge['predicate'] for edge_id, edge in graph['edges'].items()}
    # The double comprehension is a bit of a mess, but our singlehash values are sets
    # What is happening is that a given s or t edge, we want a map from that qgid (the id in sedges) we want to
    # get the kg edges.  Thats a set, we loop over it, and get the edgetypes from the kg for each, and make
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
