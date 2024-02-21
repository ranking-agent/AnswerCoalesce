
import os, requests, json, httpx, logging, uuid, asyncio,time
from datetime import datetime, timedelta
from copy import deepcopy
from collections import defaultdict
from functools import partial
from string import Template
from src.operations import sort_results_score, filter_results_top_n, filter_kgraph_orphans, filter_message_top_n
from reasoner_pydantic import Response as PDResponse, Query, KnowledgeGraph, QueryGraph
from fastapi.testclient import TestClient
from reasoner_pydantic import Response as PDResponse
from src.single_node_coalescer import coalesce

logger = logging.getLogger(__name__)

AC_TEST_URL = "https://answercoalesce-test.apps.renci.org/1.4/query/"
max_conns = os.environ.get("MAX_CONNECTIONS", 5)
nrules = int(os.environ.get("MAXIMUM_ROBOKOPKG_RULES", 5))

rulefile = os.path.join(os.path.dirname(__file__),"rules","dummyrule.json")
with open(rulefile,'r') as inf:
    AMIE_EXPANSIONS = json.load(inf)

def multiCurieLookup(message) -> (dict, int):
    try:
        input_message = deepcopy(message)
        # tasks = []
        input_id, is_set, source, source_input, target, answer_category, keys = get_infer_parameters(input_message)
        rule_results = get_rule_results(input_message, keys, source, target, input_id, is_set, answer_category, source_input)
        # tasks.append(asyncio.create_task(rule_learning(input_message, rules, nrules, target, AC_TEST_URL, max_conns)))
        # tasks.append(asyncio.create_task(enrichmentbased(message, AC_TEST_URL)))
        # results = await asyncio.gather(*tasks)
        return rule_results
    except ConnectionError as c:
        return f"Illegal caller {c}", 400

def get_rule_results(input_message, keys, source, target, input_id, is_set, answer_category, source_input=False):
    original_result = coalesce(input_message)
    result_messages = []
    original_query_graph = input_message["query_graph"]
    allnodes = input_message["query_graph"]['nodes'].keys()
    for key in keys:
        for rule_def in AMIE_EXPANSIONS.get(key,[]):
            query_template = Template(json.dumps(rule_def["template"]))
            if source_input:
                qs = query_template.substitute(source=source,target=target,source_id = input_id, target_id='')
            else:
                qs = query_template.substitute(source=source, target=target, target_id=input_id, source_id='')
            query = json.loads(qs)
            if source_input:
                del query["query_graph"]["nodes"][target]["ids"]
                query["query_graph"]["nodes"][source]["ids"] = input_id
                query["query_graph"]["nodes"][source].update({"is_set": is_set, "constraints": []})
                query["query_graph"]["nodes"][target].update({"is_set": not(is_set), "constraints": []})
                # with open(f"prototyping_results/Multihop_Query{datetime.now()}.json", 'w') as outf:
                #     json.dump(query, outf, indent=2)
                if len(query['query_graph']['nodes'])>2 or len(query['query_graph']['edges'])>1:
                    # with open('prototyping_results/ResultsList.json', 'r') as inf:
                    #     r_messages = json.load(inf)
                    r_messages = expandmultihopquery(query, allnodes, is_set)
                else:
                    r_messages = [coalesce_msg(query)]
                if None in r_messages:
                    continue
                combined_res = combine_multihoprule_results(source, original_query_graph, query,
                                                            r_messages, original_result)
                result_messages.append(combined_res)
            else:
                del query["query_graph"]["nodes"][source]["ids"]
                query["query_graph"]["nodes"][target]["ids"] = input_id
                query["query_graph"]["nodes"][target].update({"is_set": is_set, "constraints": []})
                query["query_graph"]["nodes"][source].update({"is_set": not(is_set), "constraints": []})
                if len(query['query_graph']['nodes'])>2 or len(query['query_graph']['edges'])>1:
                    r_messages =  expandmultihopquery(query, allnodes, is_set)
                else:
                    r_messages = [coalesce_msg(query)]
                if None in r_messages:
                    continue
                combined_res = combine_multihoprule_results(source, original_query_graph, query, r_messages, original_result)
                result_messages.append(combined_res)
    # There is only one result
    return result_messages[0]["message"]

