from copy import deepcopy
from collections import defaultdict
import ast, json
from string import Template
from typing import LiteralString

###
# These classes are used to extract the meaning from the TRAPI MCQ query into a more usable form
###

# TODO: Handle the case where we are not gifted a category for the group node
class MCQGroupNode:
    def __init__(self, query_graph):
        for qnode_id, qnode in query_graph["nodes"].items():
            if qnode.get("set_interpretation", "") == "MANY":
                self.curies = qnode["member_ids"]
                self.qnode_id = qnode_id
                self.uuid = qnode["ids"][0]
                self.semantic_type = qnode["categories"][0]

class MCQEnrichedNode:
    def __init__(self, query_graph):
        for qnode_id, qnode in query_graph["nodes"].items():
            if qnode.get("set_interpretation", "") != "MANY":
                self.qnode_id = qnode_id
                self.semantic_types = qnode["categories"]

class MCQEdge:
    def __init__(self, query_graph,groupnode_qnodeid):
        for qedge_id, qedge in query_graph["edges"].items():
            if qedge["subject"] == groupnode_qnodeid:
                self.group_is_subject = True
            else:
                self.group_is_subject = False
            self.qedge_id = qedge_id
            self.predicate_only = qedge["predicates"][0]
            self.predicate = {"predicate": qedge["predicates"][0]}
            qualifier_constraints = qedge.get("qualifiers_constraints", [])
            if len(qualifier_constraints) > 0:
                qc = qualifier_constraints[0]
                self.qualifiers = qc.get("qualifier_set", [])
                for q in self.qualifiers:
                    self.predicate[q["qualifier_type_id"]] = q["qualifier_value"]
            else:
                self.qualifiers = []

class MCQDefinition:
    def __init__(self,in_message):
        query_graph = in_message["message"]["query_graph"]
        self.group_node = MCQGroupNode(query_graph)
        self.enriched_node = MCQEnrichedNode(query_graph)
        self.edge = MCQEdge(query_graph,self.group_node.qnode_id)


###
# These components are about holding the results of Graph enrichment in a TRAPI independent way
###

class NewNode:
    def __init__(self, newnode, newnodetype): #edge_pred_and_qual, newnode_is):
        self.new_curie = newnode
        self.newnode_type = newnodetype
        self.name = None

class NewEdge:
    def __init__(self, source, predicate, target):
        self.source = source
        self.predicate = predicate
        self.target = target
    def get_prov_link(self):
        return f"{self.source} {self.predicate} {self.target}"
    def add_prov(self,prov):
        self.prov = prov

