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
    #What we're really looking for are results that have equivalent edge types, and
    # also share all node bindings except for 1.
    graph = answers['result_graph']
    inputs = answers['results']
    #First, find all the groups of results that only vary in one spot.
    identify_node_differing_groups(inputs)

def identify_node_differing_groups(results):
    """Given a list of results, find groupings that have all the same node bindings except
    for a single node."""
    #Index the results
    index = index_results(results)
    #Now, we're going to go qg_id by qg_id, and make groups
    for gq_id in index:
        pass

def index_results(results):
    """Given a list of results, and a list of gq ids, return a dictionary
    going qg_id -> kg_id -> [index of results with that mapping] """
    index = defaultdict( lambda: defaultdict(list))
    for i,result in enumerate(results):
        nb = result['node_bindings']
        for binding in nb:
            index[binding['qg_id']][binding['kg_id']].append(i)
    return index
