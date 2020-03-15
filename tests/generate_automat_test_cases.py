import requests
import os
import json
from time import sleep


def make_disease_chem_question(disease_id):
    question = { 'nodes': [{'id':'n0', 'type':'disease', 'curie':disease_id},
                          {'id': 'n1', 'type':'chemical_substance'}],
                 'edges': [ {'id': 'e0', 'source_id': 'n1', 'target_id': 'n0', 'type': 'treats'}]}
    message = {'query_graph': question}
    return message

def make_chem_gene_question(c_id):
    question = { 'nodes': [{'id':'n0', 'type':'chemical_substance', 'curie':c_id},
                          {'id': 'n1', 'type':'gene'}],
                 'edges': [ {'id': 'e1', 'source_id': 'n0', 'target_id': 'n1', 'type':'decreases_degradation_of'}]}
    message = {'query_graph': question}
    return message

from datetime import datetime as dt
def query_automat(message,plate):
    url = f'https://automat.renci.org/{plate}/reasonerapi'
    t0 = dt.now()
    r = requests.post(url,json=message)
    t1= dt.now()
    print(f'It took {t1-t0} s to return')
    if r.status_code == 200:
        return r.json()
    print(r.status_code)
    return None

def create_example(request,plate,fname):
    thisdir = os.path.dirname(os.path.realpath(__file__))
    print(request)
    output = query_automat(request,plate)
    for r in output['results']:
        r['score'] = 1
    outfname = os.path.join(thisdir,fname)
    print(output['results'][0]['score'])
    print(output['results'][-1]['score'])
    with open(outfname,'w') as outf:
        json.dump(output,outf,indent=2)

if __name__ == '__main__':
    #did = 'MONDO:0005148'  # T2D
    #create_example( make_disease_chem_question(did), 'mychem','mychem_treats_diabetes.json')
    create_example( make_chem_gene_question("PUBCHEM:9830615"),'ctd','mixo.json')