class Enrichment:
    def __init__(self,p_value,newnode: LiteralString, predicate: LiteralString, is_source, ndraws, n, total_node_count, curies, node_type):
        """Here the curies are the curies that actually link to newnode, not just the input curies."""
        self.p_value = p_value
        self.linked_curies = curies
        self.enriched_node = None
        self.predicate = predicate
        self.provmap = {}
        self.add_extra_node(newnode, node_type)
        self.add_extra_edges(newnode, predicate, is_source)
        self.counts = [ndraws, n, total_node_count]
    #def add_provenance(self,provmap):
    #    self.provmap = provmap
    def add_extra_node(self,newnode, newnodetype):
        """Optionally, we can patch by adding a new node, which will share a relationship of
        some sort to the curies in self.set_curies.  The remaining parameters give the edge_type
        of those edges, as well as defining whether the edge points to the newnode (newnode_is = 'target')
        or away from it (newnode_is = 'source') """
        self.enriched_node = NewNode(newnode, newnodetype)
    def add_extra_node_name_and_label(self,name_dict,label_dict):
        self.enriched_node.newnode_name = name_dict.get(self.enriched_node.new_curie, None)
        self.enriched_node.nodenode_categories = label_dict.get(self.enriched_node.new_curie, [])
    def add_extra_edges(self, newnode, predicate, newnode_is_source):
        """Add edges between the newnode (curie) and the curies that they were linked to"""
        if newnode_is_source:
            self.links = [NewEdge(newnode,self.predicate,curie) for curie in self.linked_curies]
        else:
            self.links = [NewEdge(curie,self.predicate,newnode) for curie in self.linked_curies]
    def get_prov_links(self):
        return [link.get_prov_link() for link in self.links]
    def add_provenance(self,prov):
        for link in self.links:
            provlink = link.get_prov_link()
            if provlink not in prov:
                print("what the hell")
            link.add_prov(prov[link.get_prov_link()])

    #TODO: this should not exist in here any more, we are just making a data class
    def x_apply(self,answers,question,graph,graph_index,patch_no):
        # Find the answers to combine.  It's not necessarily the answer_ids.  Those were the
        # answers that were originally in the opportunity, but we might have only found commonality
        # among a subset of them
        all_new_answers =[]
        possible_answers = [answers[i] for i in self.answer_indices]
        comb_answers = [a for a in possible_answers if self.isconsistent(a)]
        #This can happen for weird inputs like double bound nodes
        if len(comb_answers) < 2:
            return [],question,graph,graph_index
        #Modify the question graph and the knowledge graph
        #If we're not adding a new node, extra_q_node = None, extra_q_edges = extra_k_edges =[]. No bindings to add
        #If we have an added node, the added node is always self.newnode
        # Also we will have an extra_q_node in that case, as well as one extra_q_edge, and 1 or more new k_edges
        #question,extra_q_nodes,extra_q_edges = self.update_qg(question)
        graph,all_extra_k_edges,graph_index = self.update_kg(graph,graph_index)
        for answer in answers:
            if answer in comb_answers:
                if all_extra_k_edges:
                    #Then this is a graph oalsece
                    for node_no, extra_k_edges in enumerate(all_extra_k_edges):
                        answer.add_bindings(extra_k_edges, f'{patch_no}_{node_no}')
                    answer.add_properties(self.qg_id, self.new_props, f'{patch_no}_{node_no}')
                else:
                    # For property_coalesced nodes with no all_extra_k_edges
                    # Noticed some property patches has null from enriched_properties in the Property_coalescer,
                    # We need to be sure such nodes are not added into the enrichment
                    # Example in test_graph_coalesce_with_workflow() with method= 'all'
                    if self.new_props:
                        node_no = 0
                        answer.add_property_bindings(all_extra_k_edges, self.qg_id, self.new_props, f'{patch_no}_{node_no}')
            all_new_answers.append(answer)
        return all_new_answers, question, graph, graph_index


    def isconsistent(self, possibleanswer):
        """
        The patch is constructed from a set of possible answers, but it doesn't have to use all
        of them.  Checks to see if this answer is one of the ones that is still part of
        the patch/enriched.
        """
        # See if the value that the answer has for our this patch's variable node is on eof the patch's curies
        answer_kg_id = list(possibleanswer.node_bindings[self.qg_id])[0]
        if answer_kg_id in self.set_curies:
            return True
        return False
    def update_qg(self,qg):
        extra_q_nodes = []
        extra_q_edges = []
        #First add "set":True to our variable node
        qg['nodes'][self.qg_id]['is_set'] = True
        #for node in qg['nodes']:
        #    if node['id'] == self.qg_id:
        #        node['set'] = True
        #We are going to want to know whether we have aleady added a particular new node/edge.  Then if we are
        # adding it again, we can say, nope, already did it. So let's collect what we have.
        #Because of the way that we are constructing new queries, the only thing that will happen is an undirected
        # edge to self.qg_id.  So we really just need to know if there already is such a thing.
        qg_updated = False
        for edge_id,edge in qg['edges'].items():
            if edge_id.startswith('extra_'):
                if edge['subject'].startswith('extra'):
                    itis = 'source'
                    qid = edge['subject']
                    oid = edge['object']
                else:
                    itis = 'target'
                    qid = edge['subject']
                    oid = edge['object']
                #it might be that the oid is not the same one for this patch
                if oid != self.qg_id:
                    continue
                extra_q_nodes.append(qid)
                extra_q_edges.append(edge_id)
                qg_updated = True
        for newnode in self.added_nodes:
            #First, we need to decide whether this new node is already in there.
            rep = (set(newnode.newnode_type), newnode.newnode_is)
            if qg_updated:
                continue
            #Doesn't seem like it's already here, so Add the new node to the question.
            node_ids = list(qg['nodes'].keys())
            nnid = 0
            new_node_id = f'extra_qn_{nnid}'
            while new_node_id in node_ids:
                nnid += 1
                new_node_id = f'extra_qn_{nnid}'
            extra_q_nodes.append(new_node_id)

            if not isinstance(newnode.newnode_type, list):
                newnode.newnode_type = [newnode.newnode_type]

            qg['nodes'].update({new_node_id: {'categories': newnode.newnode_type}})
            #Add the new edge to the question
            edge_ids = list(qg['edges'].keys())
            neid = 0
            new_edge_id = f'extra_qe_{neid}'
            while new_edge_id in edge_ids:
                neid += 1
                new_edge_id = f'extra_qe_{neid}'
            if newnode.newnode_is == 'target':
                qg['edges'].update( {new_edge_id:{ 'subject': self.qg_id, 'object': new_node_id }})
            else:
                qg['edges'].update( {new_edge_id:{ 'subject': new_node_id, 'object': self.qg_id }})
            extra_q_edges.append(new_edge_id)
        return qg, extra_q_nodes, extra_q_edges


    def update_kg(self,kg,kg_index):
        if len(kg_index) == 0:
            kg_index['nodes'] = set( kg['nodes'].keys() )
            kg_index['edges'] = { (edge['subject'],edge['object'],edge['predicate']):edge_id for edge_id,edge in kg['edges'].items() }
        all_extra_edges = []
        for newnode in self.added_nodes:
            extra_edges=[]
            #See if the newnode is already in the KG, and if not, add it.
            found = False
            if newnode.newnode not in kg_index['nodes']:
                if not isinstance(newnode.newnode_type, list):
                    newnode.newnode_type = [newnode.newnode_type]

                kg['nodes'].update({ newnode.newnode:{'name': newnode.newnode_name, 'categories': newnode.newnode_type, 'attributes': []}})
                kg_index['nodes'].add(newnode.newnode)
            #Add new edges
            for curie in self.set_curies: #try to add a new edge from this curie to newnode
                if curie == newnode.newnode:
                    continue #no self edge please

                #check to see if the edge we want to add is already present in the kg
                if newnode.newnode_is == 'source':
                    source_id = newnode.newnode
                    target_id = curie
                else:
                    source_id = curie
                    target_id = newnode.newnode
                eid = None
                ekey = (source_id, target_id,  newnode.new_edges)
                if ekey not in kg_index['edges']:
                    try:
                        provs = self.provmap[ f'{source_id} {newnode.new_edges} {target_id}']
                    except KeyError:
                        provs = []

                    #newnode.new_edges is a string containing a dict like
                    #{"predicate": "biolink:affects", "object_aspect_qualifier":"transport"}

                    edge_def = ast.literal_eval(newnode.new_edges)

                    sources = []
                    for prov in provs:
                        source1 = {'resource_id': 'infores:automat-robokop', 'resource_role': 'aggregator_knowledge_source'}
                        source2 = {'resource_id': 'infores:aragorn', 'resource_role': 'aggregator_knowledge_source'}
                        source1['upstream_resource_ids'] = [prov.get('resource_id', None)]
                        source2['upstream_resource_ids'] = [source1.get('resource_id', None)]
                        sources.extend([source1, source2])
                    source_pov = provs + sources

                    edge = { 'subject': source_id, 'object': target_id, 'predicate': edge_def["predicate"],
                             'sources': source_pov, 'attributes': []}

                    if len(edge_def) > 1:
                        edge["qualifiers"] = [ {"qualifier_type_id": f"biolink:{ekey}", "qualifier_value": eval}
                                               for ekey, eval in edge_def.items() if not ekey == "predicate"]
                    #Need to make a key for the edge, but the attributes & quals make it annoying
                    ek = deepcopy(edge)

                    ek['attributes'] = str(ek['attributes'])
                    ek['sources'] = str(ek['sources'])
                    if 'qualifiers' in ek:
                        ek['qualifiers'] = str(ek['qualifiers'])
                    eid = str(hash(frozenset(ek.items())))
                    kg['edges'].update({eid:edge})
                    kg_index['edges'][ekey] = eid
                eid = kg_index['edges'][ekey]
                extra_edges.append(str(eid))

            all_extra_edges.append(extra_edges)
        return kg, all_extra_edges,kg_index

