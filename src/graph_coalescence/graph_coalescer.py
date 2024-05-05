from collections import defaultdict
from scipy.stats import hypergeom, poisson, binom, norm
from src.components import PropertyPatch, PropertyPatch_query
from src.util import LoggingUtil
import logging
import os
import redis
import json
import ast
import itertools
import orjson

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
    p = typeredis.pipeline(transaction=False)
    return p


def coalesce_by_graph(opportunities, mode="coalesce", predicates_to_exclude=[], pvalue_threshold=None, result_length = None):
    """
    Given opportunities for coalescence, potentially turn each into patches that can be applied to an answer
    patch = [qg_id of the node that is being replaced, curies (kg_ids) in the new combined set, props for the new curies,
    qg_id of the edges being removed/combined, answers being collapsed]

    result_length determines if we want more answers than we started with, so we need to parameterize.
    """
    patches = []

    logger.info(f'Start of processing. {len(opportunities)} opportunities discovered.')

    # Multiple opportunities are going to use the same nodes.  In one random (large) example where there are about
    # 2k opportunities, there are a total of 577 unique nodes, but with repeats, we'd end up calling messenger 3650
    # times.  So instead, we will unique the nodes here, call messenger once each, and then pull from that
    # collected set of info.
    allnodes = opportunities.get('qg_curies') if mode =="query" else create_node_to_type(opportunities)

    nodes_to_links = create_nodes_to_links(allnodes)

    # #There will be nodes we can't enrich b/c they're not in our db.  Remove those from our opps, and remove redundant/empty opps
    if mode == 'query':
        _, nodes_indices, unique_link_nodes, unique_links = filter_opportunities_and_unify(opportunities, nodes_to_links)
    else:
        opportunities = filter_opportunities(opportunities, nodes_to_links)
        unique_link_nodes, unique_links = uniquify_links(nodes_to_links, opportunities)
        # unique_link_nodes: bringing all the nodes that lookup results in allnodes maps through nodes_to_links as a set

    #We need to handle symmetric links
    #NB This is already handled in the create_nodes_to_link()
    # new_unique_links = set()
    # for ul in unique_links:
    #     if "biolink:related_to" in ul[1]:
    #         new_unique_links.add( (ul[0], ul[1], not ul[2], ul[3]) )
    # unique_links.update(new_unique_links)
    lcounts = get_link_counts(unique_links)
    nodetypedict = get_node_types(unique_link_nodes)
    nodenamedict = get_node_names(unique_link_nodes)

    provs = get_provs(nodes_to_links)

    total_node_counts = get_total_node_counts(set([k for k in allnodes.values()])) if mode =='query' else get_total_node_counts(set([o.get_qg_semantic_type() for o in opportunities]))

    onum = 0
    # sffile=open('sfcalls.txt','w')
    # In a test from test_bigs, we can see that we call sf 1.46M times.  But, we only call with 250k unique parametersets
    # so we're gonna cache those
    sf_cache = {}

    direction = {True: 'biolink:object', False: 'biolink:subject'}
    if not isinstance(opportunities, list):
        otype = opportunities.get('answer_type', None)
        q_predicates = list(opportunities.get('answer_edge', {}).values())[0]
        opportunities = [opportunities]

    for opportunity in opportunities:
        logger.debug('Starting new opportunity')
        onum += 1
        nodes = list(allnodes.keys()) if mode =='query' else opportunity.get_kg_ids()  # this is the list of curies that can be in the given spot
        qg_id = opportunity.get('question_id', '') if mode =='query' else opportunity.get_qg_id()
        stype = opportunity.get('question_type', '') if mode =='query' else opportunity.get_qg_semantic_type()

        if mode =='query':
            enriched_links = get_enriched_links_4_query(nodes, stype, nodes_to_links, lcounts, sf_cache, nodetypedict,
                                                 total_node_counts, q_predicates, otype)
            curies_types = get_node_types(nodes)
            curies_names = get_node_names(nodes)
            max_ret = 1000


        else:
            enriched_links = get_enriched_links(nodes, stype, nodes_to_links, lcounts, sf_cache, nodetypedict,
                                            total_node_counts, predicates_to_exclude=predicates_to_exclude,
                                            pvalue_threshold=pvalue_threshold)
            max_ret = len(nodes) if mode=='coalesce' else 100

        logger.info(f'{len(enriched_links)} enriched links discovered.')

        # For the moment, we're only going to return an arbitrarily small number of enrichments
        # It's POC, really you'd like to include many of these.  But we don't want
        # to end up with more answers than we started with, so we need to parameterize, and
        # that's more work that we can do later.
        processed_links = 0
        for i in range(len(enriched_links)):
            link = enriched_links[i]
            best_enrich_node = link[1]
            # We do not want (triangle) enrichment to point to the same lookup node
            # Eg MONDO:001 - treats -> PUBCHEM.COMPOUND:0001 - treats -> MONDO:001
            if mode == 'infer' and enrich_equal_qnode(opportunity.answer_hash, best_enrich_node):
                continue
            if not result_length and processed_links >= max_ret:
                    break
            if result_length and result_length > 0 and processed_links >= result_length:
                    break
            processed_links += 1
            # Extract the pvalue and the set of chemical nodes that mapped the enriched link tuples
            best_enrich_p = link[0]
            enrich_direction = direction.get(link[3])
            best_grouping = link[7]
            if mode == 'query':
                best_grouping_types = {curie: curies_types[curie] for curie in best_grouping}
                best_grouping_names = {curie: curies_names[curie] for curie in best_grouping}

            attributes = []

            attributes.append({'attribute_type_id': 'biolink:supporting_study_method_type',
                               'value': 'graph_enrichment'})

            attributes.append({'attribute_type_id': 'biolink:p_value',
                               'value': best_enrich_p})

            attributes.append({'attribute_type_id': 'biolink:supporting_study_cohort',
                               'value': qg_id})

            attributes.append({'attribute_type_id': enrich_direction,
                               'value': best_enrich_node})

            for key, value in json.loads(link[2]).items():
                attributes.append({'attribute_type_id': 'biolink:' + key,
                                   'value': value})

            newprops = {'attributes': attributes}

            if mode == "query":
                patch = PropertyPatch_query(qg_id, best_grouping, best_grouping_types, best_grouping_names, newprops,
                                       nodes_indices)
            else:
                patch = PropertyPatch(qg_id, best_grouping, newprops, opportunity.get_answer_indices())
            provkeys = []
            for e in [link]:
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
            # pprovs = {pk: provs[pk] for pk in provkeys }
            pprovs = {}
            for pk in provkeys:
                pk = pk if pk in provs else get_edge_symmetric(pk)
                pprovs[pk] = provs[pk]

            patch.add_provenance(pprovs)
            patches.append(patch)

        logger.debug('end of opportunity')

    logger.info('All opportunities processed.')

    return patches


