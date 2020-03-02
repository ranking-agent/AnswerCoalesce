import requests
import os
import json

def create_asthma_chemical_request(edgetype):
    req = {
        "message": {
            "query_graph": {
                "nodes": [
                    {
                       "id": "n0",
                       "type": "chemical_substance"
                    },
                    {
                       "id": "n1",
                       "type": "disease",
                       "curie": ["MONDO:0004979"]
                    }
                ],
                "edges": [
                    {
                        "id": "e1",
                        #"type": "contributes_to",
                        "source_id": "n0",
                        "target_id": "n1"
                    }
                ]
            }
        }
    }
    if edgetype:
        req['edges'][0]['type'] = 'contributes_to'
    return req

def create_svil_request():
    request = {
    "message": {
        "query_graph": {
            "nodes": [
                {
                    "id": "n0",
                    "type": "gene",
                    "set": False,
                    "name": "SVIL",
                    "curie": [
                        "HGNC:11480"
                    ]
                },
                {
                    "id": "n1",
                    "type": "sequence_variant",
                    "set": False
                },
                {
                    "id": "n2",
                    "type": "disease_or_phenotypic_feature",
                    "set": False
                },
                {
                    "id": "n3",
                    "type": "disease",
                    "set": False,
                    "name": "autism spectrum disorder",
                    "curie": [
                        "MONDO:0005258"
                    ]
                }
            ],
            "edges": [
                {
                    "id": "e0",
                    "source_id": "n0",
                    "target_id": "n1"
                },
                {
                    "id": "e1",
                    "source_id": "n1",
                    "target_id": "n2"
                }
            ]
        }
    } }

def pipeline(request):
    #normalize question
    response = requests.post( 'http://robokop.renci.org:4868/normalize', json=request )
    normalized = response.json()
    #answer question
    request = { 'message': normalized, }
    response = requests.post( 'http://robokop.renci.org:4868/answer', json=request )
    answered = response.json()
    #Yank
    request = { 'message': answered, }
    response = requests.post( 'http://robokop.renci.org:4868/yank', json=request )
    filled = response.json()
    #support
    request = { 'message': filled, }
    response = requests.post( 'http://robokop.renci.org:4868/support', json=request )
    supported = response.json()
    #weight
    request = { 'message': supported, }
    response = requests.post( 'http://robokop.renci.org:4868/weight_correctness', json=request )
    weighted = response.json()
    #score
    request = { 'message': weighted, }
    response = requests.post( 'http://robokop.renci.org:4868/score', json=request )
    scored = response.json()
    return scored

def create_example(request,fname):
    thisdir = os.path.dirname(os.path.realpath(__file__))
    output = pipeline(request)
    outfname = os.path.join(thisdir,fname)
    with open(outfname,'w') as outf:
        json.dump(output,outf,indent=2)

if __name__ == '__main__':
    #create_example( create_asthma_chemical_request(edgetype=True), 'asthma_one_hop.json')
    create_example( create_asthma_chemical_request(edgetype=False), 'asthma_one_hop_many_preds.json')
