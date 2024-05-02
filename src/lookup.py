from collections import defaultdict
from src.components import PropertyPatch, PropertyPatch_query
from src.util import LoggingUtil
import logging
from copy import deepcopy
import os, redis, json, ast, itertools, orjson, httpx, requests

this_dir = os.path.dirname(os.path.realpath(__file__))

logger = LoggingUtil.init_logging('lookup', level=logging.WARNING, format='long', logFilePath=this_dir + '/')



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
    jpath = os.path.join(os.path.abspath(os.path.dirname(__file__)), '', '..', 'config.json')
    with open(jpath, 'r') as inf:
        conf = json.load(inf)
    if 'redis_password' in conf and len(conf['redis_password']) > 0:
        typeredis = redis.Redis(host=conf['redis_host'], port=int(conf['redis_port']), db=dbnum,
                                password=conf['redis_password'])
    else:
        typeredis = redis.Redis(host=conf['redis_host'], port=int(conf['redis_port']), db=dbnum)
    p = typeredis.pipeline(transaction=False)
    return p


def get_node_types(unique_link_nodes):
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

def get_node_properties(unique_link_nodes, return_category_set):
    nodetypedict = get_node_types(unique_link_nodes)
    nodenamedict = get_node_names(unique_link_nodes)
    nodes = {}
    for node in unique_link_nodes:
        if return_category_set and return_category_set.intersection(nodetypedict[node]):
            nodes.update({node: {'name': nodenamedict[node], 'categories': nodetypedict[node], 'attributes': []}})
    return nodes

def get_provs(edges):
    # Now we are going to hit redis to get the provenances for all of the links.
    # our unique_links are the keys
    # Convert n2l to edges
    # we could reuse the function in Graph Coalesce, except that the condition below doesnt apply there:
        # if "infores:text-mining-provider-targeted" in n.decode('utf-8'):
        #     continue
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

    def process_prov(prov_data):
        if isinstance(prov_data, (str, bytes)):
            prov_data = orjson.loads(prov_data)
        return [{'resource_id': check_prov_value_type(v), 'resource_role': check_prov_value_type(k)} for k, v in
                prov_data.items()]
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
                    if "infores:text-mining-provider-targeted" in n.decode('utf-8'):
                        continue
                    prov[edge] = process_prov(n)
                # To make up for the fact that we added in inverted edges for
                # related to, but the prov doesn't know about it.
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

def get_opportunity(answerset):
    query_graph = answerset.get("query_graph", {})
    allpreds = set()
    opportunity = {'answer_categories': set()}
    alledges = set()
    eid = set()
    nodes = query_graph.get("nodes", {})
    # {"object_aspect_qualifier": "activity", "object_direction_qualifier": "decreased", "predicate": "biolink:affects"}
    for qg_eid, edge_data in query_graph.get("edges", {}).items():
        subject = nodes[edge_data.get('subject')]
        object = nodes[edge_data.get('object')]
        allpreds.update(edge_data.get('predicates'))
        if ("ids" in subject) and (subject["ids"] is not None):
            qnode_ids = subject["ids"]
            is_source = True
        else:
            is_source = False
            qnode_ids = object["ids"]

        eid.add(qg_eid)
        if is_source:
            opportunity['q_node'] = edge_data.get('subject')
            opportunity['a_node'] = edge_data.get('object')
            return_category = object.get('categories', [])
        else:
            opportunity['q_node'] = edge_data.get('object')
            opportunity['a_node'] = edge_data.get('subject')
            return_category = subject.get('categories', [])

        opportunity['answer_categories'].update(return_category)
        for qnode_id in qnode_ids:
            edgepredicate = {}; qualifiers = {}
            if 'qualifier_constraints' in edge_data and len(edge_data.get('qualifier_constraints', [])) > 0:
                for i in edge_data.get('qualifier_constraints', [])[0].get('qualifier_set'):
                    qualifiers.update({i.get("qualifier_type_id"): i.get("qualifier_value")})
            for predicate in edge_data['predicates']:
                edgepredicate.update(qualifiers)
                edgepredicate.update({'predicate': predicate})
                alledges.add(f'{qnode_id}\t{json.dumps(edgepredicate)}\t{is_source}\t{return_category[0]}')

    opportunity['qg_curies'] = qnode_ids
    opportunity['edges'] = alledges
    opportunity['all_preds'] = allpreds
    opportunity['qg_eid'] = eid


    return opportunity