class PropertyPatch_query:
    def __init__(self,qg_id,curies,curies_types,curies_names,props,answer_ids):
        self.qg_id = qg_id
        self.set_curies = curies
        self.curies_types = curies_types
        self.curies_names = curies_names
        self.new_props = props
        self.answer_indices = answer_ids
        self.added_nodes = []
        self.provmap = {}
    def add_provenance(self,provmap):
        self.provmap = provmap
    def add_extra_node(self,newnode, newnodetype, edge_pred_and_qual, newnode_is,newnode_name):
        """Optionally, we can patch by adding a new node, which will share a relationship of
        some sort to the curies in self.set_curies.  The remaining parameters give the edge_type
        of those edges, as well as defining whether the edge points to the newnode (newnode_is = 'target')
        or away from it (newnode_is = 'source') """
        self.added_nodes.append( NewNode(newnode, newnodetype, edge_pred_and_qual, newnode_is, newnode_name) )

    def apply_(self, nodeset, graph, graph_index, patch_no):

        all_new_answers = []
        graph, all_extra_k_edges, graph_index = self.update_kg_(graph, graph_index)

        if all_extra_k_edges:
            for node_no, extra_k_edges in enumerate(all_extra_k_edges):
                answer = self.create_resullt(extra_k_edges, nodeset)
            all_new_answers.extend(answer)

        return all_new_answers, graph, graph_index

    def create_resullt(self, extra_k_edges, nodeset):
        answer = {}
        result = []
        for qg_edge in nodeset.get('answer_edge'):
            answer['node_bindings'] = {self.qg_id: [{'id': curie, 'qnode_id': curie, 'attributes': []} for curie in self.set_curies],
                                     nodeset.get('answer_id', 'answer'): [{'id': newnode.newnode} for newnode in
                                                                          self.added_nodes]}
            answer['analyses'] = [{"resource_id": "infores:automat-robokop",
                                   "edge_bindings": {
                                       qg_edge: [
                                           {
                                               "id": kedge
                                           } for kedge in extra_k_edges
                                       ]
                                   },
                                   "score": 0.
                                   }]
            answer['analyses'][0].update(self.new_props)
            result.append(answer)
        return result

    def update_kg_(self, kg, kg_index):
        if not kg:
            kg['nodes'] = {}
            kg['edges'] = {}

        if len(kg_index) == 0:
            kg_index['nodes'] = set(kg.get('nodes', {}).keys())
            kg_index['edges'] = {(edge['subject'], edge['object'], edge['predicate']): edge_id for edge_id, edge in
                                 kg.get('edges', {}).items()}
        all_extra_edges = []
        for newnode in self.added_nodes:
            extra_edges = []
            # See if the newnode is already in the KG, and if not, add it.
            found = False
            if newnode.newnode not in kg_index['nodes']:
                if not isinstance(newnode.newnode_type, list):
                    newnode.newnode_type = [newnode.newnode_type]

                kg['nodes'].update(
                    {newnode.newnode: {'name': newnode.newnode_name, 'categories': newnode.newnode_type, 'attributes': []}})
                kg_index['nodes'].add(newnode.newnode)


            # Add new edges
            for curie in self.set_curies:  # try to add a new edge from this curie to newnode
                if curie not in kg['nodes']:
                    kg['nodes'].update(
                        {curie: {'name': self.curies_names.get(curie), 'categories': self.curies_types.get(curie), 'attributes': []}}
                    )
                    kg_index['nodes'].add(curie)
                if curie == newnode.newnode:
                    continue  # no self edge please

                # check to see if the edge we want to add is already present in the kg
                if newnode.newnode_is == 'source':
                    source_id = newnode.newnode
                    target_id = curie
                else:
                    source_id = curie
                    target_id = newnode.newnode
                eid = None
                ekey = (source_id, target_id, newnode.new_edges)
                if ekey not in kg_index['edges']:
                    try:
                        provs = self.provmap[f'{source_id} {newnode.new_edges} {target_id}']
                    except KeyError:
                        provs = []
                    edge_def = ast.literal_eval(newnode.new_edges)

                    sources = []
                    for prov in provs:
                        source1 = {'resource_id': 'infores:automat-robokop',
                                   'resource_role': 'aggregator_knowledge_source'}
                        source2 = {'resource_id': 'infores:aragorn', 'resource_role': 'aggregator_knowledge_source'}
                        source1['upstream_resource_ids'] = [prov.get('resource_id', None)]
                        source2['upstream_resource_ids'] = [source1.get('resource_id', None)]
                        sources.extend([source1, source2])
                    source_pov = provs + sources

                    edge = {'subject': source_id, 'object': target_id, 'predicate': edge_def["predicate"],
                            'sources': source_pov, 'attributes': []}

                    if len(edge_def) > 1:
                        edge["qualifiers"] = [{"qualifier_type_id": f"biolink:{ekey}", "qualifier_value": eval}
                                              for ekey, eval in edge_def.items() if not ekey == "predicate"]
                    # Need to make a key for the edge, but the attributes & quals make it annoying
                    ek = deepcopy(edge)

                    ek['attributes'] = str(ek['attributes'])
                    ek['sources'] = str(ek['sources'])
                    if 'qualifiers' in ek:
                        ek['qualifiers'] = str(ek['qualifiers'])
                    eid = str(hash(frozenset(ek.items())))
                    kg['edges'].update({eid: edge})
                    kg_index['edges'][ekey] = eid
                eid = kg_index['edges'][ekey]
                extra_edges.append(str(eid))

            all_extra_edges.append(extra_edges)
        return kg, all_extra_edges, kg_index



