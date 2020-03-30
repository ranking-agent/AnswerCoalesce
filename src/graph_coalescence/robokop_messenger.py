import os
import requests
import sqlite3


class RobokopMessenger:
    def __init__(self):
        self.url = 'http://robokop.renci.org:4868'

        # find the absolute directory we are in
        this_dir: str = os.path.dirname(os.path.realpath(__file__))

        # create the DB name
        self.db_name: str = f'{this_dir}/node_hit_count_lookup.db'

    def pipeline(self, request, yank=True):
        # normalize question
        response = requests.post(f'{self.url}/normalize', json=request)
        normalized = response.json()
        # answer question
        request = {'message': normalized}
        response = requests.post(f'{self.url}/answer', json=request)
        answered = response.json()
        if not yank:
            return answered

        # Yank
        request = {'message': answered}
        response = requests.post(f'{self.url}/yank', json=request)
        filled = response.json()
        return filled

    def get_links_for(self, curie, stype):
        query = {'nodes': [{'id': 'n0', 'curie': curie, 'type': stype}, {'id': 'n1'}],
                 'edges': [{'id': 'e0', 'source_id': 'n0', 'target_id': 'n1'}]}
        request = {"message": {"query_graph": query}}
        result = self.pipeline(request)
        kg = result['knowledge_graph']

        # This kg should be a star, centered on "curie".  Just walk its edges.
        links = []
        for edge in kg['edges']:
            source = (edge['source_id'] == curie)
            if source:
                other_node = edge['target_id']
            else:
                other_node = edge['source_id']
            predicate = edge['type']
            link = (other_node, predicate, source)
            links.append(link)
        return links

    def get_hit_node_count(self, newcurie: str, predicate: str, newcurie_is_source: bool, semantic_type: str) -> int:
        """ gets the number of nodes (loaded from the graph database into a local database)
            that share this node, predicate and semantic type """

        # use the direction of the lookup to use the correct db table
        if newcurie_is_source:
            table_name: str = 'source_curie'
        else:
            table_name: str = 'target_curie'

        # open a db connection and get the data
        with sqlite3.connect(self.db_name) as conn:
            # prepare and execute the SQL statement
            cur = conn.execute(f'\
                SELECT count \
                FROM {table_name} \
                WHERE normalized_curie=? AND predicate=? AND concept=?', (newcurie, predicate, semantic_type))

        # get the results
        result = cur.fetchall()

        # did we get something
        try:
            ret_val: int = result[0][0]
        except Exception as e:
            print(f'{newcurie} in get_hit_node_count() not found. {e}')
            ret_val: int = 0

        # Just need to know how many
        return ret_val

    def get_hit_nodecount_old(self, newcurie, predicate, newcurie_is_source, semantic_type):
        """ old style node count retreival. may be used for testing only """
        query = {'nodes': [{'id': 'n0', 'curie': newcurie}, {'id': 'n1', 'type': semantic_type}]}

        if newcurie_is_source:
            query['edges'] = [{'id': 'e0', 'source_id': 'n0', 'target_id': 'n1', 'type': predicate}]
        else:
            query['edges'] = [{'id': 'e0', 'source_id': 'n1', 'target_id': 'n0', 'type': predicate}]

        request = {"message": {"query_graph": query}}

        result = self.pipeline(request, yank=False)

        return len(result['results'])