def get_curie_to_lookup_links(opportunity):
    """
    Finds keys in Redis whose values contain a specific pattern.
    """
    curie = opportunity['qg_curies'][0]
    unique_link_nodes_with_prov = set([curie])
    predicate_links = defaultdict(set)
    predicates = opportunity['all_preds']
    with get_redis_pipeline(0) as p:
        # for curie, predicate in zip(curies, predicates):
            # sample
            # MONDO:0004975 [["PUBCHEM.COMPUND:0002", "{\"predicate\": \"biolink:treats\"}", true], [
            #     "UniProtKB:P05155-1, "{\"predicate\": \"biolink:coexpressed_with\"}", true]]
        p.get(curie)
        all_links = p.execute()
    full_edges = set()
    # for curie in curies:
    for linkstring, predicate in zip(all_links, list(predicates)):
        links = orjson.loads(linkstring)
        for link in links:
        # ["PUBCHEM.COMPOUND:0002", "{\"predicate\": \"biolink:treats\"}", true]
        #     if predicate not in link[1]: #If we want the {"predicate": "biolink:treats_or_applied_or_studied_to_treat"} edges
            if predicate != orjson.loads(link[1])['predicate']:
                continue
            if link[2]:
                full_edges.add(f'{curie} {link[1]} {link[0]}')
            else:
                full_edges.add(f'{link[0]} {link[1]} {curie}')
            predicate_links[link[1]].add(f'{link[0]}, {link[2]}')
            # unique_link_nodes.add(link[0])
            logger.debug(f'{len(predicate_links)} links discovered for {predicate} edge.')
#get provenance for the edges
    prov = get_provs(full_edges)
    unique_link_nodes_with_prov.update([edge.split(' ')[0] for edge in prov])

    predicate_links_with_prov = defaultdict(set)
    for pred, links in predicate_links.items():
        predicate_links_with_prov[pred] = {link for link in links if link.split(', ')[0] in unique_link_nodes_with_prov}
    return predicate_links_with_prov, unique_link_nodes_with_prov, prov

def make_kg_and_results(normalized_nodes, links, provs, qnodes, opportunity):
    kg_edges = {}
    answerset = {}
    anode = opportunity['a_node']
    qnode = opportunity['q_node']
    qg_eid = list(opportunity['qg_eid'])[0]
    for edges, prov in provs.items():
        sources = []
        source_id, obj_and_predicate = edges.split(" {")
        edge, target_id = obj_and_predicate.split('} ')
        edge = f'{{{edge}}}'
        for pro in prov:
            source1 = {'resource_id': 'infores:automat-robokop', 'resource_role': 'aggregator_knowledge_source'}
            source2 = {'resource_id': 'infores:aragorn', 'resource_role': 'aggregator_knowledge_source'}
            source1['upstream_resource_ids'] = [pro.get('resource_id', None)]
            source2['upstream_resource_ids'] = [source1.get('resource_id', None)]
            sources.extend([source1, source2])
        source_pov = prov + sources
        edge_def = ast.literal_eval(edge)
        one_edge = {'subject': source_id, 'object': target_id, 'predicate': edge_def["predicate"], 'sources': source_pov, 'attributes': []}

        if len(edge_def) > 1:
            one_edge["qualifiers"] = [{"qualifier_type_id": f"biolink:{ekey}", "qualifier_value": eval}
                                  for ekey, eval in edge_def.items() if not ekey == "predicate"]

       # Need to make a key for the edge, but the attributes & quals make it annoying
        ek = deepcopy(one_edge)
        ek['attributes'] = str(ek['attributes'])
        ek['sources'] = str(ek['sources'])
        if 'qualifiers' in ek:
            ek['qualifiers'] = str(ek['qualifiers'])
        eid = str(hash(frozenset(ek.items())))
        kg_edges.update({eid: one_edge})
        answerset = create_result(source_id, target_id, eid, anode, qnode, qg_eid, answerset)

    kg_and_result = {"knowledge_graph": {'edges': kg_edges, 'nodes': normalized_nodes},
          "results": list(answerset.values())}
    return kg_and_result