class Answer:
    def __init__(self, json_answer, json_question, json_kg):
        """Take the json answer and turn it into a more usable structure"""
        # The answer has 2 parts:
        # 1. Node bindings
        # 2. Analyses
        #       a. a list of edge bindings, and
        #       b. Score
        # The edges may be asked for in the question, or they might be extras (support edges)
        # The node bindings can be in a variety of formats. In 1.0 they're all based on
        # "node_bindings": { "n0": [ { "id": "CHEBI:35475" } ], "n1": [ { "id": "MONDO:0004979" } ] },
        self.node_bindings = defaultdict(set)
        self.binding_properties = defaultdict(dict)
        self.enrichments = defaultdict(set)
        self.analyses = []
        self.aux_graph = defaultdict(lambda: defaultdict(list))


        # Node_bindings
        for qg_id, kg_bindings in json_answer['node_bindings'].items():
            kg_ids = set([x['id'] for x in kg_bindings ])
            # kg_ids = set([x[id] for x in kg_bindings for id in x])#To retain both the id and the qnode_id
            self.node_bindings[qg_id].update(kg_ids)
            self.binding_properties[qg_id] = defaultdict(dict)

        # Analyses, edge_bindings and other properties
        self.support_edge_bindings = defaultdict(set)

        question_edge_ids = set(json_question['edges'].keys())

        # Using this to save up the qnode_id in addition to the id
        self.question_node_ids = [value['ids'][0] for _, value in json_question['nodes'].items() if value.get('ids')]

        self.question_node = [key for key, value in json_question['nodes'].items() if value.get('ids')]

        #resource_id keep throwing error because of null value so i am using a temporary place holder
        placeholder = 'infores:automat-robokop'
        self.enrichments.update({'edges': defaultdict(set)})

        question_edge_bindings = defaultdict(set)

        for analysis in json_answer['analyses']:
            for qg_id, kg_bindings in analysis['edge_bindings'].items():
                kg_ids = set(x['id'] for x in kg_bindings)
                if qg_id in question_edge_ids:
                    question_edge_bindings[qg_id].update(kg_ids)
                else:
                    self.support_edge_bindings[ qg_id].update(kg_ids)
                self.binding_properties[qg_id] = defaultdict(dict)
            self.analyses.append(
                {'resource_id': analysis.get('resource_id', placeholder),
                 'edge_bindings': question_edge_bindings,
                 'score': analysis.get('score', 0.)})

    def get_auxiliarygraph(self):
        graph = {}
        for k, v in self.aux_graph.items():
            graph.update({k:v})
        return graph

    #
    def to_json(self):
        """Serialize the answer back to ReasonerStd JSON 1.0"""
        json_node_bindings = { q : [ {"id": kid, "attributes": []} for kid in k ] for q,k in self.node_bindings.items() }

        # Initially the edge bindings have qnode_id, rewrite them in the node_bindings
        for q_node, q_nodeid in zip(self.question_node, self.question_node_ids):
            if q_node in json_node_bindings:
                json_node_bindings[q_node][0]["qnode_id"] = q_nodeid

        json_analyses = [ {'resource_id':analysis['resource_id'],
                           'edge_bindings': {key:[{"id": list(value)[0], "attributes":[]}]  for key, value in analysis['edge_bindings'].items()},
                            'score': analysis['score']
                    }
                        for analysis in self.analyses
                ]
        for analysis in json_analyses:
            analysis['edge_bindings'].update({q: [{"id": kid, "attributes": []} for kid in k] for q, k in self.support_edge_bindings.items()})

        json_enrichments = [eb_dict for eb_dict in self.enrichments['edges'] ]

        return {'node_bindings': json_node_bindings, 'analyses': json_analyses, 'enrichments':json_enrichments}

    #TODO: This is not including edges, which is bad.  But I think it should work if the bindings are made right.
    def make_bindings(self):
        """Return a single bindings map, making sure that the same id is not
        used for both node and edge. Also remove any edge_bindings that are not part of the question, such
        as support edges"""
        #Check for malformed questions: are the qg_id's unique across edges and nodes
        # if len( set(self.node_bindings.keys()).intersection( set(keys for anl in self.analyses for keys in anl['edge_bindings'].keys()))) > 0:
        #     print('Invalid Question; shares identifiers across nodes and edges in the question')
        if len(set(self.node_bindings.keys()).intersection(
                set(keys for anl in self.analyses for keys in anl['edge_bindings'].keys()))) > 0:
            print('Invalid Question; shares identifiers across nodes and edges in the question')

        if len(set(self.node_bindings.keys()).intersection(set(self.support_edge_bindings.keys()))) > 0:
            print('Invalid Question; shares identifiers across nodes and edges in the question')
        combined_bindings = {}
        one_result = {'node_bindings': self.node_bindings,
              'analyses': self.analyses,
              'enrichments': self.enrichments}
        combined_bindings.update(one_result)
        return combined_bindings

    def add_properties(self, qg_id, bps, counter):
        """Update the property map of element qg_id with the properties in bps"""
        self.binding_properties[qg_id].update(bps)
        self.aux_graph[f'_e_ac_{counter}'].update(bps)

    def add_bindings(self, extra_k_edges, counter):
        self.enrichments['edges'][f'_e_ac_{counter}'].update(extra_k_edges)
        self.aux_graph[f'_e_ac_{counter}']['edges'].extend(extra_k_edges)

    def add_property_bindings(self, extra_k_edges, qg_id, bps, counter):
        self.enrichments['edges'][f'_n_ac_{counter}'].update(extra_k_edges)
        self.aux_graph[f'_n_ac_{counter}']['edges'].extend(extra_k_edges)
        self.binding_properties[qg_id].update(bps)
        self.aux_graph[f'_n_ac_{counter}'].update(bps)

