from collections import defaultdict
from scipy.stats import hypergeom, poisson, binom, norm
from src.components import Enrichment
from src.util import LoggingUtil
import logging
import os
import redis
import json
import ast
import itertools
import orjson
import bmt

this_dir = os.path.dirname(os.path.realpath(__file__))

logger = LoggingUtil.init_logging('graph_coalescer', level=logging.WARNING, format='long', logFilePath=this_dir + '/')
tk = bmt.Toolkit()

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

def filter_links_by_predicate(nodes_to_links, predicate_constraints, predicate_constraint_style):
    """Filter out links that don't meet the predicate constraints
    predicate constraints are just in the form that qualified predicates are described in the links e.g.
    {"predicate": "biolink:related_to", "object_aspect_qualifier": "activity"}
    Matching the constraint means that all keys and values match between the link and the constraint
    If predicate_constraint style is "include" then only links that match one constraint will be kept
    If predicate_constraint style is "exclude" then only links that match no constraints will be kept
    """
    if len(predicate_constraints) == 0:
        return nodes_to_links
    new_nodes_to_links = {}
    for node, links in nodes_to_links.items():
        new_links = []
        for link in links:
            # link_dict = json.loads(link[1])
            if predicate_constraint_style == "include":
                if any(constraint in link[1] for constraint in predicate_constraints):
                    new_links.append(link)
            elif predicate_constraint_style == "exclude":
                if not any(constraint in link[1] for constraint in predicate_constraints):
                    new_links.append(link)
        new_nodes_to_links[node] = new_links
    return new_nodes_to_links

def filter_links_by_node_type(nodes_to_links, node_constraints, link_node_types):
    """Filter out links that don't meet the node constraints
    node constraints is a list of acceptable node types for the returned nodes.  The node type of the other node
    in the links is used to determine if the link is kept.  Fortunately, link_node_types holds all of the superclasses
    of the node type, so we can just check if the link node type is in the set of acceptable types.

    Also, we want to filter out links that end up with block-list nodes
    """
    # These are trash curies that we never want to see
    blocklist = set(["HP:0000118", "MONDO:0000001", "MONDO:0700096", "UMLS:C1333305", "CHEBI:24431",
                 "CHEBI:23367", "CHEBI:33579", "CHEBI:36357", "CHEBI:33675", "CHEBI:33302", "CHEBI:33304",
                 "CHEBI:33582", "CHEBI:25806", "CHEBI:50860", "CHEBI:51143", "CHEBI:32988", "CHEBI:33285",
                 "CHEBI:33256", "CHEBI:36962", "CHEBI:35352", "CHEBI:36963", "CHEBI:25367", "CHEBI:72695",
                 "CHEBI:33595", "CHEBI:33832", "CHEBI:37577", "CHEBI:24532", "CHEBI:5686", "NCBITaxon:9606"])

    #Collect the accepted types, which are any subclass of what gets passed into node constraints.
    # We're going to special case named thing - if that's in there, we just bypass all the type checks.
    accept_all_types = ( "biolink:NamedThing" in node_constraints )

    new_nodes_to_links = {}
    for node, links in nodes_to_links.items():
        new_links = []
        for link in links:
            othernode = link[0]
            if othernode in blocklist:
                continue
            if accept_all_types:
                new_links.append(link)
            else:
                # we have 2 lists: node constraints and link_node_types_othernode.  We want to see if there is any overlap
                # between the two lists.  If there is, then we want to keep the link.
                accepted_types = set(node_constraints) & set(link_node_types[othernode])
                if len(accepted_types) > 0:
                    new_links.append(link)
        new_nodes_to_links[node] = new_links

    return new_nodes_to_links


