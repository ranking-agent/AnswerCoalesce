
import os, requests, json, httpx, logging, uuid, asyncio,time
from requests.models import Response
from datetime import datetime, timedelta
from copy import deepcopy
from collections import defaultdict
from functools import partial
from string import Template
from operations import sort_results_score, filter_results_top_n, filter_kgraph_orphans, filter_message_top_n
from reasoner_pydantic import Response as PDResponse, Query, KnowledgeGraph, QueryGraph
from util import create_log_entry
import src.single_node_coalescer as snc
from fastapi.testclient import TestClient
from reasoner_pydantic import Response as PDResponse
from src.server import APP
client = TestClient(APP)

logger = logging.getLogger(__name__)
jsondir = 'InputJson_1.4'
AC_TEST_URL = "https://answercoalesce-test.apps.renci.org/1.4/query/"
ROBOKOP_URL = "https://aragorn.renci.org/robokop/query"
rulefile = os.path.join(os.path.dirname(__file__),"rules","kara_typed_rules","rules_with_types_cleaned_finalized.json")
# rulefile = os.path.join(os.path.dirname(__file__),"rules","rules.json")
with open(rulefile,'r') as inf:
    AMIE_EXPANSIONS = json.load(inf)

async def lookup(message) -> (dict, int):
    try:
        AC_TEST_URL = os.environ.get("AC_URL", "https://answercoalesce-test.apps.renci.org/1.4/query/")
        max_conns = os.environ.get("MAX_CONNECTIONS", 5)
        nrules = int(os.environ.get("MAXIMUM_ROBOKOPKG_RULES", 10))
        original_query_graph = message['message']['query_graph']
        input_message = deepcopy(message)
        tasks = []
        input_id, is_set, source, source_input, target, answer_category, keys = get_infer_parameters(input_message)
        rule_results = get_rule_results(input_message, keys, source, target, input_id, is_set, answer_category, source_input)
        # tasks.append(asyncio.create_task(rule_learning(input_message, rules, nrules, target, AC_TEST_URL, max_conns)))
        # tasks.append(asyncio.create_task(enrichmentbased(message, AC_TEST_URL)))
        # results = await asyncio.gather(*tasks)
        return combine_all(rule_results, input_message, original_query_graph, original_query_graph, target), 200
    except ConnectionError as c:
        return f"Illegal caller {c}", 400

def get_rule_results(input_message, keys, source, target, input_id, is_set, answer_category, source_input=False):
    original_result = multiqueryAC(input_message, AC_TEST_URL=AC_TEST_URL)
    result_messages = []
    original_query_graph = input_message["message"]["query_graph"]
    allnodes = set(input_message["message"]["query_graph"]["nodes"].keys())
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
                ## if we strictly want only rules that satisfies the subject category, but it seems not important right now
                # if query["query_graph"]["nodes"][target]["categories"] == answer_category:
                if len(query['query_graph']['nodes'])>2 or len(query['query_graph']['edges'])>1:
                    r_messages = expandmultihopquery(query, allnodes, is_set)
                else:
                    r_messages = [multiqueryAC({"message": query}, AC_TEST_URL=AC_TEST_URL)]
                if None in r_messages:
                    continue
                combined_res = combine_multihoprule_results(source, original_query_graph, query,
                                                            r_messages, original_result)
                result_messages.extend(combined_res)
            else:
                del query["query_graph"]["nodes"][source]["ids"]
                query["query_graph"]["nodes"][target]["ids"] = input_id
                query["query_graph"]["nodes"][target].update({"is_set": is_set, "constraints": []})
                query["query_graph"]["nodes"][source].update({"is_set": not(is_set), "constraints": []})
                if len(query['query_graph']['nodes'])>2 or len(query['query_graph']['edges'])>1:
                    r_messages = expandmultihopquery(query, allnodes, is_set)
                else:
                    r_messages = [multiqueryAC({"message": query}, AC_TEST_URL=AC_TEST_URL)]
                if None in r_messages:
                    continue
                combined_res = combine_multihoprule_results(source, original_query_graph, query,
                                                        r_messages, original_result)
                result_messages.extend(combined_res)
    return result_messages


