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
# os.path.insert(0, "/Users/olawumiolasunkanmi/Library/CloudStorage/OneDrive-UniversityofNorthCarolinaatChapelHill/FALL2022/BACKUPS/ARAGORN/AnswerCoalesce/")

this_dir = os.path.dirname(os.path.realpath(__file__))

logger = LoggingUtil.init_logging('graph_coalescer', level=logging.WARNING, format='long', logFilePath=this_dir + '/')

# These are predicates that we have decided are too messy for graph coalescer to use
#
# bad_predicates = ['biolink:causes_adverse_event']


def grouper(n, iterable):
    it = iter(iterable)
    while True:
        chunk = tuple(itertools.islice(it, n))
        if not chunk:
            break
        yield chunk


def get_redis_pipeline(dbnum):
    # "redis_host": "localhost",
    # "redis_port": 6379,
    # "redis_password": "",
    jpath = os.path.join(os.path.abspath(os.path.dirname(__file__)), '..', '..', 'config.json')
    with open(jpath, 'r') as inf:
        conf = json.load(inf)
    if 'redis_password' in conf and len(conf['redis_password']) > 0:
        typeredis = redis.Redis(host=conf['redis_host'], port=int(conf['redis_port']), db=dbnum,
                                password=conf['redis_password'])
    else:
        typeredis = redis.Redis(host=conf['redis_host'], port=int(conf['redis_port']), db=dbnum)
    p = typeredis.pipeline()
    return p