class GEnrichment:
    def __init__(self, kg, qg, auxg_edgeattributes, answer_qnode, log):
        self.kg = kg
        self.auxg_edgeattributes = auxg_edgeattributes
        self.knodes = self.kg['nodes']
        self.kedges = self.kg['edges']
        self.answer_qnode = answer_qnode
        self.logs = log
        self.qg_answercategory = self.get_qg_anwercategory(qg['nodes'])
        self.rule_index = {}


    def get_qg_anwercategory(self, qnodes):
        default = ["biolink:NamedEntity"]
        qg_answercategory = [qnode.get("categories", default) for qnode in qnodes.values() if not qnode.get("ids")]
        return qg_answercategory[-1] if qg_answercategory else default

    def make_rules(self, othertype= None):
        predicates_to_exclude = [
            "biolink:causes", "biolink:biomarker_for", "biolink:biomarker_for", "biolink:contraindicated_for",
            "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"
        ]

        messages = []
        enrichednode_ids, is_source, predicate, qualifiers = self.get_ac_edgeinfo(self.auxg_edgeattributes)
        if qualifiers and len(qualifiers)>=2:
            ekey = {(is_source, predicate, qualifiers[0].get("qualifier_value", ""),
                      qualifiers[1].get("qualifier_value", "")): enrichednode_ids}
        else:
            ekey = {(is_source, predicate):enrichednode_ids}
        ekey = tuple(ekey.items())
        if predicate not in predicates_to_exclude or ekey not in self.rule_index:
            enrichednode_category = self.get_node_category(enrichednode_ids)
            query_template = Template(qg_template())
            if is_source:
                source_type = [enrichednode_category]
                source = enrichednode_category.split(":")[1].lower()
                if othertype:
                    #wanna make a room for disease to disease trapi query
                    target_type = [othertype]
                else:
                    target_type = self.qg_answercategory
                # target_type = self.qg_answercategory
                target = self.answer_qnode
                # if the enriched node is the source node in the kg, then it becomes the object node in the templated query
                qs = query_template.substitute(source=source, target=target, source_id=enrichednode_ids, target_id="",
                                               source_category=json.dumps(source_type),
                                               target_category=json.dumps(target_type), predicate=predicate,
                                               qualifiers=json.dumps(qualifiers))
            else:
                if othertype:
                    #wanna make a room for disease to disease trapi query
                    source_type = [othertype]
                else:
                    source_type = self.qg_answercategory
                # source_type = self.qg_answercategory
                source = self.answer_qnode
                target_type = [enrichednode_category]
                target = enrichednode_category.split(":")[1].lower()
                qs = query_template.substitute(source=source, target=target, target_id=enrichednode_ids, source_id="",
                                               source_category=json.dumps(source_type),
                                               target_category=json.dumps(target_type), predicate=predicate,
                                               qualifiers=json.dumps(qualifiers))
            query = json.loads(qs)
            if is_source:
                del query["query_graph"]["nodes"][target]["ids"]
            else:
                del query["query_graph"]["nodes"][source]["ids"]
            message = {"message": query}
            if self.logs:
                message["logs"] = self.logs
            messages.append(message)
            self.rule_index[ekey]= enrichednode_ids
        return messages

    def get_ac_edgeinfo(self, enriched_edge_attributes):

        is_source = None
        enriched_node = None
        object_aspect_qualifier = None
        object_direction_qualifier = None
        predicate_value = None
        direction = {'biolink:object': False, 'biolink:subject': True}

        for attrib in enriched_edge_attributes:
            attribute_type = attrib["attribute_type_id"]
            value = attrib["value"]

            if attribute_type in ("biolink:object", "biolink:subject"):
                enriched_node = value
                is_source = direction.get(attribute_type)
            elif attribute_type == "biolink:predicate":
                predicate_value = value
            elif attribute_type == "biolink:object_aspect_qualifier":
                object_aspect_qualifier = value
            elif attribute_type == "biolink:object_direction_qualifier":
                object_direction_qualifier = value

        qualifiers = []
        if object_aspect_qualifier is not None:
            qualifiers.append({
                "qualifier_type_id": "biolink:object_aspect_qualifier",
                "qualifier_value": object_aspect_qualifier
            })
        if object_direction_qualifier is not None:
            qualifiers.append({
                "qualifier_type_id": "biolink:object_direction_qualifier",
                "qualifier_value": object_direction_qualifier
            })

        return enriched_node, is_source, predicate_value, qualifiers

    def get_node_category(self, node):
        # We are assuming the most probable type is the first item in the category/label list
        return self.knodes[node].get('categories', [])[0]

    def get_ac_input_category(self, input_ids):
        input_category = self.get_input_category(input_ids)
        return input_category