def combine_multihoprule_results(source, original_query_graph, query,
                                 r_messages, original_result):
    pydantic_kgraph = KnowledgeGraph.parse_obj(original_result["knowledge_graph"])
    for rm in r_messages:
        pydantic_kgraph.update(KnowledgeGraph.parse_obj(rm["message"]["knowledge_graph"]))


    result = PDResponse(**{
        "message": {"query_graph": {"nodes": {}, "edges": {}},
                    "knowledge_graph": {"nodes": {}, "edges": {}},
                    "results": [],
                    "auxiliary_graphs": {}}}).dict(exclude_none=True)
    result["message"]["query_graph"] = original_query_graph
    result["message"]["knowledge_graph"] = pydantic_kgraph.dict()
    for node, node_dict in original_query_graph['nodes'].items():
        if not node_dict.get('ids'):
            a_node = node
    qg_nodes = set(original_query_graph['nodes'].keys())
    q_node = list(qg_nodes.difference([a_node]))[0]
    qg_qualifiers = []
    for qg_ed in original_query_graph['edges']:
        orignial_Edge = qg_ed
        qg_predicate = original_query_graph['edges'][qg_ed]['predicates'][0]
        if original_query_graph['edges'][qg_ed].get('qualifier_constraints', []):
            qg_qualifiers = original_query_graph['edges'][qg_ed]["qualifier_constraints"][0].get("qualifier_set", [])
    # We had if b-f ^ f-a then b-a
    # b : set of input genes
    # f : set of intermediate nodes
    # a : set of answer nodes that solves what ?a regulates b
    bf = {}
    bf_edges = {}
    bf_edges_attributes = {}
    aux_graphs = {}
    new_graph_edges = {}

    # bf
    for rmsg in r_messages:
        # making sure that we regroup only the rule
        if not queries_equivalent(rmsg["message"]["query_graph"], original_query_graph):
            msg_nodes = rmsg["message"]["query_graph"]["nodes"]
            if source in msg_nodes:
                continue
            mid = list(set(msg_nodes).difference(qg_nodes))[0]
            for r in rmsg["message"]["results"]:
                b = r["node_bindings"][q_node]
                f = r["node_bindings"][mid][0]['id']
                for bs in b:
                    bf.setdefault(f, []).append(bs['id'])
                for qedge in r['analyses'][0]['edge_bindings']:
                    bf_edges.setdefault(f, []).extend([e['id'] for e in r['analyses'][0]['edge_bindings'][qedge]])
                    bf_edges_attributes.setdefault(f, []).extend(r['analyses'][0]['attributes'])

    # fa
    for rmsg in r_messages:
        # making sure that we regroup only the rule
        if not queries_equivalent(rmsg["message"]["query_graph"], original_query_graph):
            msg_nodes = rmsg["message"]["query_graph"]["nodes"]
            if source not in msg_nodes:
                continue
            mid = list(set(msg_nodes).difference(qg_nodes))[0]
            msg_results = []
            for r in rmsg["message"]["results"]:
                one_result = {'node_bindings': {}, 'analyses': []}
                fs = r["node_bindings"][mid].copy()
                a = r["node_bindings"][a_node][0]['id']

                # replace fa with ba: use the f to get the b that replaces f
                newb = {q_node: remove_duplicates_ids([{'id': b, 'qnode_id': b} for f in fs for b in bf.get(f['id'])])}
                newa = {a_node: r["node_bindings"][a_node]}
                edge_0_attributes = r['analyses'][0].get('attributes')
                edge_0 = [e['id'] for bdedge in r['analyses'][0]['edge_bindings'] for e in r['analyses'][0]['edge_bindings'].get(bdedge)]
                aux_graph_id_0 = a+'--->'+'_'.join([f['id'] for f in fs])

                if aux_graph_id_0 in aux_graphs:
                    # Extend the existing edges for the given aux_graph_id
                    aux_graphs[aux_graph_id_0]['edges'].extend(edge_0)
                else:
                    # Create a new entry if aux_graph_id doesn't exist
                    aux_graphs.setdefault(aux_graph_id_0, {}).update({'edges': edge_0, 'attributes': edge_0_attributes})
                qnode_ids = [ed['id'] for ed in newb[q_node]]

                # make new knowledge graph edges
                kgedges = []
                for qnode_id in qnode_ids:
                    sources =  [{'resource_id': 'infores:robokop',
                                 'resource_role': 'aggregator_knowledge_source',
                                 'upstream_resource_ids': ['infores:automat-robokop']}]

                    newkgedge = {'subject': a, 'predicate': qg_predicate, 'object': qnode_id, 'sources': sources,
                                 'qualifiers': qg_qualifiers}
                    tempedge = newkgedge.copy()
                    tempedge['sources'] = str(tempedge['sources'])
                    if 'qualifiers' in tempedge:
                        tempedge['qualifiers'] = str(tempedge['qualifiers'])
                    if 'attributes' in tempedge:
                        tempedge['attributes'] = str(tempedge['attributes'])
                    ek = str(hash(frozenset(tempedge.items())))
                    kgedges.append(ek)
                    new_graph_edges.update({ek:newkgedge})

                # analysis = []
                resource_id = 'infores:aragorn-robokop'
                edge_1 = [bf_edge for f in fs for bf_edge in bf_edges.get(f['id'])]

                edge_1_attributes = [bf_edges_attributes.get(f['id']) for f in fs][0]
                eb = {orignial_Edge:[{'id': ek} for ek in kgedges]}
                b_list = set(b for f in fs for b in bf.get(f['id']))
                aux_graph_id_1 = '_'.join([f['id'] for f in fs])+'--->'+'_'.join(b_list)
                if aux_graph_id_1 in aux_graphs:
                    # Extend the existing edges for the given aux_graph_id
                    aux_graphs[aux_graph_id_1]['edges'].extend(edge_1)
                else:
                    # Create a new entry if aux_graph_id doesn't exist
                    aux_graphs.setdefault(aux_graph_id_1, {}).update({'edges': edge_1, 'attributes': edge_1_attributes})
                aux_graphs[aux_graph_id_1]['edges'] = list(set(aux_graphs[aux_graph_id_1]['edges']))
                analyses = {'resource_id': resource_id,
                               'edge_bindings': eb,
                               # 'score': r['analyses'][0].get('score'),
                               'attributes': update_supporting_study_cohort(r['analyses'][0].get('attributes'))}
                               # 'support_graphs': [aux_graph_id_0]}

                # update the kg edges with the support graphs
                for kgedge in kgedges:
                    if new_graph_edges.get(kgedge, {}):
                        if new_graph_edges.get(kgedge, {}).get("attributes", []):
                            if new_graph_edges[kgedge].get("attributes", [])[0].get(
                                    "value",
                                    []):
                                new_graph_edges[kgedge].get("attributes", [])[0].get(
                                    "value", []).extend([aux_graph_id_0, aux_graph_id_1])
                        else:
                            new_graph_edges[kgedge].update({'attributes': [
                                {'attribute_type_id': "biolink:support_graphs", "value": [aux_graph_id_0, aux_graph_id_1]}]})


                one_result['node_bindings'].update(newb)
                one_result['node_bindings'].update(newa)
                one_result['analyses'].append(analyses)
                msg_results.append(one_result)
    result["message"]["results"] = msg_results
    result["message"]["knowledge_graph"]["edges"].update(new_graph_edges)
    result["message"]["auxiliary_graphs"].update(aux_graphs)

    with open(f"OneResults{datetime.now()}.json", 'w') as outf:
        json.dump(result, outf, indent=2)
    # merge_results = merge_results_by_node(result, a_node, original_result["results"])
    # with open(f"mergedResults{datetime.now()}.json", 'w') as outf:
    #     json.dump(merge_results, outf, indent=2)
    return result


