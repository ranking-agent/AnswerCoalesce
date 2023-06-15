from copy import deepcopy
from collections import defaultdict
import ast

class Opportunity:
    def __init__(self,hash, qg, kg, a_i, ai2kg):
        """
        Define a coalescent opportunity by a hash (the fixed parts of the answers)
        qg: a (qg_id, semantic type) pair
        kg: kg_ids allowed for the combined answers
        a_i: indices into the results saying which answers are combined to give this
             opportunity
        kg2a_i: dict mapping frozenset of kg -> which answer they appear in.  Used to filter.
        """
        self.answer_hash = hash
        self.qg_id = qg[0]
        self.qg_semantic_type = qg[1]
        self.kg_ids = kg
        self.answer_indices = a_i
        self.answerid2kg = ai2kg
    def get_kg_ids(self):
        return self.kg_ids
    def get_qg_id(self):
        return self.qg_id
    def get_qg_semantic_type(self):
        stype = self.qg_semantic_type
        if isinstance(stype, list):
            stype = stype[0]
        return stype
    def get_answer_indices(self):
        return self.answer_indices
    def filter(self,new_kg_ids):
        """We constructed the opportunities without regard to what nodes we have data on.  Now, we want to filter
        this opportunity to only answers where we actually have info about the nodes.
        new_kg_ids is a subset of self.kg_ids.  If we have an answer where we don't have all the nodes, we want to
        get rid of that answer, and return a new (filtered) opp.  If we get rid of all answers, return None"""
        if len(new_kg_ids) == len(self.kg_ids):
            #No filtering required
            return self
        nkgids = set(new_kg_ids)
        new_ai2kg = {}
        for answer_i, kgs in self.answerid2kg.items():
            keep = True
            for kg_i in kgs:
                if kg_i not in nkgids:
                    keep = False
                    break
            if keep:
                new_ai2kg[answer_i] = kgs
        if len(new_ai2kg) == 0:
            return None
        #If we removed any answers, we might also need to remove some kg_ids that weren't explicitly filtered
        final_kg_ids = set()
        for kgi in new_ai2kg.values():
            final_kg_ids.update(kgi)
        return Opportunity(self.answer_hash, (self.qg_id , self.qg_semantic_type ), list(final_kg_ids), list(new_ai2kg.keys()), new_ai2kg)

class NewNode:
    def __init__(self,newnode, newnodetype, edge_pred_and_qual, newnode_is, newnode_name):
        self.newnode = newnode
        self.newnode_type = newnodetype
        self.new_edges = edge_pred_and_qual
        self.newnode_is = newnode_is
        self.newnode_name = newnode_name


