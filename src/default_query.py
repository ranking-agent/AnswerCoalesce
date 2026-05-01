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
                        # 'HP:0000739',
                        # 'HP:0001288',
                        # 'HP:0001252',
                        # 'HP:0001250',
                        # 'HP:0000750',
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

default_input_infer: dict = {
    "message": {
        "query_graph": {
            "nodes": {
                "input": {
                    "categories": ["biolink:Disease"],
                    "ids": ["MONDO:0004975"]
                },
                "output": {
                    "categories": ["biolink:Drug"]
                }
            },
            "edges": {
                "edge_0": {
                    "subject": "output",
                    "object": "input",
                    "predicates": ["biolink:treats"],
                    "knowledge_type": "inferred"
                }
            }
        }
    },
    "parameters": {
        "pvalue_threshold": 1e-6,
        "max_rules": 5
    }
}