def expandmultihopquery(query, allnodes, is_set):
    nodes = query['query_graph']['nodes']
    intermediate_qnodes = []
    qgtemp = []
    for edgekey, edge in query['query_graph']['edges'].items():
        subject = edge['subject']
        object = edge['object']
        if set([subject, object]) != allnodes:
            intermediate_qnode = list(set([subject, object]).difference(allnodes))[0]
            query['query_graph']['nodes'][intermediate_qnode].update({"is_set": not(is_set), "constraints": []})
            intermediate_qnodes.append(intermediate_qnode)
        edge["knowledge_type"] = "inferred"
        edge['attribute_constraints'] = []
        qg = {'query_graph': {'nodes': {subject: nodes[subject], object: nodes[object]}, 'edges': {edgekey: edge}}}
        qgtemp.append(qg)

    result_messages = processqg(qgtemp, intermediate_qnodes)
    # with open(f"prototyping_results/ResultsList{datetime.now()}.json", 'w') as outf:
    #     json.dump(result_messages, outf, indent=2)
    return result_messages

def update_supporting_study_cohort(attributes):
    index_to_update = next((index for index, attr in enumerate(attributes) if attr["attribute_type_id"] == "biolink:supporting_study_cohort"), None)
    if index_to_update is not None:
        attributes[index_to_update]["value"] = "gene"
    return attributes
