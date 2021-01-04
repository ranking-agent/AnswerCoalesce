from collections import defaultdict
from scipy.stats import hypergeom, poisson, binom, norm
from src.components import PropertyPatch
from src.util import LoggingUtil
import logging
import os
import redis
import json
import ast
import itertools


this_dir = os.path.dirname(os.path.realpath(__file__))

logger = LoggingUtil.init_logging('graph_coalescer', level=logging.WARNING, format='long', logFilePath=this_dir+'/')

def grouper(n, iterable):
    it = iter(iterable)
    while True:
        chunk = tuple(itertools.islice(it, n))
        if not chunk:
            break
        yield chunk

def get_redis_pipeline(dbnum):
    #"redis_host": "localhost",
    #"redis_port": 6379,
    #"redis_password": "",
    jpath = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..','..','config.json')
    with open(jpath,'r') as inf:
        conf = json.load(inf)
    if 'redis_password' in conf and len(conf['redis_password']) > 0:
        typeredis = redis.Redis(host=conf['redis_host'], port=int(conf['redis_port']), db=dbnum, password=conf['redis_password'])
    else:
        typeredis = redis.Redis(host=conf['redis_host'], port=int(conf['redis_port']), db=dbnum)
    p = typeredis.pipeline()
    return p


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

    allnodes = create_node_to_type(opportunities)
    nodes_to_links = create_nodes_to_links(allnodes)
    unique_link_nodes, unique_links = uniquify_links(nodes_to_links, opportunities)
    lcounts = get_link_counts(unique_links)
    nodetypedict = get_node_types(unique_link_nodes)

    onum = 0
    #sffile=open('sfcalls.txt','w')
    #In a test from test_bigs, we can see that we call sf 1.46M times.  But, we only call with 250k unique parametersets
    # so we're gonna cache those
    sf_cache = {}
    for opportunity in opportunities:
        logger.debug('Starting new opportunity')
        onum += 1

        nodes = opportunity.get_kg_ids() #this is the list of curies that can be in the given spot
        qg_id = opportunity.get_qg_id()
        stype = opportunity.get_qg_semantic_type()

        enriched_links = get_enriched_links(nodes, stype, nodes_to_links, lcounts,sf_cache,nodetypedict)

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
                #This is here because the current db are old style but we need the results newstyle.
                if not etype.startswith('biolink'):
                    etype = f'biolink:{etype}'
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


def get_node_types(unique_link_nodes):
    p = get_redis_pipeline(1)
    nodetypedict = {}
    for ncg in grouper(1000, unique_link_nodes):
        for newcurie in ncg:
            p.get(newcurie)
        all_typestrings = p.execute()
        for newcurie, nodetypestring in zip(ncg, all_typestrings):
            node_types = ast.literal_eval(nodetypestring.decode())
            nodetypedict[newcurie] = node_types
    return nodetypedict


def get_link_counts(unique_links):
    # Now we are going to hit redis to get the counts for all of the links.
    # our unique_links are the keys
    p = get_redis_pipeline(2)
    lcounts = {}
    for ulg in grouper(1000, unique_links):
        for ul in ulg:
            p.get(str(ul))
        ns = p.execute()
        for ul, n in zip(ulg, ns):
            try:
                lcounts[ul] = int(n)
            except:
                print('Failure')
                print(ul)
                raise('error')
    return lcounts


def uniquify_links(nodes_to_links, opportunities):
    # A link might occur for multiple nodes and across different opportunities
    # Create the total unique set of links
    unique_links = set()
    unique_link_nodes = set()
    io = 0
    for opportunity in opportunities:
        # print('new op', io, dt.now())
        io += 1
        kn = opportunity.get_kg_ids()
        # print('',len(kn))
        seen = set()
        for n in kn:
            # if len(nodes_to_links[n]) > 10000:
            #    print(' ',n,len(nodes_to_links[n]),opportunity.get_qg_semantic_type())
            for l in nodes_to_links[n]:
                # The link as defined uses the input node as is_source, but the lookup into redis uses the
                # linked node as the is_source, so gotta flip it
                lplus = l + [opportunity.get_qg_semantic_type()]
                lplus[2] = not lplus[2]
                tl = tuple(lplus)
                if tl in seen:
                    # if lplus[0] == 'NCBIGene:355':
                    #    print(io, tl)
                    unique_links.add(tl)
                    unique_link_nodes.add(tl[0])
                else:
                    seen.add(tl)
        # print('','end',dt.now())
    return unique_link_nodes, unique_links