def combine_multihoprule_results(answer_qnode, original_query_graph, lookup_query_graph, r_messages, original_result):
    pydantic_kgraph = KnowledgeGraph.parse_obj(original_result["message"]["knowledge_graph"])
    auxiliary_graphs = {}
    for rm in r_messages:
        pydantic_kgraph.update(KnowledgeGraph.parse_obj(rm["message"]["knowledge_graph"]))


    result = PDResponse(**{
        "message": {"query_graph": {"nodes": {}, "edges": {}},
                    "knowledge_graph": {"nodes": {}, "edges": {}},
                    "results": [],
                    "auxiliary_graphs": {}}}).dict(exclude_none=True)
    result["message"]["query_graph"] = original_query_graph
    result["message"]["results"] = original_result["message"]["results"].copy()
    result["message"]["knowledge_graph"] = pydantic_kgraph.dict()

    lookup_results = []  # in case we don't have any
    rules = []
    rule_edges = []
    for result_message in r_messages:
        if queries_equivalent(result_message["message"]["query_graph"], lookup_query_graph["query_graph"]):
            result["message"]["results"].extend(result_message["message"]["results"])
        else:
            rule_edges.extend(result_message["message"]["knowledge_graph"]["edges"])

     # make aux graph out of the result
    aux_graph_id = str(uuid.uuid4())
    aux_graph = {"edges": rule_edges}
    new_results = [result["message"]["results"][i].update({'support_graph': aux_graph_id}) for i in range(len(result["message"]["results"]))]
    result["message"]["results"] = new_results
    result["message"]["auxiliary_graphs"].update({aux_graph_id: aux_graph})

    return result


# def combine_multihoprule_results(answer_qnode, original_query_graph, lookup_query_graph, r_messages, original_result):
#     pydantic_kgraph = KnowledgeGraph.parse_obj(original_result["message"]["knowledge_graph"])
#     for rm in r_messages:
#         pydantic_kgraph.update(KnowledgeGraph.parse_obj(rm["message"]["knowledge_graph"]))
#
#     result = PDResponse(**{
#         "message": {"query_graph": {"nodes": {}, "edges": {}},
#                     "knowledge_graph": {"nodes": {}, "edges": {}},
#                     "results": [],
#                     "auxiliary_graphs": {}}}).dict(exclude_none=True)
#     result["message"]["query_graph"] = original_query_graph
#     result["message"]["results"] = original_result["message"]["results"].copy()
#     result["message"]["knowledge_graph"] = pydantic_kgraph.dict()
#
#     lookup_results = []
#     for result_message in r_messages:
#         if queries_equivalent(result_message["message"]["query_graph"],lookup_query_graph["query_graph"]):
#             lookup_results = result_message["message"]["results"]
#         else:
#             result["message"]["results"].extend(result_message["message"]["results"])
#     if not lookup_results:
#         lookup_results = original_result["message"]["results"].copy()
#     mergedresults = merge_results_by_node(result, answer_qnode, lookup_results)
#     return mergedresults
#


def expandmultihopquery(query, allnodes, is_set):
    nodes = query['query_graph']['nodes']
    anodes = []
    qgtemp = []
    for edgekey, edge in query['query_graph']['edges'].items():
        subject = edge['subject']
        object = edge['object']
        if set([subject, object]) != allnodes:
            anode = list(set([subject, object]).difference(allnodes))[0]
            query['query_graph']['nodes'][anode].update({"is_set": not(is_set), "constraints": []})
            anodes.append(anode)
        edge["knowledge_type"] = "inferred"
        edge['attribute_constraints'] = []
        qg = {'query_graph': {'nodes': {subject: nodes[subject], object: nodes[object]}, 'edges': {edgekey: edge}}}
        qgtemp.append(qg)

    result_messages = processqg(qgtemp, anodes)
    return result_messages

def get_infer_parameters(input_message):
    keydicts = []
    for edge_id, edge in input_message["message"]["query_graph"]["edges"].items():
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

    if ("ids" in input_message["message"]["query_graph"]["nodes"][source]) \
            and (input_message["message"]["query_graph"]["nodes"][source]["ids"] is not None):
        input_id = input_message["message"]["query_graph"]["nodes"][source]["ids"]
        source_input = True
        is_set = input_message["message"]["query_graph"]["nodes"][source]['is_set']
        answer_category = input_message["message"]["query_graph"]["nodes"][target]["categories"]
    else:
        input_id = input_message["message"]["query_graph"]["nodes"][target]["ids"]
        source_input = False
        is_set = input_message["message"]["query_graph"]["nodes"][target]['is_set']
        answer_category = input_message["message"]["query_graph"]["nodes"][source]["categories"]

    return input_id, is_set, source, source_input, target, answer_category, keydicts

