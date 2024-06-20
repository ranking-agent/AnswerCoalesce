from collections import defaultdict
from scipy.stats import hypergeom, poisson, binom, norm
from src.components import Enrichment
from src.util import LoggingUtil
from itertools import zip_longest
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
    Note tht the links are constructed by taking that dictionary and running json.dumps(sort_keys=True) on it.
    So we will need to do the same for our constraints
    Matching the constraint means that all keys and values match between the link and the constraint
    If predicate_constraint style is "include" then only links that match one constraint will be kept
    If predicate_constraint style is "exclude" then only links that match no constraints will be kept
    """
    if len(predicate_constraints) == 0:
        return nodes_to_links
    string_constraints = [json.dumps(constraint, sort_keys=True) for constraint in predicate_constraints]
    new_nodes_to_links = {}
    for node, links in nodes_to_links.items():
        new_links = []
        for link in links:
            # link_dict = json.loads(link[1])
            if predicate_constraint_style == "include":
                if any(constraint in link[1] for constraint in string_constraints):
                    new_links.append(link)
            elif predicate_constraint_style == "exclude":
                if not any(constraint in link[1] for constraint in string_constraints):
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
            if (isinstance(link,list) or isinstance(link,tuple)):
                othernode = link[0]
            else:
                othernode = link
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


async def coalesce_by_graph(input_ids, input_node_type,
                             node_constraints=None, predicate_constraints=None, predicate_constraint_style="exclude",
                             pvalue_threshold=None, result_length=None, filter_predicate_hierarchies=False):
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
    filter_predicate_hierarchies mainly in edgar to exclude/add symmetric edges inline
    (in create_node_to_link) and filter predicate hierarchies in get_enriched_link enrichment_results
    """
    logger.info(f'Start of processing.')
    if node_constraints is None:
        node_constraints = ["biolink:NamedThing"]
    if predicate_constraints is None:
        predicate_constraints = []
    # Get the links for all the input nodes
    nodes_to_links = create_nodes_to_links(input_ids)
    # We don't want to do the exlusion here because we want to do it after we've found the enrichments
    # But we can narrow down by the inclusion constraints
    if predicate_constraint_style == "include":
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


    enriched_links = get_enriched_links(input_ids, input_node_type, nodes_to_links, lcounts, sf_cache, nodetypedict,
                                        total_node_counts, filter_predicate_hierarchies)

    if pvalue_threshold:
        enriched_links = [link for link in enriched_links if link.p_value < pvalue_threshold]
    if result_length:
        enriched_links = enriched_links[:result_length]

    if predicate_constraints:
        enriched_links = [link for link in enriched_links if orjson.loads(link.predicate).get("predicate") not in predicate_constraints]

    augment_enrichments(enriched_links, nodetypedict)

    return enriched_links

def augment_enrichments(enriched_links, nodetypes):
    """Having found the set of enrichments we want to return, make sure that each enrichment has the node name and the node type."""
    enriched_curies = set([link.enriched_node.new_curie for link in enriched_links])
    nodenamedict = get_node_names(enriched_curies)
    for enrichment in enriched_links:
        enrichment.add_extra_node_name_and_label(nodenamedict, nodetypes)
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
            inverted_to_original = {}
            for edge, n in zip(edgegroup, ns):
                # Convert the svelte key-value attribute into a fat trapi-style attribute
                if not n:
                    inverted = get_edge_symmetric(edge)
                    symmetric_edges.append(inverted)
                    inverted_to_original[inverted] = edge
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
                        #This has to be for the original edge, otherwise we don't find it later
                        prov[inverted_to_original[sym_edge]] = process_prov(sn)
                    else:
                        prov[sym_edge] = [{}]
                        logger.info(f'{sym_edge} not exist!')
    for enrichment in enrichments:
        enrichment.add_provenance(prov)


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
                s = str(ul)
                p.get(s)
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
    #This is for caching the edge types as symmetric or not because we are parsing json every time.
    predicate_is_symmetric = {}
    for n in nodes_to_links:
        for l in nodes_to_links[n]:
            # The link as defined uses the input node as is_source, but the lookup into redis uses the
            # linked node as the is_source, so gotta flip it.   But there is a gross wrinkle here - if the
            # link is symmetric, then we want the link to always be "True" (Don't flip if it already says True)
            lplus = l + [input_type]
            if (l[1] not in predicate_is_symmetric):
                predicate_is_symmetric[l[1]] = predicate_string_is_symmetric(l[1])
            if predicate_is_symmetric[l[1]]:
                lplus[2] = True
            else:
                lplus[2] = not lplus[2]
            tl = tuple(lplus)
            unique_links.add(tl)
            unique_link_nodes.add(tl[0])
    return unique_link_nodes, unique_links