def create_nodes_to_links(allnodes):
    p = get_redis_pipeline(0)
    # Create a dict from node->links by looking up in redis.  Each link is a potential node to add.
    # This is across all opportunities as well
    # Could pipeline
    nodes_to_links = {}
    for group in grouper(1000, allnodes.keys()):
        for node in group:
            p.get(node)
        linkstrings = p.execute()
        for node, linkstring in zip(group, linkstrings):
            if linkstring is None:
                print(node)
            if linkstring is None:
                links = []
            else:
                links = json.loads(linkstring)
            nodes_to_links[node] = links
    return nodes_to_links


import re
def create_node_to_type(opportunities):
    # Create a dict from node->type(node) for all nodes in every opportunity
    allnodes = {}
    for opportunity in opportunities:
        kn = opportunity.get_kg_ids()
        stype = opportunity.get_qg_semantic_type()
        #We're in a situation where there are databases using old style types but the input will be new style, and
        #for a moment we need to translate.  This will go away.
        if stype.startswith('biolink'):
            pascal = stype.split(':')[1]
            stype = re.sub(r'(?<!^)(?=[A-Z])', '_', pascal).lower()
        for node in kn:
            allnodes[node] = stype
    return allnodes


#def get_shared_links(nodes, stype, nodes_type_list: dict):
#    """Return the intersection of the superclasses of every node in nodes"""
#    rm = RobokopMessenger()
#    links_to_nodes = defaultdict(set)
#    for node in nodes:
#        logger.debug(f'start get_links_for({node}, {stype})')
#        links = rm.get_links_for(node, stype, nodes_type_list)
#        logger.debug('end get_links_for()')
#
#        for link in links:
#            links_to_nodes[link].add(node)
#    nodes_to_links = defaultdict(list)
#    for link,nodes in links_to_nodes.items():
#        if len(nodes) > 1:
#            nodes_to_links[frozenset(nodes)].append(link)
#
#    return nodes_to_links

def get_enriched_links(nodes, semantic_type, nodes_to_links,lcounts, sfcache, typecache, pcut=1e-6):
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

    #rm = RobokopMessenger()
    results = []

    logger.info(f'{len(nodeset_to_links.items())} possible shared links discovered.')

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
            #n = rm.get_hit_node_count(newcurie, predicate, newcurie_is_source, semantic_type)
            n = lcounts[ (newcurie, predicate, newcurie_is_source, semantic_type) ]
            # logger.debug (f'end get_hit_node_count() = {n}, start get_hit_nodecount_old()')
            # o = rm.get_hit_nodecount_old(newcurie, predicate, newcurie_is_source, semantic_type)

            # if n != o:
            #     logger.info (f'New and old node count mismatch for ({newcurie}, {predicate}, {newcurie_is_source}, {semantic_type}: n:{n}, o:{o}')

            ndraws = len(nodes)


            #The correct distribution to calculate here is the hypergeometric.  However, it's the slowest.
            # For most cases, it is ok to approximate it.  There are multiple levels of approximation as described
            # here: https://www.vosesoftware.com/riskwiki/ApproximationstotheHypergeometricdistribution.php
            # Ive tested and each approximation is faster, while the quality decreases.
            # Norm is a bad approximation for this data
            # the other three are fine.  Poisson very occassionaly is off by a factor of two or so, but that's not
            # terribly important here.  It's also almost 2x faster than the hypergeometric.
            # So we're going to use poisson, but if we have problems with it we should drop back to binom rather than hypergeom
            args = (x-1,total_node_count,n,ndraws)
            if args not in sfcache:
                #sfcache[args] = hypersf(x - 1, total_node_count, n, ndraws)
                #p_binom = binomsf(x-1,ndraws,n/total_node_count)
                #p_pois = poissonsf(x-1,n * ndraws / total_node_count)
                #p_norm = normsf(x-1,n*ndraws/total_node_count, math.sqrt((ndraws*n)*(total_node_count-n))/total_node_count)
                sfcache[args] =  poisson.sf(x-1,n * ndraws / total_node_count)
                #sf_out.write(f'{x-1}\t{total_node_count}\t{n}\t{ndraws}\t{sfcache[args]}\t{p_binom}\t{p_pois}\t{p_norm}\n')
            enrichp = sfcache[args]

            if enrichp < pcut:
                node_types = typecache[newcurie]
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
