from collections import defaultdict
from scipy.stats import hypergeom

def coalesce_by_property(opportunities):
    for opportunity in opportunities:
        nodes = opportunity[2] #this is the list of curies that can be in the given spot
        properties = collect_properties(nodes) #properties = {property: (curies with it)}
        for property,curies in properties.items():
            #The hypergeometric distribution models drawing objects from a bin.
            # M is the total number of objects (nodes) ,
            # n is total number of Type I objects (nodes with that property).
            # The random variate represents the number of Type I objects in N drawn
            #  without replacement from the total population (len curies).
            x = len(curies) #draws with the property
            total_node_count=400
            n = total_nodes_with_property(property)
            ndraws = len(nodes)
            enrichp = hypergeom.sf(x-1, total_node_count, n, ndraws)
    return []

def collect_properties(nodes):
    """
    given a list of curies, go somewhere and find out all of the properties that two or more
    of the nodes share.  Return a dict from the shared property to the nodes.
    """
    #Right now, we're going to load the property file, but we should replace with a redis.
    # It could also point to a big graph like robokop or something else.
    propmap = defaultdict(int)
    prop2nodes = defaultdict(list)
    for node in nodes:
        properties = propmap[node]
        for prop in properties:
            prop2nodes[prop].append(node)
    returnmap = {}
    for prop,nodelist in prop2nodes.items():
        if len(nodelist) > 1:
            returnmap[prop] = nodelist
    return returnmap

def total_nodes_with_property(property):
    """Given a property, what are the total number of nodes that have it?"""
    #Currently pulling from a file, but let's move it into a redis
    propmap = defaultdict(int)
    return propmap[property]