def get_node_types(unique_link_nodes):
    # p = get_redis_pipeline(1)
    nodetypedict = {}
    with get_redis_pipeline(1) as p:
        for ncg in grouper(2000, unique_link_nodes):
            for newcurie in ncg:
                p.get(newcurie)
            all_typestrings = p.execute()
            for newcurie, nodetypestring in zip(ncg, all_typestrings):
                node_types = ast.literal_eval(nodetypestring.decode())
                nodetypedict[newcurie] = node_types
    return nodetypedict

def get_node_names(unique_link_nodes):
    # p = get_redis_pipeline(3)
    nodenames = {}
    with get_redis_pipeline(3) as p:
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
    # p = get_redis_pipeline(2)
    lcounts = {}
    with get_redis_pipeline(2) as p:
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

def check_prov_value_type(value):
    if isinstance(value, list):
        val = ','.join(value)
    else:
        val = value
    # I noticed some values are lists eg. ['infores:sri-reference-kg']
    # This function coerce such to string
    # Also, the newer pydantic accepts 'primary_knowledge_source' instead of 'biolink:primary_knowledge_source' in the old
    return val.replace('biolink:', '')
def get_edge_symmetric(edge):
    subject, b = edge.split('{')
    edge_predicate, obj = b.split('}')
    edge_predicate = '{' + edge_predicate + '}'
    return f'{obj.lstrip()} {edge_predicate} {subject.rstrip()}'