def get_infer_parameters(input_message):
    keydicts = []
    for edge_id, edge in input_message["query_graph"]["edges"].items():
        source = edge["subject"]
        target = edge["object"]
        predicates = edge["predicates"]
        qc = edge.get("qualifier_constraints", [])
        if len(qc) == 0:
            qualifiers = {}
        else:
            # AMIE rule templates for qualifier edges have extra params 'qualifier_set' in them
            qualifiers = {"qualifier_constraints": qc}
        for predicate in predicates:
            keydict = {'predicate': predicate}
            keydict.update(qualifiers)
            keydicts.append(json.dumps(keydict, sort_keys=True))

    if ("ids" in input_message["query_graph"]["nodes"][source]) \
            and (input_message["query_graph"]["nodes"][source]["ids"] is not None):
        input_id = input_message["query_graph"]["nodes"][source]["ids"]
        source_input = True
        is_set = input_message["query_graph"]["nodes"][source]['is_set']
        answer_category = input_message["query_graph"]["nodes"][target]["categories"]
    else:
        input_id = input_message["query_graph"]["nodes"][target]["ids"]
        source_input = False
        is_set = input_message["query_graph"]["nodes"][target]['is_set']
        answer_category = input_message["query_graph"]["nodes"][source]["categories"]

    return input_id, is_set, source, source_input, target, answer_category, keydicts

def coalesce_msg(input_message):
    return {"message": coalesce(input_message)}

def remove_duplicates_ids(binding_list):
    # unique_set = []
    # seen_keys = set()
    # for d in binding_list:
    #     if isinstance(d, dict):
    #         frozen = frozenset(d.items())
    #         if frozen not in seen_keys:
    #             seen_keys.add(frozen)
    #             unique_set.append(dict(frozen))
    #     if isinstance(d, str) and d not in seen_keys:
    #         seen_keys.add(d)
    #         unique_set.append(d)
    # return unique_set
    return [dict(t) for t in {tuple(d.items()) for d in binding_list}]


