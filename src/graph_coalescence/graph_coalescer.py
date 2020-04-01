from collections import defaultdict
from scipy.stats import hypergeom
from src.graph_coalescence.robokop_messenger import RobokopMessenger
from src.components import PropertyPatch
from src.util import LoggingUtil
import logging
import os

this_dir = os.path.dirname(os.path.realpath(__file__))

logger = LoggingUtil.init_logging('graph_coalescer', level=logging.DEBUG, format='long', logFilePath=this_dir+'/')


def coalesce_by_graph(opportunities):
    """
    Given opportunities for coalescence, potentially turn each into patches that can be applied to an answer
    patch = [qg_id of the node that is being replaced, curies (kg_ids) in the new combined set, props for the new curies,
    qg_id of the edges being removed/combined, answers being collapsed]
    """
    patches = []
    for opportunity in opportunities:
        logger.debug('Starting new opportunity')

        nodes = opportunity.get_kg_ids() #this is the list of curies that can be in the given spot
        qg_id = opportunity.get_qg_id()
        stype = opportunity.get_qg_semantic_type()

        enriched_links = get_enriched_links(nodes,stype)

        #For the moment, we're only going to return the best enrichment.  Note that this
        # might mean more than one shared node, if the cardinalities all come out the
        # same.  It's POC, really you'd like to include many of these.  But we don't want
        # to end up with more answers than we started with, so we need to parameterize, and
        # that's more work that we can do later.
        #(enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset) )
        best_enrich_p = enriched_links[0][0]
        best_grouping = enriched_links[0][7]
        best_enrichments = list(filter(lambda x: (x[0] == best_enrich_p) and x[7] == best_grouping,enriched_links))
        newprops = {'coalescence_method':'graph_enrichment',
                    'p_value': best_enrich_p,
                    'enriched_nodes': [x[1] for x in best_enrichments]}
        patch = PropertyPatch(qg_id,best_grouping,newprops,opportunity.get_answer_indices())
        for e in best_enrichments:
            newcurie = e[1]
            etype = e[2]
            if e[3]:
                nni = 'target'
            else:
                nni = 'source'
            #Need to get the right node type.
            patch.add_extra_node(newcurie,'named_thing',edge_type=etype,newnode_is=nni)
        patches.append(patch)
        logger.debug('end of opportunity')

    return patches

def get_shared_links(nodes, stype):
    """Return the intersection of the superclasses of every node in nodes"""
    rm = RobokopMessenger()
    links_to_nodes = defaultdict(set)
    for node in nodes:
        logger.debug(f'start get_links_for({node}, {stype})')
        links = rm.get_links_for(node, stype)
        logger.debug('end get_links_for()')
        for link in links:
            links_to_nodes[link].add(node)
    nodes_to_links = defaultdict(list)
    for link,nodes in links_to_nodes.items():
        if len(nodes) > 1:
            nodes_to_links[frozenset(nodes)].append(link)

    logger.debug(f'total RK hit count: {rm.RK_call_count}')

    return nodes_to_links

def get_enriched_links(nodes,semantic_type,pcut=1e-6):
    logger.debug ('start get_enriched_links()')

    """Get the most enriched connected node for a group of nodes."""
    logger.debug ('start get_shared_links()')
    nodeset_to_links = get_shared_links(nodes,semantic_type)
    logger.debug ('end get_shared_links()')

    rm = RobokopMessenger()
    results = []
    for nodeset, possible_links in nodeset_to_links.items():
        logger.debug ('start processing of get_shared_links()')
        enriched = []
        for newcurie,predicate,is_source in possible_links:
            # The hypergeometric distribution models drawing objects from a bin.
            # M is the total number of objects (nodes) ,
            # n is total number of Type I objects (nodes with that property).
            # The random variate represents the number of Type I objects in N drawn
            #  without replacement from the total population (len curies).

            x = len(nodeset)  # draws with the property

            total_node_count = get_total_node_count(semantic_type)

            #total_node_count = 6000000 #not sure this is the right number. Scales overall p-values.
            #Note that is_source is from the point of view of the input nodes, not newcurie

            newcurie_is_source = not is_source

            logger.debug (f'start get_hit_node_count({newcurie}, {predicate}, {newcurie_is_source}, {semantic_type})')
            n = rm.get_hit_node_count(newcurie, predicate, newcurie_is_source, semantic_type)
            logger.debug (f'end get_hit_node_count() = {n}, start get_hit_nodecount_old()')
            y = rm.get_hit_nodecount_old(newcurie, predicate, newcurie_is_source, semantic_type)
            logger.debug (f'end get_hit_nodecount_old() = {y}')

            ndraws = len(nodes)

            enrichp = hypergeom.sf(x - 1, total_node_count, n, ndraws)

            if enrichp < pcut:
                enriched.append( (enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset) )
        if len(enriched) > 0:
            results += enriched

    results.sort()

    logger.debug ('end get_enriched_links()')
    return results

def get_total_node_count(semantic_type):
    """In the hypergeometric calculation, you're drawing balls from a bag, and you have
    to know the total number of possible draws.  What should that be?   It could be the number
    of nodes in the graph, but is that fair?  If I'm expanding from say, a chemical, there are
    only certain nodes and certain kinds of nodes that I can connect to.  Is it fair
    to say that the total number of nodes is all the nodes?

    In some sense it doesn't matter, because all you're doing is scaling the p-value, but it
    might make sense because of the way that variants are affecting things.   They are
    preferentially hooked to certain nodes.  So another approach would be to leave them
    out of everything.  But that doesn't seem fair either.  Especially b/c of gwas catalog.
    (or maybe even gtex).

    So here, we're going to say that if you have stype, then we're looking at
    match (a:stype)--(n) return count distinct n.  For genes and for anatomical features,
    we're ignoring variants, because we don't really want to deal with gtex right now, and we
    might need to consider the independently somehow?  These numbers are precomputed using
    the robokopdb2 database march 7, 2020."""
    stype2counts = {'disease':84000,
                    'gene':329000,
                    'phenotypic_feature':74000,
                    'disease_or_phenotypic_feature':174000,
                    'chemical_substance':214000,
                    'anatomical_entity':112000,
                    'cell':40000,
                    'biological_process':133000,
                    'molecular_activity':86000,
                    'biological_process_or_activity':148000 }
    if semantic_type in stype2counts:
        return stype2counts[semantic_type]
    #Give up and return the total number of nodes
    return 6000000
