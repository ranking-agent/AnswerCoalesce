import requests

class RobokopMessenger:
    def __init__(self):
        self.url = 'http://robokop.renci.org:4868'
    def pipeline(self,request,yank = True):
        #normalize question
        response = requests.post( f'{self.url}/normalize', json=request )
        normalized = response.json()
        #answer question
        request = { 'message': normalized, }
        response = requests.post( f'{self.url}/answer', json=request )
        answered = response.json()
        if not yank:
            return answered
        #Yank
        request = { 'message': answered, }
        response = requests.post( f'{self.url}/yank', json=request )
        filled = response.json()
        return filled
    def get_links_for(self,curie,stype):
        query = { 'nodes': [{'id': 'n0', 'curie':curie, 'type': stype},
                            {'id': 'n1'}],
                  'edges': [{'id': 'e0', 'source_id': 'n0', 'target_id': 'n1'}]}
        request = { "message": { "query_graph": query } }
        result = self.pipeline(request)
        kg = result['knowledge_graph']
        #This kg should be a star, centered on "curie".  Just walk its edges.
        links = []
        for edge in kg['edges']:
            source = (edge['source_id'] == curie)
            if source:
                other_node = edge['target_id']
            else:
                other_node = edge['source_id']
            predicate = edge['type']
            link = (other_node,predicate,source)
            links.append(link)
        return links
    def get_total_nodecount(self, newcurie, predicate, newcurie_is_source, semantic_type):
        query = { 'nodes': [{'id': 'n0', 'curie':newcurie},
                            {'id': 'n1', 'type': semantic_type}] }
        if newcurie_is_source:
            query['edges'] = [{'id': 'e0', 'source_id': 'n0', 'target_id': 'n1', 'type': predicate}]
        else:
            query['edges'] = [{'id': 'e0', 'source_id': 'n1', 'target_id': 'n0', 'type': predicate}]
        request = { "message": { "query_graph": query } }
        result = self.pipeline(request,yank = False)
        #Just need to know how many
        return len(result['results'])
