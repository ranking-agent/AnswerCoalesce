from copy import deepcopy

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
        new_answers = []
        #First, find an answer that we want to patch.  It needs to be consistent
        for possibleanswer_i in self.answer_indices:
            possibleanswer = answers[possibleanswer_i]
            if self.isconsistent(possibleanswer):
                base_answer = possibleanswer
        #Start with some answer
        new_answer = deepcopy(base_answer)
        node_bindings = new_answer['node_bindings']
        #Replace the relevant node binding, adding the new properties
        for nb in node_bindings:
            if nb['qg_id'] == self.qg_id:
                nb['kg_id'] = self.set_curies
                nb.update(self.new_props)
        #Now, figure out which edges we need.  We essentially need every edge from
        # any answer that matches
        for possibleanswer_i in self.answer_indices:
            possibleanswer = answers[possibleanswer_i]
            if self.isconsistent(possibleanswer):
                add_edge_bindings(new_answer,possibleanswer)
        new_answers.append(new_answer)
        return new_answers
    def isconsistent(self, possibleanswer):
        """
        The patch is constructed from a set of possible nodes, but it doesn't have to use all
        of them.  Checks to see if this answer is one of the ones that is still part of
        the patch.
        """
        # needs work if sets are allowed
        nb_possible = possibleanswer['node_bindings']
        kg_ids_possible = [x['kg_id'][0] for x in nb_possible if x['qg_id'] == self.qg_id]
        kg_id_possible = kg_ids_possible[0]
        return kg_id_possible in self.set_curies

def add_edge_bindings(newanswer, panswer):
    """Update an answer with edges from the patch"""
    original_bindings = {x['qg_id']: x['kg_id'] for x in newanswer['edge_bindings']}
    for eb in panswer['edge_bindings']:
        eb_q = eb['qg_id']
        eb_k = eb['kg_id']
        ebl = [x for x in newanswer['edge_bindings'] if x['qg_id'] == eb_q]
        if len(ebl) == 0:
            newanswer['edge_bindings'].append({'qg_id': eb_q, 'kg_id': eb_k})
        else:
            eb = ebl[0]
            ebk = eb_k[0]
            if ebk not in eb['kg_id']:
                eb['kg_id'].append(ebk)