def processqg(queries, intermediate_qnodes):
    decomposed_queries = []
    result_messsages = []
    intermediate_ids = []
    for i, query in enumerate(queries.copy()):
        query_graph = query.get('query_graph', {})
        nodes = query_graph.get('nodes', {})

        # !!!!!!!!!!!Check if 'ids' are present in the 'nodes'
        if any('ids' in node for node in nodes.values()):
            intermediate_answers = coalesce_msg(query)
            if intermediate_qnodes and intermediate_answers.get("message", {}):
                intermediate_qnode = intermediate_qnodes[i]
                intermediate_ids = get_intermediate_nodes(intermediate_answers, intermediate_qnode)
                # Remove the processed query from the list
            result_messsages.append(intermediate_answers)
            decomposed_queries.append(query)
            queries.remove(query)

    # Process the remaining queries
    for j, query in enumerate(queries):
        if intermediate_qnodes and intermediate_ids:
            anode = intermediate_qnodes[j]
            infix_intermediate_ids(query, intermediate_ids, anode)
            decomposed_queries.append(query)
            result = coalesce_msg(query)
            if result and result.get('message', {}).get('results', []):
                result_messsages.append(result)
            else:
                print(result)
                print("********")
                logger.info(f"Empty returned for the {len(intermediate_ids)} intermediate_ids")
    # with open(f"prototyping_results/decomposed_Queries{datetime.now()}.json", 'w') as outf:
    #     json.dump(decomposed_queries, outf, indent=2)
    return result_messsages


def get_intermediate_nodes(intermediate_results, anode):
    results = intermediate_results['message']['results']
    intermediate_answers = []
    for r in results:
        intermediate_answers.append(r['node_bindings'][anode][0]['id'])
    return intermediate_answers

def infix_intermediate_ids(qg, intermediate_answers, anode):

    return qg['query_graph']['nodes'][anode].update({'ids': intermediate_answers, 'is_set': True})



def merge_results_by_node(result_message, merge_qnode, lookup_results):
    grouped_results = group_results_by_qnode(merge_qnode, result_message, lookup_results)
    original_qnodes = result_message["message"]["query_graph"]["nodes"].keys()
    new_results = []
    for r in grouped_results:
        new_result = merge_answer(result_message, r, grouped_results[r], original_qnodes)
        new_results.append(new_result)
    result_message["message"]["results"] = new_results
    return result_message

def group_results_by_qnode(merge_qnode, result_message, lookup_results):
    original_results = result_message["message"].get("results", [])
    # group results
    grouped_results = defaultdict( lambda: {"creative": [], "lookup": []})
    # Group results by the merge_qnode
    for result_set, result_key in [(original_results, "creative"), (lookup_results, "lookup")]:
        for result in result_set:
            answer = result["node_bindings"][merge_qnode]
            bound = frozenset([x["id"] for x in answer])
            grouped_results[bound][result_key].append(result)
    return grouped_results