def coalesce_by_graph(opportunities, predicates_to_exclude=None, coalesce_threshold=None):
    """
    Given opportunities for coalescence, potentially turn each into patches that can be applied to an answer
    patch = [qg_id of the node that is being replaced, curies (kg_ids) in the new combined set, props for the new curies,
    qg_id of the edges being removed/combined, answers being collapsed]
    """
    patches = []

    logger.info(f'Start of processing. {len(opportunities)} opportunities discovered.')

    # Multiple opportunities are going to use the same nodes.  In one random (large) example where there are about
    # 2k opportunities, there are a total of 577 unique nodes, but with repeats, we'd end up calling messenger 3650
    # times.  So instead, we will unique the nodes here, call messenger once each, and then pull from that
    # collected set of info.

    allnodes = create_node_to_type(opportunities)

    nodes_to_links = create_nodes_to_links(allnodes)

    "eg 'PUBCHEM.COMPOUND:60809' maps 112 [['UniProtKB:P14416', 'biolink:interacts_with', True], ['MONDO:0002039', 'biolink:ameliorates', True]," \
    "['NCBIGene:1133', 'biolink:activity_increased_by', False], ['CHEBI:24431', 'biolink:subclass_of', True],"

    # #There will be nodes we can't enrich b/c they're not in our db.  Remove those from our opps, and remove redundant/empty opps
    opportunities = filter_opportunities(opportunities, nodes_to_links)

    unique_link_nodes, unique_links = uniquify_links(nodes_to_links, opportunities)
    # unique_link_nodes: bringing all the nodes that each chemical in allnodes maps through nodes_to_links as a set
    # unique_links:

    lcounts = get_link_counts(unique_links)
    nodetypedict = get_node_types(unique_link_nodes)
    nodenamedict = get_node_names(unique_link_nodes)

    # provs: One chemical to many enrich nodes
    provs = get_provs(nodes_to_links)

    total_node_counts = get_total_node_counts(set([o.get_qg_semantic_type() for o in opportunities]))

    onum = 0
    # sffile=open('sfcalls.txt','w')
    # In a test from test_bigs, we can see that we call sf 1.46M times.  But, we only call with 250k unique parametersets
    # so we're gonna cache those
    sf_cache = {}
    for opportunity in opportunities:

        logger.debug('Starting new opportunity')
        onum += 1

        nodes = opportunity.get_kg_ids()  # this is the list of curies that can be in the given spot

        qg_id = opportunity.get_qg_id()
        stype = opportunity.get_qg_semantic_type()


        enriched_links = get_enriched_links(nodes, stype, nodes_to_links, lcounts, sf_cache, nodetypedict,
                                            total_node_counts, predicates_to_exclude=predicates_to_exclude)

        logger.info(f'{len(enriched_links)} enriched links discovered.')

        # For the moment, we're only going to return an arbitrarily small number of enrichments
        # It's POC, really you'd like to include many of these.  But we don't want
        # to end up with more answers than we started with, so we need to parameterize, and
        # that's more work that we can do later.
        # (enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset) )
        for i in range(len(enriched_links)):
            link = enriched_links[i]
            if coalesce_threshold:
                threshold = coalesce_threshold
            else:
                threshold = len(nodes)
            if i >= threshold:
                break
            # for the first 78 enriched result,
            # Extract the pvalue and the set of chemical nodes that mapped the enriched link tuples
            best_enrich_p = link[0]
            best_grouping = link[7]
            best_enrich_predicate = json.loads(link[2])
            # I don't think this is right
            # best_enrichments = list(filter(lambda x: (x[0] == best_enrich_p) and x[7] == best_grouping,enriched_links))
            best_enrichments = [link]  # ?
            # print(best_enrichments)
            attributes = []

            attributes.append({'original_attribute_name': 'coalescence_method',
                               'attribute_type_id': 'biolink:has_attribute',
                               'value': 'graph_enrichment',
                               'value_type_id': 'EDAM:operation_0004'})

            attributes.append({'original_attribute_name': 'p_value',
                               'attribute_type_id': 'biolink:has_numeric_value',
                               'value': best_enrich_p,
                               'value_type_id': 'EDAM:data_1669'})

            attributes.append({'original_attribute_name': 'enriched_nodes',
                               'attribute_type_id': 'biolink:has_attribute',
                               'value': [x[1] for x in best_enrichments],
                               'value_type_id': 'EDAM:data_0006'})

            attributes.append({'original_attribute_name': 'predicates',
                               'attribute_type_id': 'biolink:has_attribute',
                               'value': [best_enrich_predicate],
                               'value_type_id': 'EDAM:data_0006'})

            newprops = {'attributes': attributes}

            patch = PropertyPatch(qg_id, best_grouping, newprops, opportunity.get_answer_indices())
            provkeys = []
            for e in best_enrichments:
                newcurie = e[1]
                # etype is a string rep of a dict.  We leave it as such because we use it as a key but
                # we also need to take it apart
                edge_key = e[2]
                if e[3]:
                    nni = 'target'
                    provkeys += [f'{bg} {edge_key} {newcurie}' for bg in best_grouping]
                else:
                    nni = 'source'
                    provkeys += [f'{newcurie} {edge_key} {bg}' for bg in best_grouping]
                # Need to get the right node type.
                patch.add_extra_node(newcurie, e[8], edge_pred_and_qual=edge_key, newnode_is=nni,
                                     newnode_name=nodenamedict[newcurie])
            pprovs = {pk: provs[pk] for pk in provkeys}
            patch.add_provenance(pprovs)
            # print(patch)
            patches.append(patch)
        logger.debug('end of opportunity')

    logger.info('All opportunities processed.')

    return patches


def get_node_types(unique_link_nodes):
    p = get_redis_pipeline(1)
    nodetypedict = {}
    for ncg in grouper(2000, unique_link_nodes):
        # print(ncg)
        # for ncg in (unique_link_nodes):
        for newcurie in ncg:
            p.get(newcurie)
        all_typestrings = p.execute()
        for newcurie, nodetypestring in zip(ncg, all_typestrings):
            node_types = ast.literal_eval(nodetypestring.decode())
            nodetypedict[newcurie] = node_types
    return nodetypedict


def get_node_names(unique_link_nodes):
    p = get_redis_pipeline(3)
    nodenames = {}
    for ncg in grouper(1000, unique_link_nodes):
        for newcurie in ncg:
            p.get(newcurie)
        all_names = p.execute()
        for newcurie, name in zip(ncg, all_names):
            try:
                nodenames[newcurie] = name.decode('UTF-8')
            except:
                nodenames[newcurie] = ''
    return nodenames


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
                # this can happen becuase we're inferring the category type from the qgraph.  But if we have 0 we have 0
                lcounts[ul] = 0
    return lcounts


