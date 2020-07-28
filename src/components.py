from copy import deepcopy
from collections import defaultdict

class Opportunity:
    def __init__(self,hash, qg, kg, a_i):
        """
        Define a coalescent opportunity by a hash (the fixed parts of the answers)
        qg: a (qg_id, semantic type) pair
        kg: kg_ids allowed for the combined answers
        a_i: indices into the results saying which answers are combined to give this
             opportunity
        """
        self.answer_hash = hash
        self.qg_id = qg[0]
        self.qg_semantic_type = qg[1]
        self.kg_ids = kg
        self.answer_indices = a_i
    def get_kg_ids(self):
        return self.kg_ids
    def get_qg_id(self):
        return self.qg_id
    def get_qg_semantic_type(self):
        return self.qg_semantic_type
    def get_answer_indices(self):
        return self.answer_indices

class NewNode:
    def __init__(self,newnode, newnodetype, edge_type, newnode_is):
        self.newnode = newnode
        self.newnode_type = newnodetype
        self.new_edges = edge_type
        self.newnode_is = newnode_is


class PropertyPatch:
    def __init__(self,qg_id,curies,props,answer_ids):
        self.qg_id = qg_id
        self.set_curies = curies
        self.new_props = props
        self.answer_indices = answer_ids
        self.added_nodes = []
    def add_extra_node(self,newnode, newnodetype, edge_type, newnode_is):
        """Optionally, we can patch by adding a new node, which will share a relationship of
        some sort to the curies in self.set_curies.  The remaining parameters give the edge_type
        of those edges, as well as defining whether the edge points to the newnode (newnode_is = 'target')
        or away from it (newnode_is = 'source') """
        self.added_nodes.append( NewNode(newnode, newnodetype, edge_type, newnode_is) )
    def apply(self,answers,question,graph):
        #Modify the question graph and the knowledge graph
        #If we're not adding a new node, extra_q_node = None, extra_q_edges = extra_k_edges =[]. No bindings to add
        #If we have an added node, the added node is always self.newnode
        # Also we will have an extra_q_node in that case, as well as one extra_q_edge, and 1 or more new k_edges
        question,extra_q_nodes,extra_q_edges = self.update_qg(question)
        graph,all_extra_k_edges = self.update_kg(graph)
        #Find the answers to combine.  It's not necessarily the answer_ids.  Those were the
        # answers that were originally in the opportunity, but we might have only found commonality
        # among a subset of them
        possible_answers = [answers[i] for i in self.answer_indices]
        comb_answers = [ a for a in possible_answers if self.isconsistent(a) ]
        #Start with some answer
        new_answer = deepcopy(comb_answers[0])
        #Add in the other answers
        for another_answer in comb_answers[1:]:
            new_answer.update(another_answer)
        #Add in any extra properties
        new_answer.add_properties(self.qg_id,self.new_props)
        #Add newnode-related bindings if necessary
        for newnode,extra_q_node,extra_q_edge,extra_k_edges in \
                zip(self.added_nodes,extra_q_nodes,extra_q_edges,all_extra_k_edges):
            new_answer.add_bindings(extra_q_node, [newnode.newnode], extra_q_edge, extra_k_edges)
        return new_answer, question, graph
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
        for node in qg['nodes']:
            if node['id'] == self.qg_id:
                node['set'] = True
        #We are going to want to know whether we have aleady added a particular new node/edge.  Then if we are
        # adding it again, we can say, nope, already did it. So let's collect what we have.
        added_nodes = []
        for edge in qg['edges']:
            if edge['id'].startswith('extra_'):
                if edge['source_id'].startswith('extra'):
                    itis = 'source'
                    qid = edge['source_id']
                    oid = edge['target_id']
                else:
                    itis = 'target'
                    qid = edge['target_id']
                    oid = edge['source_id']
                #it might be that the oid is not the same one for this patch
                if oid != self.qg_id:
                    continue
                for node in qg['nodes']:
                    if node['id'] == qid:
                        ntype = node['type']
                added_nodes.append( (set(ntype), itis) )
        for newnode in self.added_nodes:
            #First, we need to decide whether this new node is already in there.
            rep = (set(newnode.newnode_type), newnode.newnode_is)
            if rep in added_nodes:
                continue
            #Doesn't seem like it's already here, so Add the new node to the question.
            node_ids = [n['id'] for n in qg['nodes']]
            nnid = 0
            new_node_id = f'extra_qn_{nnid}'
            while new_node_id in node_ids:
                nnid += 1
                new_node_id = f'extra_qn_{nnid}'
            extra_q_nodes.append(new_node_id)
            qg['nodes'].append({'id': new_node_id, 'type': newnode.newnode_type})
            #Add the new edge to the question
            edge_ids = [ e['id'] for e in qg['edges']]
            neid = 0
            new_edge_id = f'extra_qe_{neid}'
            while new_edge_id in edge_ids:
                neid += 1
                new_edge_id = f'extra_qe_{neid}'
            if newnode.newnode_is == 'target':
                qg['edges'].append( {'id': new_edge_id, 'source_id': self.qg_id, 'target_id': new_node_id })
            else:
                qg['edges'].append( {'id': new_edge_id, 'source_id': new_node_id, 'target_id': self.qg_id })
            extra_q_edges.append(new_edge_id)
        return qg, extra_q_nodes, extra_q_edges
    def update_kg(self,kg):
        all_extra_edges = []
        for newnode in self.added_nodes:
            extra_edges=[]
            #See if the newnode is already in the KG, and if not, add it.
            found = False
            for node in kg['nodes']:
                if node['id'] == newnode.newnode:
                    found = True
                    break
            if not found:
                kg['nodes'].append( {'id': newnode.newnode, 'type': newnode.newnode_type})
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
                for edge in kg['edges']:
                    if edge['source_id'] == source_id:
                        if edge['target_id'] == target_id:
                            if edge['type'] == newnode.new_edges:
                                eid = str(edge['id'])
                                break
                if eid is None:
                    #Add the new edge
                    edge = { 'source_id': source_id, 'target_id': target_id, 'type': newnode.new_edges }
                    eid = str(hash(frozenset(edge.items())))
                    edge['id'] = eid
                    kg['edges'].append(edge)
                extra_edges.append(str(eid))
            all_extra_edges.append(extra_edges)
        return kg,all_extra_edges