def predicate_string_is_symmetric(predicate: str) -> bool:
    """Check if a predicate string is symmetric. The predicate here is the whole qualified mess as a string"""
    bare_predicate = orjson.loads(predicate)["predicate"]
    return tk.get_element(bare_predicate)["symmetric"]


def create_nodes_to_links(allnodes, param_predicates = []):
    """Given a list of nodes identifiers, pull all their links
    If param_predicates is not empty, it should be a list of the same length as allnodes.
    It's use is in EDGAR where create_nodes_to_links is used in the final lookup step. In that case,
    we might be trying to run a bunch of rules at the same time and so the predicates will differ node to node.

    Note that we used to add inverted symmetric links to the results, but we no longer do that."""
    # Create a dict from node->links by looking up in redis.
    #Noticed some qualifiers are have either but not both
    # eg ['UniProtKB:P81908', '{"object_aspect_qualifier": "activity", "predicate": "biolink:affects"}', True]
    #  VS['UniProtKB:P81908', '{"object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}', True]
    nodes_to_links = {}

    with get_redis_pipeline(0) as p:
        for group, param_predicate in zip_longest(grouper(1000, allnodes), param_predicates):
            if not group:
                continue
            for node in group:
                p.get(node)
            linkstrings = p.execute()
            for node, linkstring in zip(group, linkstrings):
                if linkstring is None:
                    links = []
                else:
                    links = orjson.loads(linkstring)
                newlinks = []
                for link in links:
                    if param_predicate:
                        # For lookup operation
                        if link[1] == param_predicate:
                            newlinks.append(link[0])
                if param_predicate:
                    nodes_to_links[node] = list(set(newlinks))
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


def get_enriched_links(nodes, semantic_type, nodes_to_links, lcounts, sfcache, typecache, total_node_counts, filter_predicate_hierarchies = False):
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

            # We only want to do this if the predicate is symmetric
            #if tk.get_element(orjson.loads(predicate)["predicate"])["symmetric"]:
            if predicate_string_is_symmetric(predicate):
                newcurie_is_source = True
            else:
                newcurie_is_source = not is_source

            n = lcounts[(newcurie, predicate, newcurie_is_source, semantic_type)]

            if x > 0 and n == 0:
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

            #enrichment = Enrichment(enrichp, newcurie, orjson.loads(predicate), newcurie_is_source, ndraws, n, total_node_count, nodeset, node_types)
            enrichment = Enrichment(enrichp, newcurie, predicate, newcurie_is_source, ndraws, n, total_node_count, nodeset, node_types)
            enriched.append(enrichment)

        if len(enriched) > 0:
            results += enriched

    if filter_predicate_hierarchies:
        results = filter_result_hierarchies(results)

    results.sort(key=lambda x: x.p_value)

    logger.debug('end get_enriched_links()')

    return results


def filter_result_hierarchies(results):
    enrichment_group_dict = {}
    for i, result in enumerate(results):
        # Group results by enriched_node
        enrichment_group_dict.setdefault(result.enriched_node.new_curie, []).append(result)

    # Now filter by predicate hierarchies
    new_results = process_enrichment_group(enrichment_group_dict)

    return new_results