def get_provs(n2l):
    # Now we are going to hit redis to get the provenances for all of the links.
    # our unique_links are the keys
    # Convert n2l to edges
    edges = []
    for n1, ll in n2l.items():
        for link in ll:
            if link[2]:
                edges.append(f'{n1} {link[1]} {link[0]}')
            else:
                edges.append(f'{link[0]} {link[1]} {n1}')
    # now get the prov for those edges
    p = get_redis_pipeline(4)
    prov = {}
    for edgegroup in grouper(1000, edges):
        for edge in edgegroup:
            p.get(edge)
        ns = p.execute()
        for edge, n in zip(edgegroup, ns):
            if n is None:
                print(edge)
            # Convert the svelte key-value attribute into a fat trapi-style attribute
            prov[edge] = [{'attribute_type_id': k, 'value': v} for k, v in json.loads(n).items()]
    return prov


def filter_opportunities(opportunities, nodes_to_links):
    new_opportunities = []
    for opportunity in opportunities:
        kn = opportunity.get_kg_ids()
        # These will be the nodes that we actually have links for
        newkn = list(filter(lambda x: len(nodes_to_links[x]), kn))
        newopp = opportunity.filter(newkn)
        if newopp is not None:
            new_opportunities.append(opportunity)
    return new_opportunities


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
                links = []
            else:
                links = json.loads(linkstring)
            links  # = list( filter (lambda l: ast.literal_eval(l[1])["predicate"] not in bad_predicates, links))
            # links = list( filter (lambda l: ast.literal_eval(l[1])["predicate"] not in bad_predicates, links))
            nodes_to_links[node] = links
    # print(len(nodes_to_links))
    return nodes_to_links


def create_node_to_type(opportunities):
    # Create a dict from node->type(node) for all nodes in every opportunity
    allnodes = {}
    for opportunity in opportunities:
        kn = opportunity.get_kg_ids()
        stype = opportunity.get_qg_semantic_type()
        for node in kn:
            allnodes[node] = stype
    return allnodes


# def get_shared_links(nodes, stype, nodes_type_list: dict):
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

