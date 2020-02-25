from collections import defaultdict

def coalesce(answers):
    """Given a set of answers coalesce them and return some combined answers.
    In this case, we are going to first look for places where answers are all the same
    except for a single node.
    For this prototype, the answers must all be the same shape.
    There are plenty of ways to extend this, including adding edges to the coalescent
    entities.
    """
    #Look for places to combine
    identify_coalescent_nodes(answers)
    return answers

def identify_coalescent_nodes(answers):
    """Given a set of answers, locate answersets that are equivalent except for a single
    element.  For instance if we have an answer (a)-(b)-(c) and another answer (a)-(b')-(c)
    we will return (a)-(*)-(c) [b,b'].
    Note that the goal is not to coalesce every answer in the set into a single thing, but to
    find all the possible coalescent locations of 2 or more answers."""
    #In this implementation, we characterize each result with a frozendict that we can compare.
    #This is essentially just the node and edge bindings for the answer, except for 1) one node
    # that is allowed to vary and 2) the edges attached to that node, that are allowed to vary in
    # identity but must remain constant in type.
    question = answers['question_graph']
    graph = answers['knowledge_graph']
    inputs = answers['answers']
    for result in inputs:
        hashes = make_answer_hashes(result,graph,question)

def make_answer_hashes(result,graph,question):
    #First combine the node and edge bindings into a single dictionary, making sure that the same id is not
    #used for both a node and edge.
    bindings = { f'n_{qg_id}': kg_id for qg_id, kg_id in result['node_bindings'].items() }
    bindings.update({ f'e_{qg_id}': kg_id for qg_id, kg_id in result['edge_bindings'].items() } )
    for qg_id in result['node_bindings']:
        newhash = make_answer_hash(bindings,graph,question,qg_id)

def make_answer_hash(bindings,graph,question,qg_id):
    """given a combined node/edge bindings dictionary, plus the knowledge graph it points to and the question graph,
    create a key that characterizes the answer, except for one of the nodes (and its edges)."""
    singlehash = bindings.copy()
    #take out the binding for qg_id
    del singlehash[f'n_{qg_id}']
    #Now figure out which edges hook to qg_id
    #Note that we're keeping source and target edges separately.  If the question doesn't define a direction,
    # we might end up with edges pointing either way, and we need to compare that as well.
    sedges = list(filter( lambda x: x['source_id'] == qg_id, question['edges']))
    tedges = list(filter( lambda x: x['target_id'] == qg_id, question['edges']))
    sedge_types = { f's_{se["id"]}': graph['edges'][singlehash[f'e_{se["id"]}']]['type'] for se in sedges }
    tedge_types = { f'e_{se["id"]}': graph['edges'][singlehash[f'e_{se["id"]}']]['type'] for se in tedges }
    #Add in the edge types to our hash
    singlehash.update(sedge_types)
    singlehash.update(tedge_types)
    #Take the original qgid connected edges out of the hash
    for edge in sedges+tedges:
        del singlehash[f'e_{edge["id"]}']
    #Now we need to add back in types for the qg_id related edges.
    h = [ xi for xi in singlehash.items() ]
    h.sort()
    return tuple(h)

def _identify_coalescent_nodes(answers):
    """Given a set of answers, locate answersets that are equivalent except for a single
    element.  For instance if we have an answer (a)-(b)-(c) and another answer (a)-(b')-(c)
    we will return (a)-(*)-(c) [b,b'].
    Note that the goal is not to coalesce every answer in the set into a single thing, but to
    find all the possible coalescent locations of 2 or more answers."""
    #What we're really looking for are results that have equivalent edge types, and
    # also share all node bindings except for 1.
    question = answers['query_graph']
    graph = answers['knowledge_graph']
    inputs = answers['results']
    #First, find all the groups of results that only vary in one spot.
    identify_node_differing_groups(inputs,question,graph)

def identify_node_differing_groups(results, question_graph, knowledge_graph):
    """Given a list of results, find groupings that have all the same node bindings except
    for a single node."""
    #I'm not sure this is the best implementation.  I think that there's maybe a simpler version that does an NxN
    # type comparison and characterizes how each pair differs, and makes cliques that way.  I think that this
    # potentially simpler approach is probably slower, but if it fails fast on the comparison, maybe it would be
    # equivalent speed and maybe? simpler?

    #Index the results
    index = index_results(results)
    #Now, we're going to go qg_id by qg_id, and make groups
    for variable_qg_id in index: #This is the qg that is allowed to be different
        #Look for cases where we match on nodes.
        matches = find_partial_matches_by_node(index,variable_qg_id)
        #Now double check those based on the edges
        matches = filter_matches_by_edges(matches,question_graph,knowledge_graph,results)

def filter_matches_by_edges(matches, question_graph, knowledge_graph, results):
    """Given a list of matches, each of which is a pair (qgkg_dict, result_indices), plus
    the input question graph and resulting knowledge graph, pare down the matches to matches
    that also match on predicates.   For edges where both source and target are in the qgkg
    dictionary, we can check for exact edge match in the kg.   But for cases where one or the
    other of the nodes for an edges is the vnode for the match, then by definition the edges
    will not be identical.  In that case, we check the predicates for the edge.  They  must be
    the same."""
    #it's possible that each match set will contain N subsets once we're worried about edges. gross.

    return []

def find_partial_matches_by_node(index,variable_qg_id):
    """Given a bunch of indexed answers, find sets of answers where the answers all share qg->kg mappings,
    except for one qg node (specified).  This doesn't check edges at all, that's done in a separate step"""
    last_sets = None
    for qg_id in index:
        new_sets = []
        if qg_id == variable_qg_id:
            continue
        if last_sets is None:
            # First pass here.
            for kg_id,asets in index[qg_id].items():
                if len(asets) > 1:
                    new_sets.append( ( {qg_id:kg_id}, asets ) )
        else:
            #There's already some sets, intersect them
            for kg_id,aset in index[qg_id].items():
                for kg_id_dict, oldset in last_sets:
                    newset = oldset.intersection(aset)
                    if len(newset) > 1:
                        newdict = kg_id_dict.copy()
                        newdict.update( {qg_id:kg_id})
                        new_sets.append( (newdict, newset) )
        last_sets = new_sets
        if len(last_sets) == 0:
            break
    return last_sets


def index_results(results):
    """Given a list of results, and a list of gq ids, return a dictionary
    going qg_id -> kg_id -> [index of results with that mapping] """
    index = defaultdict( lambda: defaultdict(set))
    for i,result in enumerate(results):
        nb = result['node_bindings']
        for binding in nb:
            index[binding['qg_id']][binding['kg_id']].add(i)
    return index
