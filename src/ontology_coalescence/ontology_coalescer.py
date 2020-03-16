from collections import defaultdict
from scipy.stats import hypergeom
from src.ontology_coalescence.ubergraph import UberGraph
from src.components import PropertyPatch


def coalesce_by_ontology(opportunities):
    """
    Given opportunities for coalescence, potentially turn each into patches that can be applied to an answer
    patch = [qg_id of the node that is being replaced, curies (kg_ids) in the new combined set, props for the new curies,
    qg_id of the edges being removed/combined, answers being collapsed]
    """
    patches = []
    for opportunity in opportunities:
        nodes = opportunity.get_kg_ids() #this is the list of curies that can be in the given spot
        qg_id = opportunity.get_qg_id()
        stype = opportunity.get_qg_semantic_type()
        enriched_properties = get_enriched_superclasses(nodes,stype)
        #There will NOT be multiple ways to combine the same curies
        #now construct a patch for each curie set.
        #enriched_properties = [(enrichp, ssc, ndraws, n, total_node_count, nodeset)]
        for enrichp, superclass, ndraws, nhits, totalndoes, curieset in enriched_properties:
            #patch = [kg_id that is being replaced, curies in the new combined set, props for the new curies, answers being collapsed]
            newprops = {'coalescence_method':'ontology_enrichment',
                        'p_value': enrichp,
                        'superclass': superclass}
            patch = PropertyPatch(qg_id,curieset,newprops,opportunity.get_answer_indices())
            patch.add_extra_node(superclass,stype,edge_type='is_a',newnode_is='target')
            patches.append(patch)
    return patches

def get_shared_superclasses(nodes,prefix):
    """Return the intersection of the superclasses of every node in nodes"""
    ug = UberGraph()
    sc_to_nodes = defaultdict(set)
    for node in nodes:
        superclasses = ug.get_superclasses_of(node)
        for sc in superclasses:
            if sc.startswith(prefix):
                sc_to_nodes[sc].add(node)
    nodes_to_sc = defaultdict(list)
    for sc,nodes in sc_to_nodes.items():
        if len(nodes) > 1:
            nodes_to_sc[frozenset(nodes)].append(sc)
    return nodes_to_sc

def filter_class_nodes(inodes):
    onodes = []
    for inode in inodes:
        if inode.split(':')[0] in ('CHEBI','MONDO','HP','GO','CL','UBERON'):
            onodes.append(inode)
    return onodes

def get_enriched_superclasses(input_nodes,semantic_type,pcut=1e-6):
    """Get the most enriched superclass for a group of nodes."""
    nodes = filter_class_nodes(input_nodes)
    prefixes = set( [n.split(':')[0] for n in nodes ])
    if len(prefixes) > 1:
        return []
    prefix = list(prefixes)[0]
    nodeset_to_superclasses = get_shared_superclasses(nodes,prefix)
    ug = UberGraph()
    results = []
    for nodeset, shared_superclasses in nodeset_to_superclasses.items():
        enriched = []
        for ssc in shared_superclasses:
            # The hypergeometric distribution models drawing objects from a bin.
            # M is the total number of objects (nodes) ,
            # n is total number of Type I objects (nodes with that property).
            # The random variate represents the number of Type I objects in N drawn
            #  without replacement from the total population (len curies).
            x = len(nodeset)  # draws with the property
            total_node_count = get_total_nodecount(semantic_type,prefix)
            n = ug.count_subclasses_of(ssc) #total nodes with property of being a subclass of ssc
            ndraws = len(nodes)
            enrichp = hypergeom.sf(x - 1, total_node_count, n, ndraws)
            if enrichp < pcut:
                enriched.append( (enrichp, ssc, ndraws, n, total_node_count, nodeset) )
        enriched.sort()
        if len(enriched) > 0:
            results.append(enriched[0] )
    return results

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