def get_enriched_links(nodes, semantic_type, nodes_to_links, lcounts, sfcache, typecache, total_node_counts,
                       predicates_to_exclude=None, pcut=1e-6):
    logger.info(f'{len(nodes)} enriched node links to process.')

    # Get the most enriched connected node for a group of nodes.
    logger.debug('start get_shared_links()')

    ret_nodes_type_list: dict = {}
    nodes_type_list: dict = {}

    # nodeset_to_links = get_shared_links(nodes, semantic_type, nodes_type_list)
    links_to_nodes = defaultdict(list)
    for node in nodes:
        for link in nodes_to_links[node]:
            links_to_nodes[tuple(link)].append(node)
    nodeset_to_links = defaultdict(list)
    for link, snodes in links_to_nodes.items():

        # if the enriched node connects to more than one lookup chemical
        if len(snodes) > 1:
            nodeset_to_links[frozenset(snodes)].append(link)
    logger.debug('end get_shared_links()')

    logger.debug(f'{len(nodeset_to_links)} nodeset links discovered.')

    # rm = RobokopMessenger()
    results = []

    logger.info(f'{len(nodeset_to_links.items())} possible shared links discovered.')

    for nodeset, possible_links in nodeset_to_links.items():
        # nodeset: set of chemicals
        # possible links: list of possible enriched tuple
        # eg frozenset({'MESH:D006495', 'PUBCHEM.COMPOUND:445154', 'PUBCHEM.COMPOUND:3108'}): [('HP:0001907', 'biolink:treats', True)]
        enriched = []

        for ix, (newcurie, predicate, is_source) in enumerate(possible_links):
            # For each tuple: ('HP:0001907', 'biolink:treats', True)
            # The hypergeometric distribution models drawing objects from a bin.
            # M is the total number of objects (nodes) ,
            # n is total number of Type I objects (nodes with that property).
            # The random variate represents the number of Type I objects in N drawn
            #  without replacement from the total population (len curies).

            # length of the set of chemicals that mapped to the tuple
            x = len(nodeset)  # draws with the property

            # total_node_count = get_total_node_count(semantic_type)
            total_node_count = total_node_counts[semantic_type]

            # total_node_count = 6000000 #not sure this is the right number. Scales overall p-values.
            # Note that is_source is from the point of view of the input nodes, not newcurie

            newcurie_is_source = not is_source

            # logger.debug (f'start get_hit_node_count({newcurie}, {predicate}, {newcurie_is_source}, {semantic_type})')
            # n = rm.get_hit_node_count(newcurie, predicate, newcurie_is_source, semantic_type)
            n = lcounts[(newcurie, predicate, newcurie_is_source, semantic_type)]
            # logger.debug (f'end get_hit_node_count() = {n}, start get_hit_nodecount_old()')
            # o = rm.get_hit_nodecount_old(newcurie, predicate, newcurie_is_source, semantic_type)

            # if n != o:
            #     logger.info (f'New and old node count mismatch for ({newcurie}, {predicate}, {newcurie_is_source}, {semantic_type}: n:{n}, o:{o}')

            ndraws = len(nodes)

            # The correct distribution to calculate here is the hypergeometric.  However, it's the slowest.
            # For most cases, it is ok to approximate it.  There are multiple levels of approximation as described
            # here: https://www.vosesoftware.com/riskwiki/ApproximationstotheHypergeometricdistribution.php
            # Ive tested and each approximation is faster, while the quality decreases.
            # Norm is a bad approximation for this data
            # the other three are fine.  Poisson very occassionaly is off by a factor of two or so, but that's not
            # terribly important here.  It's also almost 2x faster than the hypergeometric.
            # So we're going to use poisson, but if we have problems with it we should drop back to binom rather than hypergeom

            # tuple -> (enrichnode,edge, typemapped)

            args = (x - 1, total_node_count, n, ndraws)
            if args not in sfcache:
                # sfcache[args] = hypersf(x - 1, total_node_count, n, ndraws)
                # p_binom = binomsf(x-1,ndraws,n/total_node_count)
                # p_pois = poissonsf(x-1,n * ndraws / total_node_count)
                # p_norm = normsf(x-1,n*ndraws/total_node_count, math.sqrt((ndraws*n)*(total_node_count-n))/total_node_count)
                sfcache[args] = poisson.sf(x - 1, n * ndraws / total_node_count)
                # sf_out.write(f'{x-1}\t{total_node_count}\t{n}\t{ndraws}\t{sfcache[args]}\t{p_binom}\t{p_pois}\t{p_norm}\n')

            # Enrichment pvalue
            enrichp = sfcache[args]

            if enrichp < pcut:
                # get the real labels/types of the enriched node
                node_types = typecache[newcurie]

                if predicates_to_exclude:
                    if json.loads(predicate)['predicate'] not in predicates_to_exclude:
                        enriched.append(
                            (enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset, node_types))
                             # if pred_exclude is used to filter, the results looks cleaner like 1000+ else 2000+ results
                else:
                    enriched.append(
                        (enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset, node_types))

        if len(enriched) > 0:
            results += enriched

    results.sort()

    logger.debug('end get_enriched_links()')
    return results


def get_total_node_counts(semantic_types):
    p = get_redis_pipeline(5)
    counts = {}
    # needs to be first so that counts will fill it first
    semantic_list = ['biolink:NamedThing'] + list(semantic_types)
    for st in semantic_list:
        p.get(st)
    allcounts = p.execute()
    for st, stc in zip(semantic_list, allcounts):
        if stc is not None:
            counts[st] = float(stc)
        elif not stc and 'biolink:NamedThing' in counts:
            # If we can't find a type, just use the biggest number.  We could improve this a bit
            # by fiddling around in the biolink model and using a more closely related superclass.
            counts[st] = counts['biolink:NamedThing']
    return counts


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
    stype2counts = {'biolink:Disease': 84000,
                    'biolink:Gene': 329000,
                    'biolink:Protein': 329000,
                    'biolink:PhenotypicFeature': 74000,
                    'biolink:DiseaseOrPhenotypicFeature': 174000,
                    'biolink:ChemicalSubstance': 214000,
                    'biolink:ChemicalEntity': 214000,
                    'biolink:AnatomicalEntity': 112000,
                    'biolink:Cell': 40000,
                    'biolink:BiologicalProcess': 133000,
                    'biolink:MolecularActivity': 86000,
                    'biolink:BiologicalProcessOrActivity': 148000}
    if semantic_type in stype2counts:
        return stype2counts[semantic_type]
    # Give up and return the total number of nodes
    return 6000000