def coalesce_by_graph(input_ids, input_node_type,
                      node_constraints = ["biolink:NamedThing"], predicate_constraints=[], predicate_constraint_style = "exclude",
                      pvalue_threshold=None, result_length = None):
    """
    Given a list of input_ids, find nodes that are enriched.
    Return a list of Enrichment objects describing each enrichment.
    We don't want to muck this up with a bunch of TRAPI handling, this is purely about finding the
    enriched nodes.
    node_contraints and predicate_constraints can be used to limit the search.   Node constraints can be used
    to only allow the new node to be of a certain type.  Predicate constraints can be used to only allow certain
    predicates to be used in the enrichment or to exclude certain predicates. predicate_constraint_style can set to
    either "include" or "exclude". If "include" then only links that exactly match one constraint pattern are included.
    If "exclude" then any link matching an "exclude" constraint is excluded.
    Predicates should be of the form:
    {"predicate": "biolink:related_to", "object_aspect_qualifier": "activity", "constraint": "include|exclude"}
    By including or not including these constraints, coalesce_by_graph can be used by either an MCQ query or EDGAR.
    result_length determines if we want more answers than we started with, so we need to parameterize.
    """
    logger.info(f'Start of processing.')

    # Get the links for all the input nodes
    nodes_to_links = create_nodes_to_links(input_ids)
    # Filter the links by predicates.  This is how we are handling the input predicate for query and the
    # excluded predicates for EDGAR.
    nodes_to_links = filter_links_by_predicate(nodes_to_links, predicate_constraints, predicate_constraint_style)
    # Find the unique link nodes and get their types
    unique_link_nodes, unique_links = uniquify_links(nodes_to_links, input_node_type)
    nodetypedict = get_node_types(unique_link_nodes)
    # Now that we know the types, get rid of any links that don't meet the node constraints.
    # For EDGAR, the default node constraint of NamedThing will let everything be used.
    nodes_to_links = filter_links_by_node_type(nodes_to_links, node_constraints, nodetypedict)
    # Having filtered some links out, we need to recompute the unique links
    unique_link_nodes, unique_links = uniquify_links(nodes_to_links, input_node_type)
    lcounts = get_link_counts(unique_links)


    total_node_counts = get_total_node_counts(input_node_type)

    # In a test from test_bigs, we can see that we call sf 1.46M times.  But, we only call with 250k unique parametersets
    # so we're gonna cache those
    sf_cache = {}

    #direction = {True: 'biolink:object', False: 'biolink:subject'}

    enriched_links = get_enriched_links(input_ids, input_node_type, nodes_to_links, lcounts, sf_cache, nodetypedict,
                                        total_node_counts)

    if pvalue_threshold:
        enriched_links = [link for link in enriched_links if link.p_value < pvalue_threshold]
    if result_length:
        enriched_links = enriched_links[:result_length]

    augment_enrichments(enriched_links, nodetypedict)

    return enriched_links

def augment_enrichments(enriched_links, nodetypes):
    """Having found the set of enrichments we want to return, make sure that each enrichment has the node name and the node type."""
    enriched_curies = set([link.enriched_node.new_curie for link in enriched_links])
    nodenamedict = get_node_names(enriched_curies)
    for enrichment in enriched_links:
        enrichment.add_extra_node_name(nodenamedict)
    add_provs(enriched_links)


def add_provs(enrichments):
    # Now we are going to hit redis to get the provenances for all of the links.
    # our unique_links are the keys
    # Convert n2l to edges
    def process_prov(prov_data):
        if isinstance(prov_data, (str, bytes)):
            prov_data = orjson.loads(prov_data)
        return [{'resource_id': check_prov_value_type(v), 'resource_role': check_prov_value_type(k)} for k, v in
                prov_data.items()]

    edges = []
    for enrichment in enrichments:
        new_edges = enrichment.get_prov_links()
        edges += new_edges

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
                # This is cheating.  It's to make up for the fact that we added in inverted edges for
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
    for enrichment in enrichments:
        enrichment.add_provenance(prov)


def leftovers():
    ### All of this stuff was in the original coalesce_by_graph, but I'm not sure if it's needed
    # some of it seems to be used by EDGAR, but most of it seems pretty crufty. We're going to move the provenance
    # stuff out of here, because it's not really about the enrichment, it's about the TRAPI response.
    for q in range(0):
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

def uniquify_links(nodes_to_links, input_type):
    # A link might occur for multiple nodes and across different opportunities
    # Create the total unique set of links
    unique_links = set()
    unique_link_nodes = set()
    for n in nodes_to_links:
        for l in nodes_to_links[n]:
            # The link as defined uses the input node as is_source, but the lookup into redis uses the
            # linked node as the is_source, so gotta flip it
            lplus = l + [input_type]
            lplus[2] = not lplus[2]
            tl = tuple(lplus)
            unique_links.add(tl)
            unique_link_nodes.add(tl[0])
    return unique_link_nodes, unique_links