def process_enrichment_group(enrichment_group_dict):
    new_results = set()

    for enriched_node, enriched_results in enrichment_group_dict.items():

        # if enriched_node == "HP:0001337":
        #     #Copy the details to test_graph_coalesce
        #     details = [(enriched_result.p_value, enriched_result.enriched_node.new_curie, enriched_result.predicate, enriched_result.is_source, enriched_result.counts[0], enriched_result.counts[1], enriched_result.counts[2], enriched_result.linked_curies, enriched_result.enriched_node.newnode_type[0]) for enriched_result in enriched_results]
        #     A = 'Stop Over Here!!'
        #     print("WAIT!!!!! I wanna see the result")

        if len(enriched_results) == 1:
            new_results.update(enriched_results)
        else:
            # Re_group by p_value:
            p_value_group_dict = {}
            for enriched_result in enriched_results:
                p_value_group_dict.setdefault(enriched_result.p_value, []).append(enriched_result)

            # For each group, find the most specific predicates in each p_value group and put in specific results
            specific_results = get_specific_results(p_value_group_dict)

            # Pick the most specific in the specific results

            if len(specific_results) == 1:
                new_results.update(specific_results)
                continue
            # Else we pick the best representative of an enrichment node from the combined group result by min pvalue
            # OR Hierarchy again, Most especially if we can get further specificity
            # Filtering by predicate hierarchy and p_value scoring
            children_to_parent = children_parent_mapping(specific_results)
            pvalue_dict = {specific_result.predicate: specific_result.p_value for
                           specific_result in specific_results}
            most_preferred = streamline_children_to_parent(children_to_parent, pvalue_dict)

            for specific_result in specific_results:
                pred = specific_result.predicate
                if pred in most_preferred:
                    new_results.add(specific_result)
    return list(new_results)


def streamline_children_to_parent(children_to_parent, pvalues):
    """
    Given,
         pvalue_dict = {
                'biolink:contributes_to': 5.62677119993497e-16,
                'biolink:related_to': 6.984714344422767e-26,
                'biolink:treats_or_applied_or_studied_to_treat': 2.688166355839941e-06,
                'biolink:has_adverse_event': 2.8008696832786763e-17,
                'biolink:causes': 3.9591314521010225e-08
        }

    And child-parent dependencies between the predicates, we want to choose the one with best predicate in each case

        children_to_parent_dict = {
            'biolink:causes': {'biolink:contributes_to', 'biolink:related_to'},
            'biolink:contributes_to': {'biolink:related_to'},
            'biolink:has_adverse_event': {'biolink:related_to'}
        }

    since `biolink:related_to` has the best pvalue compared with the key,value pair in each item

    Then our results returns:
            {'biolink:related_to'}

    """
    streamlined_set = set()
    items_to_remove = set()

    # Let's gather all unique predicates from children_to_parent and their children
    all_keys = set(children_to_parent.keys())
    for children in children_to_parent.values():
        all_keys.update(children)

    # Get the p-values
    pvalue_lookup = {key: pvalues.get(key, float('inf')) for key in all_keys}

    # Streamline the children_to_parent dictionary
    for child, parents in list(children_to_parent.items()):
        if parents:
            # Select the element with the smallest p-value
            best_element = min([child] + list(parents), key=lambda x: pvalue_lookup[x])
            streamlined_set.add(best_element)
            # items_to_remove.add(child)
            continue
        # If a child has no parents, it needs to be compared with others
        candidates = set()
        for other_child, other_parents in children_to_parent.items():
            candidates.add(other_child)
            candidates.update(other_parents)
        candidates = candidates - items_to_remove
        grouping = group_by_predicate(candidates).get(orjson.loads(child).get("predicate"), [])
        if len(grouping) == 1 and child == grouping[0]:
            streamlined_set.add(child)
            items_to_remove.add(child)
        if len(grouping) > 1:
            best_element = min(grouping, key=lambda x: pvalue_lookup[x])
            streamlined_set.add(best_element)
            items_to_remove.update(grouping)

    # # Remove items marked for deletion, if it exist
    # for item in items_to_remove:
    #     del children_to_parent[item]

    if len(streamlined_set) == 1:
        return streamlined_set

    # Check to be sure the set aren't dependent on each other
    if len(streamlined_set) == 2:
        streamlist = list(streamlined_set)
        if streamlist[0] in children_to_parent.get(streamlist[1], []):
            # 0 is the parent but return the one with least pvalue
            if pvalues.get(streamlist[0]) < pvalues.get(streamlist[1]):
                return {streamlist[0]}
            else:
                return {streamlist[1]}
        elif streamlist[1] in children_to_parent.get(streamlist[0], []):
            # 1 is the parent but return the one with least pvalue
            if pvalues.get(streamlist[1]) < pvalues.get(streamlist[0]):
                return {streamlist[1]}
            else:
                return {streamlist[0]}
        else:
            streamlist0_pred_only = orjson.loads(streamlist[0]).get('predicate')
            streamlist1_pred_only = orjson.loads(streamlist[1]).get('predicate')
            # For the last time:
            if streamlist0_pred_only in get_ancestors(streamlist1_pred_only):
                if pvalues.get(streamlist[0]) < pvalues.get(streamlist[1]):
                    return {streamlist[0]}
                else:
                    return {streamlist[1]}
            if streamlist1_pred_only in get_ancestors(streamlist0_pred_only):
                if pvalues.get(streamlist[1]) < pvalues.get(streamlist[0]):
                    return {streamlist[1]}
                else:
                    return {streamlist[0]}
            # None is the parent of the other
            return streamlined_set

    if len(streamlined_set) > 2:
        new_children_to_parent = children_parent_mapping(list(streamlined_set))
        if new_children_to_parent == children_to_parent:
            return streamlined_set
        return streamline_children_to_parent(new_children_to_parent, pvalues)


