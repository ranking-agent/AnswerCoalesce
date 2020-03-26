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

            # retry up to 3 times
            for x in range(0, 3):
                # check the response code
                if response.status_code == 200:
                    # convert the string response to json
                    results = response.json()

                    # put away every member requested
                    for c in unknown:
                        # was there a value for this curie
                        if results[c] is not None:
                            # save the data
                            translator_curie = results[c]['id']['identifier']
                            semantic_type = results[c]['type'][0]
                            self.nn[c] = translator_curie
                            self.st[c] = semantic_type
                        # else:
                        #     print(f'No normalization result found for curie: {c}')

                    break
                else:
                    if x > 2:
                        print(f'All retry attempts failed. Block {block} of {len(lines)} curies entirely failed normalization. \n - Start line: {lines[0]} - End line: {lines[len(lines) - 1]}')
                    else:
                        print(f'Normalization failed event occurred on attempt {x + 1}. Retrying...')

    def get_normed_translator_curie(self, x):
        try:
            ret_val = self.nn[x]
        except Exception:
            # print(f'{x} ID not found.')
            ret_val = None

        return ret_val

    def get_normed_semantic_type(self, x):
        try:
            ret_val = self.st[x]
        except Exception:
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
    in_filenames = [f'{this_dir}\\atarget.txt', f'{this_dir}\\asource.txt'] # f'{this_dir}\\test.text',

    # create the DB name
    db_name: str = f'{this_dir}\\node_hit_count_lookup.db'

    # create the target DB
    initialize_lookup_db(db_name)

    # get a reference to the object that does the node normalization
    norman = Normalizer()

    # for all files
    for in_filename in in_filenames:
        # open the tab-delimited source data file
        with open(in_filename, 'r') as inf:
            # init the node norm request data block counter
            block = 1

            # skip the header line
            inf.readline()

            # loop through the data a block at a time
            for n_lines in iter(lambda: tuple(islice(inf, block_size)), ()):
                # load the identifiers into the normalized info object
                norman.normalize_block(n_lines, block)

                # init the data array
                data: list = []

                # spin through the lines of data in the block
                for line in n_lines:
                    # split the data line into its' parts
                    parts = line.strip().split('\t')

                    # determine the corrected concept type
                    concept = fix_concept_type(parts[3])

                    if concept is not None:
                        data.append([parts[0], norman.get_normed_translator_curie(parts[0]), parts[1], norman.get_normed_semantic_type(parts[0]), concept, parts[4]])

                        # print(f'original curie: {parts[0]}, normalized curie: {norman.get_normed_translator_curie(parts[0])}, predicate: {parts[1]}, semantic type: \
                        # {norman.get_normed_semantic_type(parts[0])}, concept: {concept}, count: {parts[4]}')

                # persist the data
                load_data(db_name, in_filename, data)

                # progress indicator
                if block % 2500 == 0:
                    print(f'{block} blocks of 100 curies processed in file: {in_filename}.')

                # move to next block
                block = block + 1


def initialize_lookup_db(db_name: str):
    """ this method creates a new sqlite DB for the lookup data """

    # remove the DB if it already exists
    if os.path.exists(db_name):
        os.remove(db_name)

    # original curie: HGNC:5, normalized curie: NCBIGene:1, predicate: decreases_expression_of, semantic type: gene, concept: chemical_substance, count: 1
    # create the DB tables
    with sqlite3.connect(db_name) as conn:
        conn.execute('''CREATE TABLE source_curie (original_curie text, normalized_curie text, predicate text, semantic_type text, concept text, count integer)''')
        conn.execute('''CREATE TABLE target_curie (original_curie text, normalized_curie text, predicate text, semantic_type text, concept text, count integer)''')

    # return the DB name to the caller
    return db_name


def load_data(db_name: str, file_name: str, data: list):
    """ loads the sqlite database with data """

    # get the name of the table
    if 'source' in file_name:
        table_name: str = 'source_curie'
    else:
        table_name: str = 'target_curie'

    # open a db connection and persist the data
    with sqlite3.connect(db_name) as conn:
        for original_curie, normalized_curie, predicate, semantic_type, concept, count in data:
            conn.execute(f'\
            INSERT INTO {table_name} (original_curie, normalized_curie, predicate, semantic_type, concept, count) \
            VALUES (?,?,?,?,?,?)', \
            (original_curie, normalized_curie, predicate, semantic_type, concept, int(count)))


if __name__ == '__main__':
    go()
    print('Complete.')
