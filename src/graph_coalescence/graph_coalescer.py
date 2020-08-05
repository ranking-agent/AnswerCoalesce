from collections import defaultdict
from scipy.stats import hypergeom
from src.graph_coalescence.robokop_messenger import RobokopMessenger
from src.components import PropertyPatch
from src.util import LoggingUtil
import logging
import os
import redis
import json
import ast


this_dir = os.path.dirname(os.path.realpath(__file__))

logger = LoggingUtil.init_logging('graph_coalescer', level=logging.WARNING, format='long', logFilePath=this_dir+'/')


def coalesce_by_graph(opportunities):
    """
    Given opportunities for coalescence, potentially turn each into patches that can be applied to an answer
    patch = [qg_id of the node that is being replaced, curies (kg_ids) in the new combined set, props for the new curies,
    qg_id of the edges being removed/combined, answers being collapsed]
    """
    patches = []

    logger.info(f'Start of processing. {len(opportunities)} opportunities discovered.')

    #Multiple opportunities are going to use the same nodes.  In one random (large) example where there are about
    # 2k opportunities, there are a total of 577 unique nodes, but with repeats, we'd end up calling messenger 3650
    # times.  So instead, we will unique the nodes here, call messenger once each, and then pull from that
    # collected set of info.


    allnodes = {}
    for opportunity in opportunities:
        kn = opportunity.get_kg_ids()
        stype = opportunity.get_qg_semantic_type()
        for node in kn:
            allnodes[node] = stype

    r = redis.Redis(host='localhost', port=6379, db=0)

    from datetime import datetime as dt
    print('start',dt.now())
    rm = RobokopMessenger()
    nodes_to_links = {}
    nodes_type_list = {}
    for node,stype in allnodes.items():
        logger.debug(f'start get_links_for({node}, {stype})')
        #links = rm.get_links_for(node, stype, nodes_type_list)
        linkstring = r.get(node)
        links = json.loads(linkstring)
        logger.debug('end get_links_for()')
        nodes_to_links[node] = links
    print('end', dt.now())

    #Also crossing all opportunities, we'll need connection information on every node in a link, if it is connected
    # to at least two nodes in the same opportunity.
    unique_links = set()

    for opportunity in opportunities:
        print('new op', dt.now())
        kn = opportunity.get_kg_ids()
        print('',len(kn))
        seen = set()
        for n in kn:
            print(' ',len(nodes_to_links[n]))
            for l in  nodes_to_links[n]:
                tl = tuple(l)
                if tl in seen:
                    unique_links.add(tl)
                else:
                    seen.add(tl)
        print('','end',dt.now())


    unique_link_nodes = set()
    for a,b,c in unique_links:
        unique_link_nodes.add(a)

    onum = 0
    for opportunity in opportunities:
        logger.debug('Starting new opportunity')
        print(f'opp {onum} of {len(opportunities)}')
        onum += 1

        nodes = opportunity.get_kg_ids() #this is the list of curies that can be in the given spot
        qg_id = opportunity.get_qg_id()
        stype = opportunity.get_qg_semantic_type()

        print ('get enriched links')
        enriched_links = get_enriched_links(nodes, stype, nodes_to_links)
        print ('got enriched links')

        logger.info(f'{len(enriched_links)} enriched links discovered.')

        #For the moment, we're only going to return an arbitrarily small number of enrichments
        # It's POC, really you'd like to include many of these.  But we don't want
        # to end up with more answers than we started with, so we need to parameterize, and
        # that's more work that we can do later.
        #(enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset) )
        for i,link in enumerate(enriched_links):
            if i > len(nodes):
                break
            best_enrich_p = link[0]
            best_grouping = link[7]
            #I don't think this is right
            #best_enrichments = list(filter(lambda x: (x[0] == best_enrich_p) and x[7] == best_grouping,enriched_links))
            best_enrichments = [link] #?
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
                patch.add_extra_node(newcurie, e[8], edge_type=etype, newnode_is=nni)
            patches.append(patch)
        logger.debug('end of opportunity')

    logger.info('All opportunities processed.')

    return patches

def get_shared_links(nodes, stype, nodes_type_list: dict):
    """Return the intersection of the superclasses of every node in nodes"""
    rm = RobokopMessenger()
    links_to_nodes = defaultdict(set)
    for node in nodes:
        logger.debug(f'start get_links_for({node}, {stype})')
        links = rm.get_links_for(node, stype, nodes_type_list)
        logger.debug('end get_links_for()')

        for link in links:
            links_to_nodes[link].add(node)
    nodes_to_links = defaultdict(list)
    for link,nodes in links_to_nodes.items():
        if len(nodes) > 1:
            nodes_to_links[frozenset(nodes)].append(link)

    return nodes_to_links

def get_enriched_links(nodes, semantic_type, nodes_to_links,pcut=1e-6):
    logger.info (f'{len(nodes)} enriched node links to process.')

    # Get the most enriched connected node for a group of nodes.
    logger.debug ('start get_shared_links()')

    ret_nodes_type_list: dict = {}
    nodes_type_list: dict = {}

    #nodeset_to_links = get_shared_links(nodes, semantic_type, nodes_type_list)
    links_to_nodes = defaultdict(list)
    for node in nodes:
        for link in nodes_to_links[node]:
            links_to_nodes[tuple(link)].append(node)
    nodeset_to_links = defaultdict(list)
    for link,snodes in links_to_nodes.items():
        if len(snodes) > 1:
            nodeset_to_links[frozenset(snodes)].append(link)
    logger.debug ('end get_shared_links()')

    logger.debug(f'{len(nodeset_to_links)} nodeset links discovered.')

    rm = RobokopMessenger()
    results = []

    logger.info(f'{len(nodeset_to_links.items())} possible shared links discovered.')

    typeredis = redis.Redis(host='localhost', port=6379, db=1)
    for nodeset, possible_links in nodeset_to_links.items():
        enriched = []
        for newcurie,predicate,is_source in possible_links:
            # The hypergeometric distribution models drawing objects from a bin.
            # M is the total number of objects (nodes) ,
            # n is total number of Type I objects (nodes with that property).
            # The random variate represents the number of Type I objects in N drawn
            #  without replacement from the total population (len curies).

            x = len(nodeset)  # draws with the property

            total_node_count = get_total_node_count(semantic_type)

            # total_node_count = 6000000 #not sure this is the right number. Scales overall p-values.
            # Note that is_source is from the point of view of the input nodes, not newcurie

            newcurie_is_source = not is_source

            # logger.debug (f'start get_hit_node_count({newcurie}, {predicate}, {newcurie_is_source}, {semantic_type})')
            n = rm.get_hit_node_count(newcurie, predicate, newcurie_is_source, semantic_type)
            # logger.debug (f'end get_hit_node_count() = {n}, start get_hit_nodecount_old()')
            # o = rm.get_hit_nodecount_old(newcurie, predicate, newcurie_is_source, semantic_type)

            # if n != o:
            #     logger.info (f'New and old node count mismatch for ({newcurie}, {predicate}, {newcurie_is_source}, {semantic_type}: n:{n}, o:{o}')

            ndraws = len(nodes)

            enrichp = hypergeom.sf(x - 1, total_node_count, n, ndraws)

            if enrichp < pcut:
                nodetypestring = typeredis.get(newcurie)
                node_types = ast.literal_eval(nodetypestring.decode())
                enriched.append((enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset, node_types))
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