def group_by_predicate(items):
    """
    groups a list of predicate strings by the predicate only
    """
    grouped_items = {}

    for item in items:
        parsed_item = json.loads(item)
        predicate = parsed_item.get('predicate')

        if predicate not in grouped_items:
            grouped_items[predicate] = []
        grouped_items[predicate].append(item)

    return grouped_items


def children_parent_mapping(specific_results):
    def merge_dict(d):
        """
        For each key-value pair, check if any of the values are keys in the dictionary.
        If they are, merge their value sets and mark the key for removal.
        """
        # Make a new dictionary to merge all the items results
        merged_dict = {key: set(values) for key, values in d.items()}

        merging_needed = True
        while merging_needed:
            merging_needed = False
            keys_to_remove = set()
            temp_dict = {}

            for key, values in merged_dict.items():
                # W need a temporary set to avoid modifying the original set during iteration
                new_values = set(values)
                for value in values:
                    if value in merged_dict:
                        # Merge the value's set into the new set
                        new_values.update(merged_dict[value])
                        # Mark the key for removal
                        keys_to_remove.add(value)
                        # Mark merging as needed
                        merging_needed = True

                temp_dict[key] = new_values

            # Let's update the merged dictionary with the temporary dictionary
            merged_dict.update(temp_dict)

            # Then remove the merged keys
            for key in keys_to_remove:
                if key in merged_dict:
                    del merged_dict[key]

        return merged_dict

    children_to_parent = {}

    current_predicate = specific_results[0] if isinstance(specific_results[0], str) else specific_results[0].predicate

    for j in range(1, len(specific_results)):
        next_predicate = specific_results[j] if isinstance(specific_results[j], str) else specific_results[j].predicate

        if orjson.loads(current_predicate).get("predicate") in get_ancestors(
                orjson.loads(next_predicate).get("predicate")):
            children_to_parent.setdefault(next_predicate, set()).add(current_predicate)

        elif orjson.loads(next_predicate).get("predicate") in get_ancestors(
                orjson.loads(current_predicate).get("predicate")):
            children_to_parent.setdefault(current_predicate, set()).add(next_predicate)

        current_predicate = next_predicate

    allowable_predicates = {specific_result if isinstance(specific_results[0], str) else specific_result.predicate for
                            specific_result in specific_results}

    # Case where there are some misses; we need to somehow figure out how to store it in the children_to_parent_dict
    for result in specific_results:
        pred = result if isinstance(result, str) else result.predicate
        if pred in children_to_parent:
            continue
        if any(pred in values for values in children_to_parent.values()):
            continue
        pred_ancestors = get_ancestors(orjson.loads(pred).get("predicate"))
        if pred_ancestors:
            pred_ancestors = allowable_predicates.intersection(
                set([json.dumps({"predicate": pred}) for pred in pred_ancestors]))
            children_to_parent[pred] = pred_ancestors
        else:
            pred_children = get_children(orjson.loads(pred).get("predicate"))
            if pred_children:
                pred_children = allowable_predicates.intersection(
                    set([json.dumps({"predicate": pred}) for pred in pred_ancestors]))
                for pred_child in pred_children:
                    if pred_child in children_to_parent:
                        children_to_parent.setdefault(pred_child, set()).add(pred)
            else:
                children_to_parent.setdefault(pred, set()).add(pred)

    return merge_dict(children_to_parent)


