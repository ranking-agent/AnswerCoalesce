import requests
import os
import json
from time import sleep

class Strider:
    def __init__(self):
        self.url = 'http://robokop.renci.org:5781'

    def call(self, question):
        message = {'message': {'query_graph': question}}
        return self.send_message(message)

    def send_message(self, message):
        response = requests.post(f'{self.url}/query', json=message)
        if response.status_code == 200:
            pid = response.json()
            return pid
        else:
            print(f'Status code:{response.status_code}')
            return None

    def query_result(self, pid):
        r = requests.get(f'{self.url}/results', params={'query_id': pid})
        return r.json()

def make_disease_chem_question(disease_id):
    question = { 'nodes': {'n0':{'id':disease_id, 'category':'biolink:Disease'},
                           'n1': {'category':'biolink:ChemicalSubstance'}},
                 'edges': { 'e0': {'subject': 'n1', 'object': 'n0', 'predicate': 'biolink:treats'}}}
    message = {'message': {'query_graph': question}}
    return message

def create_example(request,fname):
    thisdir = os.path.dirname(os.path.realpath(__file__))
    strider = Strider()
    print(request)
    pid = strider.send_message(request)
    print(pid)
    lr = 0
    while lr == 0:
        sleep(1)
        output = strider.query_result(pid)
        if 'results' not in output:
            print(output)
        else:
            lr = len(output['results'])
    outfname = os.path.join(thisdir,fname)
    with open(outfname,'w') as outf:
        json.dump(output,outf,indent=2)

if __name__ == '__main__':
    did = 'MONDO:0005180'  # Parkinson
    create_example( make_disease_chem_question(did), 'parkinsons_chems.json')