def multiqueryAC(input_message, AC_TEST_URL=AC_TEST_URL):
    # with open(f"newset{datetime.now()}.json", 'w') as outf:
    #     json.dump(input_message, outf, indent=4)
    # # headers = {'Content-Type': 'application/json'}
    url_response = requests.post(AC_TEST_URL, json=input_message)
    coalesced = url_response.json()
    if url_response.status_code == 200 and coalesced['message']['results']:
        return coalesced
    else:
        try:
            client_response = client.post('/query', json=input_message)
            if client_response.status_code == 200:
                return json.loads(client_response.content)
        except ModuleNotFoundError:
            return input_message

def processqg(queries, anodes):
    # wait!!!!!
    result_messsages = []
    for i, query in enumerate(queries.copy()):
        query_graph = query.get('query_graph', {})
        nodes = query_graph.get('nodes', {})

        # !!!!Check if 'ids' are present in the 'nodes'
        if any('ids' in node for node in nodes.values()):
            intermediate_results = multiqueryAC({"message": query}, AC_TEST_URL=AC_TEST_URL)
            if anodes:
                anode = anodes[i]
                intermediate_answers = get_intermediate_nodes(intermediate_results, anode)
            # Remove the processed query from the list
            if not intermediate_answers['message']['results']:
                robo_response = try_robokop_url(query)
            result_messsages.append(intermediate_results)
            queries.remove(query)

    # Process the remaining queries
    for j, query in enumerate(queries):
        if anodes:
            anode = anodes[j]
            infix_intermediate_ids(query, intermediate_answers, anode)
        result = multiqueryAC({"message": query}, AC_TEST_URL=AC_TEST_URL)
        if not result['message']['results']:
            robo_response = try_robokop_url(query)
        result_messsages.append(result)
    return result_messsages

def try_robokop_url(query):
    # qg = query.copy()
    for nodekey, node in query['query_graph']['nodes'].items():
        if 'ids' in node:
            keynode = nodekey
            input_ids = node['ids']
    results = []
    for ids in input_ids:
        qgnext = query.copy()
        qgnext['query_graph']['nodes'][keynode].update({'ids': [ids], 'is_set': False})
        r = requests.post(ROBOKOP_URL, json={"message": qgnext})
        if r.status_code == 200:
            results.append(r.json())
    return results

def get_intermediate_nodes(intermediate_results, anode):
    results = intermediate_results['message']['results']
    intermediate_answers = []
    for r in results:
        intermediate_answers.append(r['node_bindings'][anode][0]['id'])
    return intermediate_answers

def infix_intermediate_ids(qg, intermediate_answers, anode):

    return qg['query_graph']['nodes'][anode].update({'ids': intermediate_answers, 'is_set': True})




def combine_all(result_messages, input_message, original_query_graph, lookup_query_graph, answer_qnode):
    print(f'result_messages: {result_messages}')
    pydantic_kgraph = KnowledgeGraph.parse_obj({"nodes": {}, "edges": {}})
    # Construct the final result message, currently empty
    result = PDResponse(**{
        "message": {"query_graph": {"nodes": {}, "edges": {}},
                    "knowledge_graph": {"nodes": {}, "edges": {}},
                    "results": []}}).dict(exclude_none=True)

    for rms in result_messages:
        # print(rms)
        if rms[1] == 200:
            rm = rms[0]
            pydantic_kgraph.update(KnowledgeGraph.parse_obj(rm["message"]["knowledge_graph"]))
            result["message"]["results"].extend(rm["message"]["results"])

    result["message"]["query_graph"] = original_query_graph
    result["message"]["knowledge_graph"] = pydantic_kgraph.dict()

    with open(f"_eb-rb_merged{datetime.now()}.json", 'w') as outf:
        json.dump(result, outf, indent=2)

    return result

def merge_results_by_node(result_message, merge_qnode, lookup_results):
    grouped_results = group_results_by_qnode(merge_qnode, result_message, lookup_results)
    original_qnodes = result_message["message"]["query_graph"]["nodes"].keys()
    new_results = []
    for r in grouped_results:
        new_result = merge_answer(result_message, r, grouped_results[r], original_qnodes)

        # new_result = merge_answer(result_message, r, grouped_results[r], original_qnodes, robokop)
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