def get_provs(n2l):
    # Now we are going to hit redis to get the provenances for all of the links.
    # our unique_links are the keys
    # Convert n2l to edges
    def process_prov(prov_data):
        if isinstance(prov_data, (str, bytes)):
            prov_data = orjson.loads(prov_data)
        return [{'resource_id': check_prov_value_type(v), 'resource_role': check_prov_value_type(k)} for k, v in
                prov_data.items()]

    edges = [f'{n1} {link[1]} {link[0]}' if link[2] else f'{link[0]} {link[1]} {n1}' for n1, ll in n2l.items() for link
             in ll]


    prov = {}

    # now get the prov for those edges
    with get_redis_pipeline(4) as p:
        for edgegroup in grouper(1000, edges):
            for edge in edgegroup:
                p.get(edge)
            ns = p.execute()
            symmetric_edges = []
            for edge, n in zip(edgegroup, ns):
                # Convert the svelte key-value attribute into a fat trapi-style attribute
                if not n:
                    symmetric_edges.append(get_edge_symmetric(edge))
                else:
                    prov[edge] = process_prov(n)
                #This is cheating.  It's to make up for the fact that we added in inverted edges for
                # related to, but the prov doesn't know about it. This is not a long term fix, it's a hack
                # for the prototype and must be fixed. FIXED!!!
            if symmetric_edges:
                for sym_edge in symmetric_edges:
                    p.get(sym_edge)
                sym_ns = p.execute()
                for sym_edge, sn in zip(symmetric_edges, sym_ns):
                    if sn:
                        prov[sym_edge] = process_prov(sn)
                    else:
                        prov[sym_edge] = [{}]
                        logger.info(f'{sym_edge} not exist!')
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
        io += 1
        kn = opportunity.get_kg_ids()
        seen = set()
        for n in kn:
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
    return unique_link_nodes, unique_links

def create_nodes_to_links(allnodes):
    # p = get_redis_pipeline(0)
    # Create a dict from node->links by looking up in redis.  Each link is a potential node to add.
    # This is across all opportunities as well
    # Could pipeline
    #Noticed some qualifiers are have either but not both
    # eg ['UniProtKB:P81908', '{"object_aspect_qualifier": "activity", "predicate": "biolink:affects"}', True]
    #  VS['UniProtKB:P81908', '{"object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}', True]
    standard_qualifiers = {"object_aspect_qualifier", "object_direction_qualifier"}
    nodes_to_links = {}
    with get_redis_pipeline(0) as p:
        for group in grouper(1000, allnodes.keys()):
            for node in group:
                p.get(node)
            linkstrings = p.execute()
            for node, linkstring in zip(group, linkstrings):
                if linkstring is None:
                    links = []
                else:
                    links = orjson.loads(linkstring)
                        ## Redundant edges with only object_aspect_qualifier but no object_direction
                        # [lstring for lstring in orjson.loads(linkstring) if standard_qualifiers.issubset(set(orjson.loads(lstring[1]).keys())) or
                        # not any(element in set(orjson.loads(lstring[1]).keys()) for element in standard_qualifiers)]
                    # this is a bit hacky.  If we're pulling in redundant, then high level symmetric predicates
                    # have been assigned one direction only. We're going to invert them as well to allow matching
                newlinks = []
                for link in links:
                    # Note that this should really be done for any symmetric predicate.
                    # or fixed at the graph level.
                    # related_to_at is getting dropped at the point of calculating pvaue so why not drop it now?
                    if "biolink:related_to" in link[1] and "biolink:related_to_at" not in link[1]:
                        newlinks.append([link[0], link[1], not link[2]])
                # links  # = list( filter (lambda l: ast.literal_eval(l[1])["predicate"] not in bad_predicates, links))
                # links = list( filter (lambda l: ast.literal_eval(l[1])["predicate"] not in bad_predicates, links))
                links += newlinks
                nodes_to_links[node] = links
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

def filter_opportunities_and_unify(opportunities, nodes_to_links):
    unique_links = set()
    unique_link_nodes = set()
    kn = set(opportunities['qg_curies'].keys())
    # These will be the nodes that we actually have links for
    link_nodes = set(filter(lambda x: len(nodes_to_links[x]), kn))
    new_nodes_to_links = {node: (nodes_to_links[node]) for node in link_nodes}
    nodes_indices = [list(new_nodes_to_links.keys()).index(node) for node in new_nodes_to_links]
    seen = set()
    for n in kn:
        for l in nodes_to_links[n]:
            # The link as defined uses the input node as is_source, but the lookup into redis uses the
            # linked node as the is_source, so gotta flip it
            lplus = l + [opportunities['qg_curies'].get(n)]
            lplus[2] = not lplus[2]
            tl = tuple(lplus)
            if tl not in seen:
                unique_links.add(tl)
                unique_link_nodes.add(tl[0])
            else:
                seen.add(tl)

    return new_nodes_to_links, nodes_indices, unique_link_nodes, unique_links