def create_result(source_id, target_id, eid, anode, qnode, qedge, answerset):
    answer = {}
    if answerset and source_id in answerset:
        answerset[source_id]['analyses'][0]["edge_bindings"][qedge].append({"id": eid})
    else:
        answer['node_bindings'] = {qnode: [{'id': target_id, 'qnode_id': target_id}],
                                   anode: [{'id': source_id}]}
        answer['analyses'] = [{"resource_id": "infores:automat-robokop",
                               "edge_bindings": { qedge: [{ "id": eid }]},
                               "score": 0.}]
        answerset[source_id] = answer

    return answerset

def normalize_qgraph_ids(unique_link_nodes, return_category):
    url = f'https://nodenormalization-sri.renci.org/get_normalized_nodes'
    normalized_curies = {}
    nnp = { "curies": list(unique_link_nodes), "conflate": True }
    nnresult = requests.post(url, json=nnp)
    if nnresult.status_code == 200:
        nnresults = nnresult.json()
        normalized_curies = format_node(nnresults, return_category)
    else:
        logger.error(f"Error reaching node normalizer: {nnresult.status_code}")
    return normalized_curies

def format_node(nnresults, return_category):
    result = {}
    for key, value in nnresults.items():
        if not value.get('id', {}).get('label'):
            continue
        if not value.get('type'):
            continue
        if return_category:
            if return_category.intersection([item['identifier'] for item in value['equivalent_identifiers']]) == set():
                continue
        result[key] = {'name': value['id']['label'], 'categories': value['type'], 'attributes': [{
            "attribute_type_id": "biolink:same_as",
            "value": [item['identifier'] for item in value['equivalent_identifiers']],
            "value_type_id": "metatype:uriorcurie",
            "original_attribute_name": "equivalent_identifiers"
        },
            {
                "attribute_type_id": "biolink:Attribute",
                "value": value.get('information_content', 0),
                "value_type_id": "EDAM:data_0006",
                "original_attribute_name": "information_content"
            }]}
    return result

def lookup(answerset):
    opportunity = get_opportunity(answerset)
    links, unique_link_nodes, provs = get_curie_to_lookup_links(opportunity)
    if links:
        # normalized_nodes = normalize_qgraph_ids(unique_link_nodes, opportunity.get('answer_categories'))
        normalized_nodes = get_node_properties(unique_link_nodes, opportunity.get('answer_categories'))
        qnodes = set(normalized_nodes.keys()).intersection(opportunity.get('qg_curies'))
        kg_and_result = make_kg_and_results(normalized_nodes, links, provs, qnodes, opportunity)
        kg_and_result.update({'query_graph': answerset["query_graph"]})
        message = {"message": kg_and_result}
        return message, 200
    else:
        return {}, 500

#
# # Example usage
# if __name__ == "__main__":
#     answerset = {
#         "workflow": [
#             {
#                 "id": "enrich_results",
#                 "parameters": {"pvalue_threshold": 1e-7,
#                                "predicates_to_exclude": [
#                                    "biolink:causes", "biolink:biomarker_for", "biolink:biomarker_for",
#                                    "biolink:contraindicated_for",
#                                    "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"
#                                ]
#                                }
#             }
#         ],
#         "message": {
#             "query_graph": {
#                 "nodes": {
#                     "chemical": {
#                         "categories": [
#                             "biolink:ChemicalEntity"
#                         ],
#                         "is_set": False,
#                         "constraints": []
#                     },
#                     "disease": {
#                         "ids": [
#                             "MONDO:0004975"
#                         ],
#                         "is_set": False,
#                         "constraints": []
#                     }
#                 },
#                 "edges": {
#                     "e00": {
#                         "subject": "chemical",
#                         "object": "disease",
#                         "predicates": [
#                             "biolink:treats"
#                         ],
#                         "attribute_constraints": [],
#                         "qualifier_constraints": []
#                     }
#                 }
#             }
#         }
#     }
#     result = start(answerset.get("message", {}))
#     print(result)