# class PEnrichment:
#     def __init__(self,json_answer, kg, qg, question_qnode, answer_qnode, auxgraph):
#         self.node_bindings = json_answer['node_bindings']
#         self.enrichments = json_answer['enrichments']
#         self.analyses = json_answer['analyses']
#         self.auxiliary_graphs = auxgraph
#         self.kg = kg
#         self.question_qnode = question_qnode
#         self.answer_qnode = answer_qnode
#         self.question_edge_ids = next(iter(set(qg['edges'].keys())))   #eg 'e00'
#         self.original_predicate = [qg['edges'][edge]['predicates'][0] for edge in qg['edges']][0] #eg biolink:treats
#         # Using this to save up the qnode_id in addition to the id
#         # EG:'MONDO:1234'
#         self.question_qnode_ids = qg['nodes'][question_qnode]['ids'][0]
#         # EG: 'disease'
#
#         self.qg_answercategory = self.get_qg_anwercategory(qg['nodes'])
#
#     def get_qg_anwercategory(self, qnodes):
#         default = ["biolink:NamedEntity"]
#         qg_answercategory = [qnode.get("categories", default) for qnode in qnodes.values() if not qnode.get("ids")]
#         return qg_answercategory[-1] if qg_answercategory else default
#
#     def update_kg_and_binding(self, enrichment):
#         kg_index = {}
#         if len(kg_index) == 0:
#             kg_index['nodes'] = set( self.kg['nodes'].keys() )
#             kg_index['edges'] = { (edge['subject'],edge['object'],edge['predicate']):edge_id for edge_id,edge in self.kg['edges'].items() }
#         result_bindings = []
#         for newnode in (self.new_nodes):
#             for nnkey, _ in newnode.items():
#                 #See if the newnode is already in the KG, and if not, add it.
#                 if nnkey in kg_index['nodes']:
#                     continue
#                 self.kg['nodes'].update(newnode)
#                 kg_index['nodes'].add(nnkey)
#                 source_id = nnkey
#                 target_id = self.question_qnode_ids
#                 ekey = (source_id, target_id, self.original_predicate)
#                 if ekey not in kg_index['edges']:
#                     edge = {'subject': source_id, 'object': target_id, 'predicate': self.original_predicate,
#                         'sources': [self.add_provenance()], 'attributes': [{'attribute_type_id': "biolink:support_graphs", "value": [enrichment]}]}
#                     ek = deepcopy(edge)
#                     ek['sources'] = str(ek['sources'])
#                     ek['attributes'] = str(ek['attributes'])
#                     eid = self.makehash(str(ek))
#                     self.kg['edges'].update({eid: edge})
#                     kg_index['edges'][ekey] = eid
#                     if self.add_binding(nnkey, eid):
#                         result_bindings.append(self.add_binding(nnkey, eid))
#                     # else:
#                 else:
#                     edgeid = kg_index['edges'].get(ekey)
#                     self.add_support_edge(self, edgeid, enrichment)
#
#         return result_bindings
#
#         # result binding
#     def add_binding(self, nnkey, eid):
#         binding = None
#         if nnkey == self.node_bindings[self.answer_qnode][0]['id']:
#             self.analyses[0]['edge_bindings'][self.question_edge_ids].append({'id':eid})
#         else:
#             binding = {
#                 "node_bindings": {
#                     self.answer_qnode: [
#                         {
#                             "id": nnkey
#                         }
#                     ],
#                     self.question_qnode: [
#                         {
#                             "id": self.question_qnode_ids,
#                             "qnode_id": self.question_qnode_ids
#                         }
#                     ]
#                 },
#                 "analyses": [
#                     {
#                         "resource_id": "infores:aragorn",
#                         "edge_bindings": {
#                             self.question_edge_ids: [
#                                 {
#                                     "id": eid
#                                 }
#                             ]
#                         }
#                     }
#                 ]
#             }
#         return binding
#
#     def makehash(self, text):
#         return hashlib.sha256(text.encode('utf-8')).hexdigest()
#
#     def add_support_edge(self, edgeid, enrichment):
#         self.kg['edge'][edgeid]['attributes'][0]['value'].append(enrichment)
#
#     def add_provenance(self):
#         provmap = {"resource_id": "infores:aragorn", "resource_role": "aggregator_knowledge_source",
#                           "upstream_resource_ids": ["infores:automat-aragorn"]}
#         return provmap
#
#     def get_property_creativeresult(self, enrichment, property, guid):
#         '''
#         param: Enriched_node property -> 'CHEBI_Role_Drug'
#         Return: neo4j nodes having such property -> .json()
#         '''
#         automat_url = 'https://automat.renci.org/robokopkg/cypher'
#         logger.info(f"{guid}:Calling {automat_url} for enriched property creative lookup")
#
#         try:
#             query = {"query": "MATCH (n:`%s` {`%s`:True}) RETURN n AS nodes, labels(n) AS labels" % (
#             self.qg_answercategory[0], property[0])}
#             pe_response = requests.post(automat_url, json=query).json()
#
#             if pe_response['results'][0]['data']:
#                 # 1. Format the neo4j result as node data
#                 self.new_nodes = [self.format_node_data(res['row']) for res in pe_response['results'][0]['data']]
#                 logger.info(f'Cypher query run for ({property}) complete, found {len(self.new_nodes)} results')
#                 # 2. update kg with the new node and make edges; then format the new result as pydantic result
#                 result_bindings = self.update_kg_and_binding(enrichment)
#                 return result_bindings, 200
#         except Exception as e:
#             # Do not come here
#             logger.exception(f"{guid}: Exception {e} posting property enriched to {automat_url}")
#             return {}, 500
#
#     def format_node_data(self, newnode):
#         '''
#         params: Raw node data from neo4j
#         Return: Coalesced formated node
#         '''
#         if isinstance(newnode[0], str):
#             # if the format is 'CHEBI_ROLE_drug', create the node data
#             return {newnode[0]: {'categories': [],
#                               'name': None,
#                               'attributes': [{'attribute_type_id': 'biolink:same_as',
#                                               'value': None, 'value_type_id': 'metatype:uriorcurie',
#                                               'original_attribute_name': None
#                                               }]
#                               }
#                     }
#         if isinstance(newnode[0], dict):
#             # if the format is {'id': 'NCBIGene003', 'name': 'TestingGene', 'tpsa': '2', ...}, from neo4j
#             # create node data with the neo4j graph node properties
#             ids = newnode[0].pop('id')
#             name = newnode[0].pop('name')
#             return {ids: {'categories': newnode[1],
#                           'name': name,
#                           'attributes': [{'attribute_type_id': 'biolink:same_as',
#                                           'value': v, 'value_type_id': 'metatype:uriorcurie',
#                                           'original_attribute_name': k
#                                           } if k == 'equivalent_identifiers'
#                                          else {'attribute_type_id': 'biolink:Attribute',
#                                                'value': v, 'value_type_id': 'EDAM:data_0006',
#                                                'original_attribute_name': k
#                                                }
#                                          for k, v in newnode[0].items()
#                                          ]
#                           }
#                     }

def qg_template():
    return '''{
        "query_graph": {
            "nodes": {
                "$source": {
                    "ids": [
                        "$source_id"
                    ],
                    "categories": 
                        $source_category

                },
                "$target": {
                    "ids": [
                        "$target_id"
                    ],
                    "categories": 
                        $target_category
                }
            },
            "edges": {
                "e00": {
                    "subject": "$source",
                    "object": "$target",
                    "predicates": [
                        "$predicate"
                    ],
                    "qualifier_constraints": [
                        {
                            "qualifier_set": $qualifiers
                        }
                    ]
                }
            }
        }
    }
'''