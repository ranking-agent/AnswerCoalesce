default_input_sync: dict = {
    'message': {
        'query_graph': {
            'nodes': {
                'input': {
                    'categories': ['biolink:PhenotypicFeature'],
                    'ids': [
                        'uuid:1'
                    ],
                    'member_ids': [
                        'HP:0000739',
                        'HP:0001288',
                        'HP:0001252',
                        'HP:0001250',
                        'HP:0000750',
                        'HP:0002378',
                        'HP:0002019',
                        'HP:0007146'
                    ],
                    'set_interpretation': 'MANY'
                },
                'output': {
                    'categories': ['biolink:Disease']}},
            'edges': {
                'edge_0': {
                    'subject': 'input',
                    'object': 'output',
                    'predicates': ['biolink:has_phenotype']
                }
            }
        }
    }
}

default_input_async: dict = {
    "callback": "https://aragorn.renci.org/1.2/aragorn_callback",
    "message": {
        "query_graph": {
            "edges": {
                "e01": {
                    "object": "n0",
                    "subject": "n1",
                    "predicates": [
                        "biolink:entity_negatively_regulates_entity"
                    ]
                }
            },
            "nodes": {
                "n0": {
                    "ids": [
                        "NCBIGene:23221"
                    ],
                    "categories": [
                        "biolink:Gene"
                    ]
                },
                "n1": {
                    "categories": [
                        "biolink:Gene"
                    ]
                }
            }
        }
    }
}
