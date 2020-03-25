import os
from itertools import islice
import requests
from ast import literal_eval

class normalizer:
    def __init__(self):
        self.url = 'https://nodenormalization-sri.renci.org/get_normalized_nodes'
        self.nn = {}
        self.st = {}
    def process(self,lines):
        unknown = []
        for l in lines:
            x = l.split('\t')[0]
            if x not in self.nn:
                unknown.append(x)
        if len(unknown) > 0:
            response=requests.get(self.url, params={'curie':unknown})
            results = response.json()
            for c in unknown:
                translator_curie = results[c]['id']['identifier']
                semantic_type = results[c]['semantic_types'][0]
                self.nn[c] = translator_curie
                self.st[c] = semantic_type
    def get_normed_id(self,x):
        return self.nn[x]
    def get_normed_type(self,x):
        return self.st[x]


goodtypes = set(
    ['gene', 'chemical_substance', 'disease', 'phenotypic_feature', 'cell', 'anatomical_entity', 'cellular_component'])
def fixtype(liststring):
    l = set(literal_eval(liststring))
    goodones = goodtypes.intersection(l)
    if len(goodones) == 0:
        print(liststring)
        exit()
    if len(goodones) > 1:
        print(liststring)
        return None
    return list[goodones][0]


def go():
    chunksize=100
    thisdir = os.path.dirname(os.path.realpath(__file__) )
    infname = f'{thisdir}/asource.txt'
    dbname = f'{thisdir}/asource.db'
    norman = normalizer()
    with open('asource.txt','r') as inf:
        h = inf.readline()
        for n_lines in iter(lambda: tuple(islice(inf, chunksize)), ()):
            #this loads the identifiers into normans info
            norman.process(n_lines)
            for line in n_lines:
                parts = line.strip().split('\t')
                newtargettype=fixtype(parts[3])
                if newtargettype is not None:
                    print(norman.get_normed_id(parts[0]),parts[1],norman.get_normed_type(parts[0]),newtargettype,parts[4])

if __name__ == '__main__':
    go()