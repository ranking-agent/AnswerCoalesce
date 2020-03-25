import os
import requests
import sqlite3
from itertools import islice
from ast import literal_eval


class Normalizer:
    """ Class that performs normalization on a block of curies """

    def __init__(self):
        self.url: str = 'https://nodenormalization-sri.renci.org/get_normalized_nodes'
        self.nn: dict = {}
        self.st: dict = {}

    def normalize_block(self, lines: tuple, block: int):
        # init storage for curies that have not been already processed
        unknown: list = []

        # for each line
        for line in lines:
            # split each line into an array of items
            x: list = line.split('\t')[0]

            # is this a duplicate
            if x not in self.nn:
                # add it to the list for processing
                unknown.append(x)

        # did we find some items to process
        if len(unknown) > 0:
            # make the call to get normalized nodes
            response: requests.Response = requests.get(self.url, params={'curie': unknown})

            # check the response code
            if response.status_code == 200:
                # convert the string response to json
                results = response.json()

                # put away every member requsted
                for c in unknown:
                    # was there a value fr this cureie
                    if results[c] is not None:
                        # save the data
                        translator_curie = results[c]['id']['identifier']
                        semantic_type = results[c]['type'][0]
                        self.nn[c] = translator_curie
                        self.st[c] = semantic_type
                    # else:
                    #     print(f'No normalization result found for curie: {c}')
            else:
                print(f'Block {block} of {len(lines)} curies entirely failed normalization. \n - Start line: {lines[0]} - End line: {lines[len(lines) - 1]}')

    def get_normed_id(self, x):
        try:
            ret_val = self.nn[x]
        except IndexError:
            # print(f'{x} ID not found.')
            ret_val = None

        return ret_val

    def get_normed_type(self, x):
        try:
            ret_val = self.st[x]
        except IndexError:
            # print(f'{x} type not found.')
            ret_val = None

        return ret_val


# declare concept filtering mechanisms. each set represents a layer of filtering
pass1_types: set = {'gene', 'chemical_substance', 'disease', 'phenotypic_feature', 'cell', 'anatomical_entity', 'cellular_component'}
pass2_types: set = {'cellular_component'}
pass3_types: set = {'disease', 'phenotypic_feature'}
pass4_types: set = {'gene', 'chemical_substance'}
pass5_types: set = {'gene', 'disease'}
pass6_types: set = {'cell', 'anatomical_entity'}


def fix_concept_type(list_string: list):
    """ filters and repairs the concept type for the item passed """

    # init the return value
    ret_val = None

    # get the input into a set
    literal = set(literal_eval(list_string))

    # filter to include only concepts we are looking for
    pass_1 = pass1_types.intersection(literal)

    # first pass singles pass on through
    if len(pass1_types.intersection(literal)) == 1:
        ret_val = next(iter(pass_1))
    # multiple curies discovered need more interrogation
    elif len(pass_1) > 1:
        # go through what was filtered to adjust the final concept to use
        if len(pass2_types.intersection(pass_1)) == 1:
            ret_val = 'cellular_component'
        elif len(pass3_types.intersection(pass_1)) == 2:
            ret_val = 'disease'
        elif len(pass4_types.intersection(pass_1)) == 2:
            ret_val = 'gene'
        elif len(pass5_types.intersection(pass_1)) == 2:
            ret_val = None
        elif len(pass6_types.intersection(pass_1)) == 2:
            ret_val = 'cell'
        else:
            print(f'Unexpected type combination: {pass_1}')

    # return the result to the caller
    return ret_val


def go():
    """ executes the normalization of nodes and putting the data in a sqlite database """

    # define the number of records in the block request
    block_size = 100

    # find the absolute directory we are in
    this_dir = os.path.dirname(os.path.realpath(__file__))

    # specify the source data files to process
    source_in_filename = f'{this_dir}/asource.txt'

    # create the target DB
    initialize_edge_dbs('asource')

    # get a reference to the object that does the node normalization
    norman = Normalizer()

    # open the tab-delimited source data file
    with open(source_in_filename, 'r') as inf:
        # init the request data block count
        block = 1

        # skip the header line
        inf.readline()

        # loop through the data a block at a time
        for n_lines in iter(lambda: tuple(islice(inf, block_size)), ()):
            # load the identifiers into the normalized info object
            norman.normalize_block(n_lines, block)

            # spin through the lines of data in the block
            for line in n_lines:
                # split the data line into its' parts
                parts = line.strip().split('\t')

                # determine the new target concept type
                newtargettype = fix_concept_type(parts[3])

                # if newtargettype is not None:
                # TODO: add record to sqlite DB
                #     print(f'parts 0: {parts[0]}, normed id: {norman.get_normed_id(parts[0])}, parts 1: {parts[1]}, normed type: {norman.get_normed_type(parts[0])}, new target type: {newtargettype}, parts 4: {parts[4]}')

            # progress indicator
            if block % 10000 == 0:
                print(f'{block} blocks processed.')

            # move to next block
            block = block + 1


def initialize_edge_dbs(source_type):
    """ this method creates new sqlite DBs for the data """

    # get the true directory we are in
    this_dir = os.path.dirname(os.path.realpath(__file__))

    # create the DB name
    dbname = f'{this_dir}/{source_type}.db'

    # remove the DB if the db already exists
    if os.path.exists(dbname):
        os.remove(dbname)

    # create the DB tables
    with sqlite3.connect(dbname) as conn:
        conn.execute('''CREATE TABLE edges (node text, edgeset text)''')
        conn.execute('''CREATE TABLE edge_counts (edge text, count integer)''')

    # return the DB name to the caller
    return dbname


def create_edge_counts(stype, db, pw):
    """ loads the sqlite database with data """
    for result in results:
        node = result['a']
        properties = clean_properties(node)
        newid = normalize(node['id'])
        if newid is None:
            continue
        properties_per_node[newid].update(properties)
        for p in properties:
            counts[p] += 1

    dbname = initialize_edge_dbs(stype)

    with sqlite3.connect(dbname) as conn:
        for newid, properties in properties_per_node.items():
            conn.execute('INSERT INTO edges (node ,propertyset) VALUES (?,?)', (newid, str(properties)))

        for p, c in counts.items():
            if c > 1:
                conn.execute('INSERT INTO edge_counts (property, count) VALUES (?,?)', (p, c))


if __name__ == '__main__':
    go()
    print('Complete.')
