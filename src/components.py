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

class PropertyPatch:
    def __init__(self,qg_id,curies,props,answer_ids):
        self.qg_id = qg_id
        self.set_curies = curies
        self.new_props = props
        self.answer_indices = answer_ids
    def apply(self,answers):
        #First, find the answers to combine.  It's not necessarily the answer_ids.  Those were the
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
        return new_answer
#    def add_answer(self,target_answer,source_answer):
#        """
#        Given two answers, copy bindings from the source_answer to the target_answer.
#        """
#        node_bindings = target_answer.node_bindings
#        #Replace the relevant node binding, adding the new properties
#        for nb in node_bindings:
#            if nb['qg_id'] == self.qg_id:
#                nb['kg_id'] = self.set_curies
#                nb.update(self.new_props)
#        #Now, figure out which edges we need.  We essentially need every edge from
#        # any answer that matches
#        for possibleanswer_i in self.answer_indices:
#            possibleanswer = answers[possibleanswer_i]
#            if self.isconsistent(possibleanswer):
#                add_edge_bindings(new_answer,possibleanswer)
#        new_answers.append(new_answer)
#        return new_answers
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

#def add_edge_bindings(newanswer, panswer):
#    """Update an answer with edges from the patch"""
#    original_bindings = {x['qg_id']: x['kg_id'] for x in newanswer['edge_bindings']}
#    for eb in panswer['edge_bindings']:
#        eb_q = eb['qg_id']
#        eb_k = eb['kg_id']
#        ebl = [x for x in newanswer['edge_bindings'] if x['qg_id'] == eb_q]
#        if len(ebl) == 0:
#            newanswer['edge_bindings'].append({'qg_id': eb_q, 'kg_id': eb_k})
#        else:
#            eb = ebl[0]
#            ebk = eb_k[0]
#            if ebk not in eb['kg_id']:
#                eb['kg_id'].append(ebk)

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
        """Add bindings from the other answer to this one."""
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
        self.binding_properties[qg_id].update(bps)