def create_nodes_to_links(allnodes, params_predicate = ""):
    """Given a list of nodes identifiers, pull all their links"""
    # Create a dict from node->links by looking up in redis.
    #Noticed some qualifiers are have either but not both
    # eg ['UniProtKB:P81908', '{"object_aspect_qualifier": "activity", "predicate": "biolink:affects"}', True]
    #  VS['UniProtKB:P81908', '{"object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}', True]
    nodes_to_links = {}

    with get_redis_pipeline(0) as p:
        for group in grouper(1000, allnodes):
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
                    link_predicate = orjson.loads(link[1])["predicate"]
                    if params_predicate:
                        # For lookup operation
                        if link_predicate != params_predicate:
                            continue
                        newlinks.append(link[0])
                    else:
                        # Note that this should really be done for any symmetric predicate.
                        # or fixed at the graph level.
                        # related_to_at is getting dropped at the point of calculating pvaue so why not drop it now?
                        # if "biolink:related_to" in link[1] and "biolink:related_to_at" not in link[1]:
                        if tk.get_element(link_predicate)["symmetric"]:
                            newlinks.append([link[0], link[1], not link[2]])

                # links  # = list( filter (lambda l: ast.literal_eval(l[1])["predicate"] not in bad_predicates, links))
                # links = list( filter (lambda l: ast.literal_eval(l[1])["predicate"] not in bad_predicates, links))
                if params_predicate:
                    nodes_to_links = newlinks
                else:
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

def get_enriched_links(nodes, semantic_type, nodes_to_links, lcounts, sfcache, typecache, total_node_counts):
    """Given a set of nodes and the links that they share, as well as some counts, return the enrichments based
    on the links.
    If you want to restrict the answers, then you filter nodes_to_links ahead of time.'
    The enrichments are of the form
    (enrichp, newcurie, predicate, is_source, ndraws, n, total_node_count, nodeset, node_types)
    and are sorted so that the lowest p-values (best enrichment) are first.  The enrichp is the pvalue of the enrichment.
    """
    logger.info(f'{len(nodes)} enriched node links to process.')

    # Get the most enriched connected node for a group of nodes.
    logger.debug('start get_shared_links()')

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
            # length of the set of chemicals that mapped to the tuple
            x = len(nodeset)  # draws with the property

            total_node_count = total_node_counts[semantic_type]

            newcurie_is_source = not is_source

            n = lcounts[(newcurie, predicate, newcurie_is_source, semantic_type)]

            #TODO: Ola handle symmetry
            # if "biolink:related_to" in predicate:
            if tk.get_element(orjson.loads(predicate)["predicate"])["symmetric"]:
                try:
                    n += lcounts[(newcurie, predicate, not newcurie_is_source, semantic_type)]
                except:
                    # no reverse edges
                    pass

            if x > 0  and n == 0:
                logger.info(f"x == {x}; n == 0??? : {newcurie} {predicate} {newcurie_is_source} {semantic_type} ")
                continue

            ndraws = len(nodes)

            # I only care about things that occur more than by chance, not less than by chance
            if x < n * ndraws / total_node_count:
                logger.info(f"x == {x} < {n * ndraws / total_node_count} : {newcurie} {predicate} {newcurie_is_source} {semantic_type} occur less than by chance")
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
                sfcache[args] = poisson.sf(x - 1, n * ndraws / total_node_count)

            # Enrichment pvalue
            enrichp = sfcache[args]

            # get the real labels/types of the enriched node
            node_types = typecache[newcurie]

            enrichment = Enrichment(enrichp, newcurie, predicate, newcurie_is_source, ndraws, n, total_node_count, nodeset, node_types)
            enriched.append( enrichment )

        if len(enriched) > 0:
            results += enriched

    results.sort(key=lambda x: x.p_value)

    logger.debug('end get_enriched_links()')
    return results

def get_total_node_counts(semantic_type):
    counts = {}
    # needs to be first so that counts will fill it first
    semantic_list = ['biolink:NamedThing',semantic_type]
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