def enrich_equal_qnode(qnode_hash, best_enrich_node):
    for _, val in qnode_hash:
        if best_enrich_node in val:
            return True
    return False

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
                       predicates_to_exclude=[],
                       pvalue_threshold=None):
    logger.info(f'{len(nodes)} enriched node links to process.')

    predicates_to_exclude = ["biolink:related_to_at_instance_level", "biolink:related_to_at_concept_level"] + predicates_to_exclude

    #These are trash curies that we never want to see
    blocklist = ["HP:0000118", "MONDO:0000001", "MONDO:0700096", "UMLS:C1333305", "CHEBI:24431",
                 "CHEBI:23367", "CHEBI:33579", "CHEBI:36357", "CHEBI:33675", "CHEBI:33302", "CHEBI:33304",
                 "CHEBI:33582", "CHEBI:25806", "CHEBI:50860", "CHEBI:51143", "CHEBI:32988", "CHEBI:33285",
                 "CHEBI:33256", "CHEBI:36962", "CHEBI:35352", "CHEBI:36963", "CHEBI:25367", "CHEBI:72695",
                 "CHEBI:33595", "CHEBI:33832", "CHEBI:37577", "CHEBI:24532", "CHEBI:5686", "NCBITaxon:9606"]


    # Use the default pcut as the enrichment p-value threshold if no threshold is given
    pcut = 1e-6 if not pvalue_threshold else pvalue_threshold

    # Get the most enriched connected node for a group of nodes.
    logger.debug('start get_shared_links()')

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

    results = []

    logger.info(f'{len(nodeset_to_links.items())} possible shared links discovered.')

    for nodeset, possible_links in nodeset_to_links.items():
        enriched = []
        for ix, (newcurie, predicate, is_source) in enumerate(possible_links):
            # For each tuple: ('HP:0001907', 'biolink:treats', True)
            # The hypergeometric distribution models drawing objects from a bin.
            # M is the total number of objects (nodes) ,
            # n is total number of Type I objects (nodes with that property).
            # The random variate represents the number of Type I objects in N drawn
            #  without replacement from the total population (len curies).
            # Fail fast on these. Don't do a bunch of calculations that we're just going to throw away.
            if json.loads(predicate)["predicate"] in predicates_to_exclude:
                continue
            if newcurie in blocklist:
                continue

            # length of the set of chemicals that mapped to the tuple
            x = len(nodeset)  # draws with the property

            # TODO Not sure why this is arbitrary number
            total_node_count = total_node_counts[semantic_type]
            # total_node_count = 1000000

            # total_node_count = 6000000 #not sure this is the right number. Scales overall p-values.
            # Note that is_source is from the point of view of the input nodes, not newcurie
            newcurie_is_source = not is_source

            # logger.debug (f'start get_hit_node_count({newcurie}, {predicate}, {newcurie_is_source}, {semantic_type})')
            # n = rm.get_hit_node_count(newcurie, predicate, newcurie_is_source, semantic_type)
            n = lcounts[(newcurie, predicate, newcurie_is_source, semantic_type)]
            if "biolink:related_to" in predicate:
                try:
                    n += lcounts[(newcurie, predicate, not newcurie_is_source, semantic_type)]
                except:
                    # no reverse edges
                    pass

            if x > 0  and n == 0:
                logger.info(f"x == {x}; n == 0??? : {newcurie} {predicate} {newcurie_is_source} {semantic_type} ")

                # print(f"x == {x}; n == 0???")
                # print(newcurie, predicate, newcurie_is_source, semantic_type)
                continue

            ndraws = len(nodes)

            # I only care about things that occur more than by chance, not less than by chance
            if x < n * ndraws / total_node_count:
                logger.info(f"x == {x} < {n * ndraws / total_node_count} : {newcurie} {predicate} {newcurie_is_source} {semantic_type} occur less than by chance")

                # print(f"x == {x} < {n * ndraws / total_node_count}")
                # print(newcurie, predicate, newcurie_is_source, semantic_type)
                # print("occur less than by chance")
                # print()
                continue

            # The correct distribution to calculate here is the hypergeometric.  However, it's the slowest.
            # For most cases, it is ok to approximate it.  There are multiple levels of approximation as described
            # here: https://riskwiki.vosesoftware.com/ApproximationstotheHypergeometricdistribution.php
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

                # if predicates_to_exclude:
                #     if json.loads(predicate)['predicate'] not in predicates_to_exclude:
                #         enriched.append(
                #             (enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset, node_types))
                #         # if pred_exclude is used to filter, the results looks cleaner like 1000+ else 2000+ results
                # else:
                enriched.append((enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset, node_types))

        if len(enriched) > 0:
            results += enriched

    results.sort()

    logger.debug('end get_enriched_links()')
    return results

