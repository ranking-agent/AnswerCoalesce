import requests
import os
import json

def create_asthma_chemical_request(edgetype):
    req = {
        "message": {
            "query_graph": {
                "nodes": {
                    'n0': {
                       "category": "biolink:ChemicalSubstance"
                    },
                    'n1': {
                       "category ": "biolink:Disease",
                       "id": ["MONDO:0004979"]
                    }
                },
                "edges": {
                    'e1':{
                        #"type": "contributes_to",
                        "subject": "n0",
                        "object": "n1"
                    }
                }
            }
        }
    }
    if edgetype:
        req['edges'][0]['predicate'] = 'biolink:contributes_to'
    return req

def create_imatinib_asthma_by_gene():
    request = {
        "message": {
            "query_graph": {
                "nodes": {
                  "n0":{
                    "category": "biolink:ChemicalSubstance",
                    "name": "imatinib",
                    "id": [
                      "CHEBI:45783"
                    ]
                  },
                  "n1":{
                    "type": "biolink:Gene",
                  },
                  'n2':{
                    "category": "biolink:Disease",
                    "name": "Asthma",
                    "id": [
                      "MONDO:0004979"
                    ]
                  }
                },
                "edges": {
                  'e0':{
                    "subject": "n0",
                    "object": "n1"
                  },
                  'e1':{
                    "subject": "n1",
                    "object": "n2"
                  }
                }
              },
        }
    }
    return request

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
    #create_example( create_asthma_chemical_request(edgetype=False), 'asthma_one_hop_many_preds.json')
    create_example( create_imatinib_asthma_by_gene(), 'imatinib_gene_asthma.json')
