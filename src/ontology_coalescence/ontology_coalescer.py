from collections import defaultdict
from scipy.stats import hypergeom
from src.ontology_coalescence.ubergraph import UberGraph


def coalesce_by_ontology(opportunities):
    """
    Given opportunities for coalescence, potentially turn each into patches that can be applied to an answer
    patch = [qg_id of the node that is being replaced, curies (kg_ids) in the new combined set, props for the new curies,
    qg_id of the edges being removed/combined, answers being collapsed]
    """
    patches = []
    for opportunity in opportunities:
        nodes = opportunity[2] #this is the list of curies that can be in the given spot
        qg_id,stype = opportunity[1]
        enriched_properties = get_enriched_superclasses(nodes,stype)
        #There will be multiple ways to combine the same curies
        # group by curies.
        c2e = defaultdict(list)
        for ep in enriched_properties:
            c2e[ep[5]].append(ep)
        #now construct a patch for each curie set.
        for curieset,eps in c2e.items():
            #patch = [kg_id that is being replaced, curies in the new combined set, props for the new curies, answers being collapsed]
            newprops = {'coalescence_method':'property_enrichment',
                        'p_values': [x[0] for x in eps],
                        'properties': [x[1] for x in eps]}
            patch = [qg_id,curieset,newprops,opportunity[3]]
            patches.append(patch)
    return patches

def get_shared_superclasses(nodes,prefix):
    ug = UberGraph()
    superclasses = set(ug.get_superclasses_of(nodes[0]))
    for ni in nodes[1:]:
        superclasses = superclasses.intersection(ug.get_superclasses_of(ni))
    #let's only return superclasses with the prefix of our node
    superclasses = set( filter( lambda x: x.startswith(prefix), superclasses))
    return superclasses

def get_enriched_superclasses(nodes,semantic_type,pcut=1e-4):
    prefixes = set( [n.split(':')[0] for n in nodes ])
    if len(prefixes) > 1:
        return []
    prefix = list(prefixes)[0]
    shared_superclasses = get_shared_superclasses(nodes,prefix)
    ug = UberGraph()
    enriched = []
    for ssc in shared_superclasses:
        # The hypergeometric distribution models drawing objects from a bin.
        # M is the total number of objects (nodes) ,
        # n is total number of Type I objects (nodes with that property).
        # The random variate represents the number of Type I objects in N drawn
        #  without replacement from the total population (len curies).
        x = len(nodes)  # draws with the property
        total_node_count = get_total_nodecount(semantic_type,prefix)
        n = ug.count_subclasses_of(ssc) #total nodes with property of being a subclass of ssc
        ndraws = len(nodes)
        enrichp = hypergeom.sf(x - 1, total_node_count, n, ndraws)
        if enrichp < pcut:
            enriched.append( (enrichp, ssc, ndraws, n, total_node_count, nodes) )
    enriched.sort()
    return enriched

def get_total_nodecount(stype,prefix):
    #This is a straight up hack.
    if prefix == 'MONDO':
        return 22000
    if prefix == 'CHEBI':
        return 130000
    if stype == 'cellular_component':
        return 4186
    if stype == 'molecular_activity':
        return 11000
    if stype == 'biological_function':
        return 30000
    if stype == 'biological_function_or_activity':
        return 41000
    if stype == 'phenotypic_feature':
        return 13000
    if prefix == 'CL':
        return 11000
    if prefix == 'UBERON':
        return 15000