def get_enriched_links_4_query(nodes, semantic_type, nodes_to_links, lcounts, sfcache, typecache, total_node_counts, q_predicates, answer_type = None):
    logger.info(f'{len(nodes)} enriched node links to process.')

    # Get the most enriched connected node for a group of nodes.
    logger.debug('start get_shared_links()')
    predicates_to_exclude = ["biolink:related_to_at_instance_level",
                             "biolink:related_to_at_concept_level"]

    # These are trash curies that we never want to see
    blocklist = ["HP:0000118", "MONDO:0000001", "MONDO:0700096", "UMLS:C1333305", "CHEBI:24431",
                 "CHEBI:23367", "CHEBI:33579", "CHEBI:36357", "CHEBI:33675", "CHEBI:33302", "CHEBI:33304",
                 "CHEBI:33582", "CHEBI:25806", "CHEBI:50860", "CHEBI:51143", "CHEBI:32988", "CHEBI:33285",
                 "CHEBI:33256", "CHEBI:36962", "CHEBI:35352", "CHEBI:36963", "CHEBI:25367", "CHEBI:72695",
                 "CHEBI:33595", "CHEBI:33832", "CHEBI:37577", "CHEBI:24532", "CHEBI:5686", "NCBITaxon:9606"]

    links_to_nodes = defaultdict(list)
    for node in nodes:
        for link in nodes_to_links[node]:
            links_to_nodes[tuple(link)].append(node)
    nodeset_to_links = defaultdict(list)
    for link, snodes in links_to_nodes.items():
        nodeset_to_links[frozenset(snodes)].append(link)
    logger.debug('end get_shared_links()')

    logger.debug(f'{len(nodeset_to_links)} nodeset links discovered.')

    results = []

    logger.info(f'{len(nodeset_to_links.items())} possible shared links discovered.')

    for nodeset, possible_links in nodeset_to_links.items():
        enriched = []

        for ix, (newcurie, predicate, is_source) in enumerate(possible_links):
            # For each tuple: ('HP:0001907', 'biolink:treats', True)
            # The hypergeometric distribution models drawing objects from a bin.
            # M is the total number of objects (nodes) ,
            # n is total number of Type I objects (nodes with that property).
            # The random variate represents the number of Type I objects in N drawn
            #  without replacement from the total population (len curies).
            pred=json.loads(predicate)
            # if not any(set(p.items()).issubset(set(json.loads(predicate).items())) for p in q_predicates):
            if pred['predicate'] not in q_predicates['predicate']:
                continue
            if q_predicates.get('object_aspect_qualifier', ''):
                if q_predicates.get('object_aspect_qualifier') != pred.get('object_aspect_qualifier', ''):
                    continue
            if q_predicates.get('object_direction_qualifier', ''):
                if q_predicates.get('object_direction_qualifier') != pred.get('object_direction_qualifier', ''):
                    continue

            if pred["predicate"] in predicates_to_exclude:
                continue
            if newcurie in blocklist:
                continue
            # length of the set of chemicals that mapped to the tuple
            x = len(nodeset)  # draws with the property

            total_node_count = total_node_counts[semantic_type]

            newcurie_is_source = not is_source

            n = lcounts[(newcurie, predicate, newcurie_is_source, semantic_type)]

            if "biolink:related_to" in predicate:
                try:
                    n += lcounts[(newcurie, predicate, not newcurie_is_source, semantic_type)]
                except:
                    # no reverse edges
                    pass

            if x > 0  and n == 0:
                logger.info(f"x == {x}; n == 0??? : {newcurie} {predicate} {newcurie_is_source} {semantic_type} ")
                # print(newcurie, predicate, newcurie_is_source, semantic_type)
                continue
                # return []

            ndraws = len(nodes)

            # I only care about things that occur more than by chance, not less than by chance
            if x < n * ndraws / total_node_count:
                logger.info(f"x == {x} < {n * ndraws / total_node_count} : {newcurie} {predicate} {newcurie_is_source} {semantic_type} occur less than by chance")
                # print(newcurie, predicate, newcurie_is_source, semantic_type)
                # print("occur less than by chance")
                # print()
                continue

            # The correct distribution to calculate here is the hypergeometric.  However, it's the slowest.
            # For most cases, it is ok to approximate it.  There are multiple levels of approximation as described
            # here: https://riskwiki.vosesoftware.com/ApproximationstotheHypergeometricdistribution.php
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

            # if enrichp < pcut:
            # get the real labels/types of the enriched node
            node_types = typecache[newcurie]

            if not answer_type or (answer_type and answer_type in set(node_types)):
                enriched.append(
                    (enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset, node_types))

        if len(enriched) > 0:
            results += enriched

    results.sort()

    logger.debug('end get_enriched_links()')
    return results

def get_total_node_counts(semantic_types):
    # p = get_redis_pipeline(5)
    counts = {}
    # needs to be first so that counts will fill it first
    semantic_list = ['biolink:NamedThing'] + list(semantic_types)
    with get_redis_pipeline(5) as p:
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