def merge_answer(result_message, answer, results, qnode_ids):
    """Given a set of results and the node identifiers of the original qgraph,
    create a single message.
    result_message has to contain the original query graph
    The original qgraph is a creative mode query, which has been expanded into a set of
    rules and run as straight queries using either strider or robokopkg.
    results contains both the lookup results and the creative results, separated out by keys
    Each result coming in is now structured like this:
    result
        node_bindings: Binding to the rule qnodes. includes bindings to original qnode ids
        analysis:
            edge_bindings: Binding to the rule edges.
    To merge the answer, we need to
    0) Filter out any creative results that exactly replicate a lookup result
    1) create node bindings for the original creative qnodes
    2) convert the analysis of each input result into an auxiliary graph
    3) Create a knowledge edge corresponding to the original creative query edge
    4) add the aux graphs as support for this knowledge edge
    5) create an analysis with an edge binding from the original creative query edge to the new knowledge edge
    6) add any lookup edges to the analysis directly
    """
    # 0. Filter out any creative results that exactly replicate a lookup result
    # How does this happen?   Suppose it's an inferred treats.  Lookup will find a direct treats
    # But a rule that ameliorates implies treats will also return a direct treats because treats
    # is a subprop of ameliorates. We assert that the two answers are the same if the set of their
    # kgraph edges are the same.
    # There are also cases where subpredicates in rules can lead to the same answer.  So here we
    # also unify that.   If we decide to pass rules along with the answers, we'll have to be a bit
    # more careful.
    lookup_edgesets = [get_edgeset(result) for result in results["lookup"]]
    creative_edgesets = set()
    creative_results = []
    for result in results["creative"]:
        creative_edges = get_edgeset(result)
        if creative_edges in lookup_edgesets:
            continue
        elif creative_edges in creative_edgesets:
            continue
        else:
            creative_edgesets.add(creative_edges)
            creative_results.append(result)
    results["creative"] = creative_results
    # 1. Create node bindings for the original creative qnodes and lookup qnodes
    mergedresult = {"node_bindings": {}, "analyses": []}
    serkeys = defaultdict(set)
    for q in qnode_ids:
        mergedresult["node_bindings"][q] = []
        for result in results["creative"] + results["lookup"]:
            for nb in result["node_bindings"][q]:
                serialized_binding = json.dumps(nb,sort_keys=True)
                if serialized_binding not in serkeys[q]:
                    mergedresult["node_bindings"][q].append(nb)
                    serkeys[q].add(serialized_binding)

    # 2. convert the analysis of each input result into an auxiliary graph
    aux_graph_ids = []
    if "auxiliary_graphs" not in result_message["message"] or result_message["message"]["auxiliary_graphs"] is None:
        result_message["message"]["auxiliary_graphs"] = {}
    for result in results["creative"]:
        for analysis in result["analyses"]:
            aux_graph_id, aux_graph = create_aux_graph(analysis)
            result_message["message"]["auxiliary_graphs"][aux_graph_id] = aux_graph
            aux_graph_ids.append(aux_graph_id)

    # 3. Create a knowledge edge corresponding to the original creative query edge
    # 4. and add the aux graphs as support for this knowledge edge
    knowledge_edge_ids = []
    if len(aux_graph_ids) > 0:
        #only do this if there are creative results.  There could just be a lookup
        for nid in answer:
            knowledge_edge_id = add_knowledge_edge(result_message, aux_graph_ids, nid)
            knowledge_edge_ids.append(knowledge_edge_id)

    # 5. create an analysis with an edge binding from the original creative query edge to the new knowledge edge
    qedge_id = list(result_message["message"]["query_graph"]["edges"].keys())[0]

    source = "infores:aragorn"
    analysis = {
        "resource_id": source,
        "edge_bindings": {qedge_id:[ { "id":kid } for kid in knowledge_edge_ids ] }
                }

    mergedresult["analyses"].append(analysis)

    # 6. add any lookup edges to the analysis directly
    for result in results["lookup"]:
        for analysis in result["analyses"]:
            for qedge in analysis["edge_bindings"]:
                if qedge not in mergedresult["analyses"][0]["edge_bindings"]:
                    mergedresult["analyses"][0]["edge_bindings"][qedge] = []
                mergedresult["analyses"][0]["edge_bindings"][qedge].extend(analysis["edge_bindings"][qedge])

    #result_message["message"]["results"].append(mergedresult)
    return mergedresult