def is_child_in(child, parent, qualifier_enum):
    children = tk.get_permissible_value_children(parent, qualifier_enum) or []
    return child in children


def has_qualifier(predicate):
    qualifiers = {"object_aspect_qualifier", "object_direction_qualifier"}
    return any(q in predicate for q in qualifiers)


def get_ancestors(predicate):
    return tk.get_ancestors(predicate, formatted=True, reflexive=False)


def get_children(predicate):
    return tk.get_children(predicate, formatted=True)


def get_specific_results(pvalue_group_dict):
    """
    This function accepts:
        enrichment result grouped by pvalue, and most-likely, different predicates
        for instance:
                0.0001: [(enriched_node1, causes), (enriched_node1, contributes_to)]
                0.0002: [(enriched_node1, has_advert_event), (enriched_node1, affects)]
                0.0003: [(enriched_node1, treats_or_applied_or_studied_to_treat), (enriched_node1, treats)]
    to return specific list representative of enriched_node1:
                [(enriched_node1, causes),(enriched_node1, has_advert_event), (enriched_node1, treats)]

    NB: No scoring is performed since each group compared shares the same p_value
    """
    specific_results = []


    for results in pvalue_group_dict.values():
        if len(results) == 1:
            specific_results.extend(results)
            continue

        most_specific_result = results[0]

        for j in range(1, len(results)):
            result_i = most_specific_result
            result_j = results[j]

            pred_i = orjson.loads(result_i.predicate)
            pred_j = orjson.loads(result_j.predicate)

            if pred_i.get("predicate") == pred_j.get("predicate"):
                # Equal predicates? then lets dig further down to the qualifier
                if any("qualifier" in key for key in pred_i) or any("qualifier" in key for key in pred_j):
                    c_pred = pred_i
                    n_pred = pred_j

                    curr_qualifier = c_pred.get("object_aspect_qualifier") or c_pred.get("object_direction_qualifier")
                    next_qualifier = n_pred.get("object_aspect_qualifier") or n_pred.get("object_direction_qualifier")

                    if curr_qualifier and next_qualifier:
                        if curr_qualifier == next_qualifier:
                            if ("object_direction_qualifier" in c_pred) != ("object_direction_qualifier" in n_pred):
                                most_specific_result = result_i if "object_direction_qualifier" in c_pred else result_j

                        elif is_child_in(curr_qualifier, next_qualifier, 'GeneOrGeneProductOrChemicalEntityAspectEnum'):
                            most_specific_result = result_i

                        elif is_child_in(next_qualifier, curr_qualifier, 'GeneOrGeneProductOrChemicalEntityAspectEnum'):
                            most_specific_result = result_j

                    elif has_qualifier(c_pred) and not has_qualifier(n_pred):
                        most_specific_result = result_i

                    elif has_qualifier(n_pred) and not has_qualifier(c_pred):
                        most_specific_result = result_j

                else:
                    most_specific_result = results[0]

            else:
                top_ancestral_result = max([result_i, result_j], key=lambda result: len(
                    get_ancestors(orjson.loads(result.predicate).get("predicate"))))
                most_specific_result = top_ancestral_result

        specific_results.append(most_specific_result)

    return specific_results


