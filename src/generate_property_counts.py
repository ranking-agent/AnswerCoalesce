from neo4j.v1 import GraphDatabase
from collections import defaultdict
import argparse

garbage_properties=set(['molecular_formula','iupac_name','pubchem.orig_smiles','inchikey','inchi','smiles','synonyms',
                        'molecular_weight','molecule_properties','equivalent_identifiers','simple_smiles','id','name',
                        'drugbank.accession_number','foodb_id','monoisotopic_mass','charge','chebi.orig_smiles','mass'])

def create_property_counts(stype,db,pw):
    driver = GraphDatabase.driver(f'bolt://{db}:7687', auth=('neo4j', pw))
    cypher = f'MATCH (a:{stype}) RETURN a'
    counts = defaultdict( int )
    with driver.session() as session:
        results = session.run(cypher)
        for result in results:
            node = result['a']
            properties = clean_properties(node)
            for p in properties:
                counts[p] += 1
    with open(f'{stype}.properties','w') as outf:
        for p,c in counts.items():
            if c > 1:
                outf.write(f'{p}\t{c}\n')


def clean_properties(node):
    props = set()
    for key in node:
        if key in garbage_properties:
            continue
        #OK, the complexity of this code is suggesting that our implementation of chem props leaves something
        # to be desired
        value = node[key]
        if key == 'drugbank.categories':
            for x in value:
                props.add(x)
        elif isinstance(value,bool):
            if value:
                props.add(key)
            continue
        else: #should be a string
            #These seem to be a couple of ways that chembl indicates false-ness
            if value == '0' or value == '-1':
                continue
            if value == '1':
                props.add(key)
            if key == 'molecule_type':
                props.add(f'{key}:{value}')
    return props

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description = 'help',
            formatter_class = argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-t','--type',help='semantic type to collect properties of')
    parser.add_argument('-d','--database',help='URL of neo4j')
    parser.add_argument('-p','--password',help='password for neo4j')
    args = parser.parse_args()
    create_property_counts(args.type,args.database,args.password)
