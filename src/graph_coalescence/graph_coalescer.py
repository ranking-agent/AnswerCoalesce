from collections import defaultdict
from scipy.stats import hypergeom
from src.graph_coalescence.robokop_messenger import RobokopMessenger
from src.components import PropertyPatch


def coalesce_by_graph(opportunities):
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
        enriched_properties = get_enriched_links(nodes,stype)
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

def get_shared_links(nodes,stype):
    """Return the intersection of the superclasses of every node in nodes"""
    rm = RobokopMessenger()
    links_to_nodes = defaultdict(set)
    for node in nodes:
        links = rm.get_links_for(node,stype)
        for link in links:
            links_to_nodes[link].add(node)
    nodes_to_links = defaultdict(list)
    for link,nodes in links_to_nodes.items():
        if len(nodes) > 1:
            nodes_to_links[frozenset(nodes)].append(link)
    return nodes_to_links

def get_enriched_links(nodes,semantic_type,pcut=1e-10):
    """Get the most enriched connected node for a group of nodes."""
    nodeset_to_links = get_shared_links(nodes,semantic_type)
    rm = RobokopMessenger()
    results = []
    for nodeset, possible_links in nodeset_to_links.items():
        enriched = []
        for newcurie,predicate,is_source in possible_links:
            # The hypergeometric distribution models drawing objects from a bin.
            # M is the total number of objects (nodes) ,
            # n is total number of Type I objects (nodes with that property).
            # The random variate represents the number of Type I objects in N drawn
            #  without replacement from the total population (len curies).
            x = len(nodeset)  # draws with the property
            total_node_count = 6000000 #not sure this is the right number. Scales overall p-values.
            #Note that is_source is from the point of view of the input nodes, not newcurie
            newcurie_is_source = not is_source
            n = rm.get_total_nodecount(newcurie,predicate,newcurie_is_source,semantic_type)
            ndraws = len(nodes)
            enrichp = hypergeom.sf(x - 1, total_node_count, n, ndraws)
            if enrichp < pcut:
                enriched.append( (enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset) )
        if len(enriched) > 0:
            results += enriched
    results.sort()
    return results


