from neo4j import GraphDatabase
from collections import defaultdict
import os.path
import argparse
import sqlite3
import jsonlines

from src.node_handling import normalize

garbage_properties=set(['molecular_formula','iupac_name','pubchem.orig_smiles','inchikey','inchi','smiles','synonyms',
                        'molecular_weight','molecule_properties','equivalent_identifiers','simple_smiles','id','name',
                        'drugbank.accession_number','foodb_id','monoisotopic_mass','charge','chebi.orig_smiles','mass',
                        'role'])

def initialize_property_dbs(stype):
    # valid in put is biolink:<node label>. so just use the end part for this
    thisdir = os.path.dirname(os.path.realpath(__file__) )
    dbname = f'{thisdir}/{stype.replace(":", ".")}.db'
    if os.path.exists(dbname):
        os.remove(dbname)
    with sqlite3.connect(dbname) as conn:
        conn.execute('''CREATE TABLE properties (node text PRIMARY KEY, propertyset text)''')
        conn.execute('''CREATE TABLE property_counts (property text PRIMARY KEY, count integer)''')
    return dbname

def create_from_file(stype):
    counts = defaultdict(int)
    properties_per_node = defaultdict(set)
    with jsonlines.open(f'{stype.replace(":", ".")}_properties.jsonl','r') as inf:
        for line in inf:
            node = line['id']
            for p in line:
                if p not in ['id','name','category','equivalent_identifiers']:
                    v = line[p]
                    if isinstance(v,bool) and v:
                        properties_per_node[node].add(p)
                        counts[p] += 1
    dbname = initialize_property_dbs(stype)
    print('connecting to database and loading')
    with sqlite3.connect(dbname) as conn:
        for newid, properties in properties_per_node.items():
            conn.execute('INSERT INTO properties (node ,propertyset) VALUES (?,?)', (newid, str(properties)))
        for p, c in counts.items():
            if c > 1:
                conn.execute('INSERT INTO property_counts (property, count) VALUES (?,?)', (p, c))


#We might want this if the props end up all getting into robokopkg, but for now, we're goint to do this a diff way
def create_property_counts(stype,db,pw):
    #Because we're normalizing stuff from the older db, we sometimes find that multiple nodes from the old db
    # get glommed together in the new norm.
    #So we have to accumulate properties, then write them all out, rather than dump as wel go.
    driver = GraphDatabase.driver(f'bolt://{db}:7687', auth=('neo4j', pw))
    cypher = f'MATCH (a:`{stype}`) RETURN a'
    counts = defaultdict( int )

    properties_per_node = defaultdict(set)
    print('opening session')
    counter: int = 0

    with driver.session() as session:
        results = session.run(cypher)

        for result in results:
            counter += 1

            if (counter % 25000) == 0:
                print(f'processed: {counter}')

            node = result['a']

            properties = clean_properties(node)

            newid = normalize(node['id'])

            if newid is None:
                continue

            properties_per_node[newid].update(properties)

            for p in properties:
                counts[p] += 1

    print(f'creating database {stype}')

    dbname = initialize_property_dbs(stype)

    print('connecting to database and loading')

    with sqlite3.connect(dbname) as conn:
        for newid,properties in properties_per_node.items():
            conn.execute( 'INSERT INTO properties (node ,propertyset) VALUES (?,?)', (newid, str(properties)))
        for p,c in counts.items():
            if c > 1:
                conn.execute( 'INSERT INTO property_counts (property, count) VALUES (?,?)', (p,c))

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
    # For chemicalEntity: python generate_property_counts.py -t biolink:ChemicalEntity
    args = parser.parse_args()
    create_from_file(args.type)