def get_total_node_counts(semantic_type):
    counts = {}
    # needs to be first so that counts will fill it first
    semantic_list = ['biolink:NamedThing', semantic_type]
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


# def filter_qualified_predicate_hierarchy(specificgroup):
#     """
#     If we have a list of predicates either qualified or not, use this to return the most specfic prodicate
#
#     ['{"object_aspect_qualifier": "secretion", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}',
#        '{"object_aspect_qualifier": "expression", "object_direction_qualifier": "increased", "predicate": "biolink:affects"}',
#        '{"object_aspect_qualifier": "secretion", "predicate": "biolink:affects"}'
#     ]
#     gives
#
#     ['{"object_aspect_qualifier": "secretion", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}']
#
#     """
#
#     specific_predicates = set()
#
#     if len(specificgroup) == 1:
#         specific_predicates.update(specificgroup)
#
#     most_specific_group = specificgroup[0]
#
#     for j in range(1, len(specificgroup)):
#         result_i = most_specific_group
#         result_j = specificgroup[j]
#
#         pred_i = orjson.loads(result_i)
#         pred_j = orjson.loads(result_j)
#
#         if pred_i.get("predicate") == pred_j.get("predicate"):
#             # Equal predicates? then lets dig further down to the qualifier
#             if any("qualifier" in key for key in pred_i) or any("qualifier" in key for key in pred_j):
#                 c_pred = pred_i
#                 n_pred = pred_j
#
#                 curr_qualifier = c_pred.get("object_aspect_qualifier") or c_pred.get("object_direction_qualifier")
#                 next_qualifier = n_pred.get("object_aspect_qualifier") or n_pred.get("object_direction_qualifier")
#
#                 if curr_qualifier and next_qualifier:
#                     if curr_qualifier == next_qualifier:
#                         if ("object_direction_qualifier" in c_pred) != ("object_direction_qualifier" in n_pred):
#                             most_specific_group = result_i if "object_direction_qualifier" in c_pred else result_j
#
#                     elif is_child_in(curr_qualifier, next_qualifier, 'GeneOrGeneProductOrChemicalEntityAspectEnum'):
#                         most_specific_group = result_i
#                     elif is_child_in(next_qualifier, curr_qualifier, 'GeneOrGeneProductOrChemicalEntityAspectEnum'):
#                         most_specific_group = result_j
#                     else:
#                         # # Handle case where neither is a child of the other
#                         # specific_predicates.add(result_i)
#                         # specific_predicates.add(result_j)
#                         continue
#
#                 elif has_qualifier(c_pred) and not has_qualifier(n_pred):
#                     most_specific_group = result_i
#
#                 elif has_qualifier(n_pred) and not has_qualifier(c_pred):
#                     most_specific_group = result_j
#
#             else:
#                 most_specific_group = result_i
#         elif orjson.loads(result_i).get("predicate") in get_ancestors(orjson.loads(result_j).get("predicate")):
#             most_specific_group = result_j
#
#         elif orjson.loads(result_j).get("predicate") in get_ancestors(orjson.loads(result_i).get("predicate")):
#             most_specific_group = result_i
#         else:
#             top_ancestral_result = max([result_i, result_j],
#                                        key=lambda result: len(get_ancestors(orjson.loads(result).get("predicate"))))
#             most_specific_group = top_ancestral_result
#
#     specific_predicates.add(most_specific_group)
#
#     return specific_predicates