class Answer:
    def __init__(self,json_answer,json_question,json_kg):
        """Take the json answer and turn it into a more usable structure"""
        #The answer has 3 parts:  Score, a list of node bindings, and a list of edge bindings
        # The edges may be asked for in the question, or they might be extras (support edges)
        self.score = json_answer['score']
        self.binding_properties = defaultdict(dict)
        #The node bindings can be in a variety of formats. They're all based on
        # { 'qg_id': "string", 'kg_id': ... }
        # The kg_id could be a string or a list of strings.  There could also be more than one binding wth the same qg_id
        self.node_bindings = defaultdict(set)
        for nb in json_answer['node_bindings']:
            if isinstance(nb['kg_id'],list):
                kg_ids = set(nb['kg_id'])
            else:
                kg_ids = set([nb['kg_id']])
            self.node_bindings[ nb['qg_id']].update(kg_ids)
            props = { k:v for k,v in nb.items() if k not in ('qg_id','kg_id')}
            self.binding_properties[nb['qg_id']] = props
        question_edge_ids = set([x['id'] for x in json_question['edges']])
        self.question_edge_bindings = defaultdict(set)
        self.support_edge_bindings = defaultdict(set)
        for eb in json_answer['edge_bindings']:
            if isinstance(eb['kg_id'],list):
                kg_ids = set(eb['kg_id'])
            else:
                kg_ids = set([eb['kg_id']])
            if eb['qg_id'] in question_edge_ids:
                self.question_edge_bindings[ eb['qg_id']].update(kg_ids)
            else:
                self.support_edge_bindings[ eb['qg_id']].update(kg_ids)
            props = { k:v for k,v in eb.items() if k not in ('qg_id','kg_id')}
            self.binding_properties[eb['qg_id']] = props
    def to_json(self):
        """Serialize the answer back to ReasonerStd JSON"""
        json_node_bindings = [ {'qg_id': q, 'kg_id': list(k)} for q,k in self.node_bindings.items() ]
        json_edge_bindings = [ {'qg_id': q, 'kg_id': list(k)} for q,k in self.question_edge_bindings.items() ]
        json_node_bindings += [ {'qg_id': q, 'kg_id': list(k)} for q,k in self.support_edge_bindings.items() ]
        for nb in json_node_bindings:
            nb.update(self.binding_properties[nb['qg_id']])
        for eb in json_edge_bindings:
            eb.update(self.binding_properties[nb['qg_id']])
        return { 'node_bindings': json_node_bindings, 'edge_bindings': json_edge_bindings, 'score':self.score}
    def make_bindings(self):
        """Return a single bindings map, making sure that the same id is not
        used for both a node and edge. Also remove any edge_bindings that are not part of the question, such
        as support edges"""
        #Check for malformed questions: are the qg_id's unique across edges and nodes
        if len( set(self.node_bindings.keys()).intersection( set(self.question_edge_bindings.keys()))) > 0:
            print('Invalid Question; shares identifiers across nodes and edges in the question')
        if len( set(self.node_bindings.keys()).intersection( set(self.support_edge_bindings.keys()))) > 0:
            print('Invalid Question; shares identifiers across nodes and edges in the question')
        combined_bindings = {}
        combined_bindings.update(self.node_bindings)
        combined_bindings.update(self.question_edge_bindings)
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
    def add_bindings(self,extra_q_node, newnode, extra_q_edge, extra_k_edges):
        self.node_bindings[extra_q_node].update(newnode)
        self.question_edge_bindings[extra_q_edge].update(extra_k_edges)