def add_knowledge_edge(result_message, aux_graph_ids, answer):
    """Create a new knowledge edge in the result message, with the aux graph ids as support."""
    # Find the subject, object, and predicate of the original query
    query_graph = result_message["message"]["query_graph"]
    #get the first key and value from the edges
    qedge_id, qedge = next(iter(query_graph["edges"].items()))
    #For the nodes, if there is an id, then use it in the knowledge edge. If there is not, then use the answer
    qnode_subject_id = qedge["subject"]
    qnode_object_id = qedge["object"]
    if "ids" in query_graph["nodes"][qnode_subject_id] and query_graph["nodes"][qnode_subject_id]["ids"] is not None:
        qnode_subject = query_graph["nodes"][qnode_subject_id]["ids"][0]
        qnode_object = answer
    else:
        qnode_subject = answer
        qnode_object = query_graph["nodes"][qnode_object_id]["ids"][0]
    predicate = qedge["predicates"][0]
    if "qualifier_constraints" in qedge and qedge["qualifier_constraints"] is not None and len(qedge["qualifier_constraints"]) > 0:
        qualifiers = qedge["qualifier_constraints"][0]["qualifier_set"]
    else:
        qualifiers = None
    # Create a new knowledge edge
    new_edge_id = str(uuid.uuid4())
    source = "infores:aragorn"
    new_edge = {
        "subject": qnode_subject,
        "object": qnode_object,
        "predicate": predicate,
        "attributes": [
            {
                "attribute_type_id": "biolink:support_graphs",
                "value": aux_graph_ids
            }
        ],
        # Aragorn is the primary ks because aragorn inferred the existence of this edge.
        "sources": [{"resource_id":source, "resource_role":"primary_knowledge_source"}]
    }
    if qualifiers is not None:
        new_edge["qualifiers"] = qualifiers
    result_message["message"]["knowledge_graph"]["edges"][new_edge_id] = new_edge
    return new_edge_id


def get_edgeset(result):
    """Given a result, return a frozenset of any knowledge edges in it"""
    edgeset = set()
    for analysis in result["analyses"]:
        for edge_id, edgelist in analysis["edge_bindings"].items():
            edgeset.update([e["id"] for e in edgelist])
    return frozenset(edgeset)

def create_aux_graph(analysis):
    """Given an analysis, create an auxiliary graph.
    Look through the analysis edge bindings, get all the knowledge edges, and put them in an aux graph.
    Give it a random uuid as an id."""
    aux_graph_id = str(uuid.uuid4())
    aux_graph = { "edges": [] }
    for edge_id, edgelist in analysis["edge_bindings"].items():
        for edge in edgelist:
            aux_graph["edges"].append(edge["id"])
    return aux_graph_id, aux_graph

async def filter_repeated_nodes(response,guid):
    """We have some rules that include e.g. 2 chemicals.   We don't want responses in which those two
    are the same.   If you have A-B-A-C then what shows up in the ui is B-A-C which makes no sense."""
    original_result_count = len(response["message"].get("results",[]))
    if original_result_count == 0:
        return
    results = list(filter(lambda x: has_unique_nodes(x), response["message"]["results"] ))
    response["message"]["results"] = results
    if len(results) != original_result_count:
        await filter_kgraph_orphans(response,{},guid)

def has_unique_nodes(result):
    """Given a result, return True if all nodes are unique, False otherwise"""
    seen = set()
    for qnode, knodes in result["node_bindings"].items():
        knode_ids = frozenset([knode["id"] for knode in knodes])
        if knode_ids in seen:
            return False
        seen.add(knode_ids)
    return True

def queries_equivalent(query1,query2):
    """Compare 2 query graphs.  The nuisance is that there is flexiblity in e.g. whether there is a qualifier constraint
    as none or it's not in there or its an empty list.  And similar for is_set and is_set is False.
    """
    q1 = query1.copy()
    q2 = query2.copy()
    for q in [q1,q2]:
        for node in q["nodes"].values():
            if "is_set" in node and node["is_set"] is False:
                del node["is_set"]
            if "constraints" in node and len(node["constraints"]) == 0:
                del node["constraints"]
        for edge in q["edges"].values():
            if "attribute_constraints" in edge and len(edge["attribute_constraints"]) == 0:
                del edge["attribute_constraints"]
            if "qualifier_constraints" in edge and len(edge["qualifier_constraints"]) == 0:
                del edge["qualifier_constraints"]
    return q1 == q2