class PropertyPatch:
    def __init__(self,qg_id,curies,props,answer_ids):
        self.qg_id = qg_id
        self.set_curies = curies
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
    def apply(self,answers,question,graph,graph_index,patch_no):
        # Find the answers to combine.  It's not necessarily the answer_ids.  Those were the
        # answers that were originally in the opportunity, but we might have only found commonality
        # among a subset of them
        all_new_answers =[]
        possible_answers = [answers[i] for i in self.answer_indices]
        comb_answers = [a for a in possible_answers if self.isconsistent(a)]
        #This can happen for weird inputs like double bound nodes
        if len(comb_answers) < 2:
            return None,question,graph,graph_index
        #Modify the question graph and the knowledge graph
        #If we're not adding a new node, extra_q_node = None, extra_q_edges = extra_k_edges =[]. No bindings to add
        #If we have an added node, the added node is always self.newnode
        # Also we will have an extra_q_node in that case, as well as one extra_q_edge, and 1 or more new k_edges
        #question,extra_q_nodes,extra_q_edges = self.update_qg(question)
        graph,all_extra_k_edges,graph_index = self.update_kg(graph,graph_index)


        for new_answer in comb_answers:
            new_answer.add_properties(self.qg_id,self.new_props)
            for node_no, (newnode, extra_k_edges) in enumerate(zip(self.added_nodes, all_extra_k_edges)):
                new_answer.add_bindings([newnode.newnode], extra_k_edges, f'{patch_no}_{node_no}')

            all_new_answers.append(new_answer)

        return all_new_answers, question, graph, graph_index
    def isconsistent(self, possibleanswer):
        """
        The patch is constructed from a set of possible answers, but it doesn't have to use all
        of them.  Checks to see if this answer is one of the ones that is still part of
        the patch.
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

                kg['nodes'].update({ newnode.newnode:{'name': newnode.newnode_name, 'categories': newnode.newnode_type}})
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
                        prov = self.provmap[ f'{source_id} {newnode.new_edges} {target_id}']
                    except KeyError:
                        prov = []

                    #newnode.new_edges is a string containing a dict like
                    #{"predicate": "biolink:affects", "object_aspect_qualifier":"transport"}
                    edge_def = ast.literal_eval(newnode.new_edges)

                    edge = { 'subject': source_id, 'object': target_id, 'predicate': edge_def["predicate"],
                             'attributes': prov + [{'attribute_type_id':'biolink:aggregator_knowledge_source','value':'infores:aragorn'},
                                            {'attribute_type_id':'biolink:aggregator_knowledge_source','value':'infores:automat-robokop'}]}
                    if len(edge_def) > 1:
                        edge["qualifiers"] = [ {"qualifier_type_id": f"biolink:{ekey}", "qualifier_value": eval}
                                               for ekey, eval in edge_def.items() if not ekey == "predicate"]
                    #Need to make a key for the edge, but the attributes & quals make it annoying
                    ek = deepcopy(edge)
                    ek['attributes'] = str(ek['attributes'])
                    if 'qualifiers' in ek:
                        ek['qualifiers'] = str(ek['qualifiers'])
                    eid = str(hash(frozenset(ek.items())))
                    kg['edges'].update({eid:edge})
                    kg_index['edges'][ekey] = eid
                eid = kg_index['edges'][ekey]
                extra_edges.append(str(eid))
            all_extra_edges.append(extra_edges)
        return kg,all_extra_edges,kg_index

class Answer:
    def __init__(self,json_answer,json_question,json_kg):
        """Take the json answer and turn it into a more usable structure"""
        #The answer has 3 parts:  Score, a list of node bindings, and a list of edge bindings
        # The edges may be asked for in the question, or they might be extras (support edges)

        self.binding_properties = defaultdict(dict)
        #The node bindings can be in a variety of formats. In 1.0 they're all based on
        #"node_bindings": { "n0": [ { "id": "CHEBI:35475" } ], "n1": [ { "id": "MONDO:0004979" } ] },
        self.node_bindings = defaultdict(set)
        self.enrichment_result = []
        self.analyses = []
        for qg_id,kg_bindings in json_answer['node_bindings'].items():
            kg_ids = set( [x['id'] for x in kg_bindings] )
            self.node_bindings[ qg_id ].update(kg_ids)
            #Not sure that this is important re: 1.0?
            #props = { k:v for k,v in nb.items() if k not in ('qg_id','kg_id')}
            #self.binding_properties[nb['qg_id']] = props
            self.binding_properties[qg_id] = defaultdict(dict)

        question_edge_ids = set(json_question['edges'].keys())
        question_edge_bindings = defaultdict(set)
        support_edge_bindings = defaultdict(set)
        if 'score' in json_answer['analyses'] and json_answer['analyses'].get('score'):
            score = json_answer['analyses'].get('score')
        else:
            score = 0.
        self.analyses.append({'score':score, "attributes":[], 'edge_bindings':json_answer['analyses'][0].get('edge_bindings')})
        self.enrichment_result.append({'edges': [], 'attributes': defaultdict(set), 'enriched_node': {}})

        for analysis in json_answer['analyses']:
            kg_bindings = analysis['edge_bindings']
            for qg_id, bindings in kg_bindings.items():
                kg_ids = set(x['id'] for x in bindings)
                if qg_id in question_edge_ids:
                    question_edge_bindings[qg_id].update(kg_ids)
                    self.analyses[0]['edge_bindings'] = question_edge_bindings
                else:
                    support_edge_bindings[qg_id].update(kg_ids)
                    self.enrichment_result.append({'edges':support_edge_bindings})
                self.binding_properties[qg_id] = defaultdict(dict)

    def to_json(self):
        """Serialize the answer back to ReasonerStd JSON 1.0"""
        json_node_bindings = { q : [ {"id": kid} for kid in k ]  for q,k in self.node_bindings.items() }
        json_analyses = [ { 'edge_bindings': {{"id": key}: value for key, value in item['edge_bindings'].items()},
                            'score': item['score'], 'attributes': item['attributes'] }
                            for item in self.analyses
                        ]
        json_enrichment_result = [ {'edges': [{eb_key: [{"id": eb} for eb in eb_dict[eb_key]]for eb_dict in item['edges'] for eb_key in eb_dict}],
                                    'attributes': item['attributes'],
                                    'enriched_node': { key: [{"id": val} for val in item['enriched_node'][key]] for key in item['enriched_node']}
                                    } for item in self.enrichment_result
                                ]
        # chk = self.binding_properties
        for (qg_id,_), enr in zip(json_node_bindings.items(), json_enrichment_result):
                enr['attributes'].update(dict(self.binding_properties[qg_id]))

        return { 'node_bindings': json_node_bindings, 'analyses': json_analyses, 'enrichment_result':json_enrichment_result}
    #TODO: This is not including edges, which is bad.  But I think it should work if the bindings are made right.
    def make_bindings(self):
        """Return a single bindings map, making sure that the same id is not
        used for both a node and edge. Also remove any edge_bindings that are not part of the question, such
        as support edges"""

        #Check for malformed questions: are the qg_id's unique across edges and nodes
        if len( set(self.node_bindings.keys()).intersection( set(keys for anl in self.analyses for keys in anl['edge_bindings'].keys()))) > 0:
            print('Invalid Question; shares identifiers across nodes and edges in the question')
        if len( set(self.node_bindings.keys()).intersection( set(item.keys() for enrichment_rslt in self.enrichment_result for item in enrichment_rslt['edges']))) > 0:
            print('Invalid Question; shares identifiers across nodes and edges in the question')
        combined_bindings = {}
        one_result = {'node_bindings': self.node_bindings,
              'analyses': self.analyses,
              'enrichment_result': self.enrichment_result}
        combined_bindings.update(one_result)
        return combined_bindings
    def update(self,other_answer):
        """Add bindings from the other answer to this one. Creates a combined answer."""
        for k,v in other_answer.node_bindings.items():
            self.node_bindings[k].update(v)
        for k, v in other_answer.question_edge_bindings.items():
            self.question_edge_bindings[k].update(v)
        for k, v in other_answer.support_edge_bindings.items():
            self.support_edge_bindings[k].update(v)
        #this one might not be right since it's nested...
        for k, v in other_answer.binding_properties.items():
            self.binding_properties[k].update(v)
    def add_properties(self,qg_id,bps):
        """Update the property map of element qg_id with the properties in bps"""
        self.binding_properties[qg_id].update(bps)
    def add_bindings(self, newnode, extra_k_edges,counter):
        for enr in self.enrichment_result:
            enr.get('edges', []).append({f'_e_ac_{counter}':extra_k_edges})
            enr.get('enriched_node', {}).setdefault(f'_n_ac_{counter}', set()).update(newnode)



