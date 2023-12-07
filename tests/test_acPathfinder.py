import pytest
import os, json, random, sys, io
import cProfile
import pstats
import numpy as np
# import matplotlib.pyplot as plt
import requests
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from reasoner_pydantic import Response as PDResponse
from set_trapi_template import qg_template
from datetime import datetime
from string import Template


jsondir ='InputJson_1.4'

def test_pathfinderac():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'sampleset.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        answerset = answerset['message']

    newset = snc.coalesce(answerset, method='graph')

    #uncomment this to save the result to the directory
    with open(f"newset{datetime.now()}.json", 'w') as outf:
        json.dump(newset, outf, indent=4)
    assert PDResponse.parse_obj({'message': newset})
    # Must be at least the length of the initial nodeset
    nodeset = {}
    for qg_id, node_data in newset.get("query_graph", {}).get("nodes", {}).items():
        if 'ids' in node_data and node_data.get('is_set'):
            nodeset = set(node_data.get('ids', []))
    assert len(newset['results']) >= len(nodeset)

# target_ids =  ["NCBIGene:3693", "NCBIGene:19894", "NCBIGene:2778", "NCBIGene:7070", "NCBIGene:103178432"]
# target = 'gene'
# source_id = 'chemical'
# input_category = 'biolink:Gene'
# output_category = 'biolink:ChemicalEntity'
# predicate = 'affects'
# qualifiers = 'increased_activity'
# def test_pathfinderac(target_ids =[], target = '', input_category = '', source_ids='', source = '', output_category='',  predicate='', qualifiers='')

def resolvename(name):
    name_resolver_url = f'https://name-resolution-sri.renci.org/lookup?string={name}&offset=0&limit=2'
    res = requests.post(name_resolver_url).json()
    curie = ''
    for rs in res:
        if rs['label']==name or rs['label'].lower() == name.lower():
            curie = rs['curie']
            break
    return curie

def xtest_pathfinderac(target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers):
# def test_pathfinderac():
#
#     # target_ids = ['JUN', 'GDI1', 'GNAI2']#["NCBIGene:3693", "NCBIGene:19894", "NCBIGene:2778", "NCBIGene:7070", "NCBIGene:103178432"]
#     target_ids= ["NCBIGene:3693", "NCBIGene:19894", "NCBIGene:2778", "NCBIGene:7070", "NCBIGene:103178432"]#['NCBIGene:3693', 'NCBIGene:19894', 'NCBIGene:2778', 'NCBIGene:7070', 'NCBIGene:103178432']
#     target='gene'
#     target_category='biolink:Gene'
#     predicate='biolink:affects'
#     source_ids=None
#     source='chemical'
#     source_category='biolink:ChemicalEntity'
#     qualifiers='increased_activity'

    if not target_ids:
        """Make sure that results are well formed."""
        dir_path = os.path.dirname(os.path.realpath(__file__))
        testfilename = os.path.join(dir_path, jsondir, 'sampleset.json')
        with open(testfilename, 'r') as tf:
            answerset = json.load(tf)
            assert PDResponse.parse_obj(answerset)
            answerset = answerset['message']
    else:
        if isinstance(target_ids, str):
            target_ids = target_ids.split(',')
            if target_ids[0].find(':')<0:
                target_ids = [resolvename(name) for name in target_ids]

        # target_ids =  ["NCBIGene:3693", "NCBIGene:19894", "NCBIGene:2778", "NCBIGene:7070", "NCBIGene:103178432"]
        # target_id = 'gene'
        # source_id = 'chemical'
        # input_category = 'biolink:Gene'
        # output_category = 'biolink:ChemicalEntity'
        # predicate = 'biolink:affects'
        # qualifiers = 'increased_activity'
        # print('=====: ', target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers, end='\n')
        answerset = get_qg(target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers)
        # print(answerset)
    with cProfile.Profile() as profile:
        newset = snc.coalesce(answerset, method='graph')

    s = io.StringIO()
    stats = pstats.Stats(profile, stream=s)
    excluded_function =["getEffectiveLevel", "<method 'isalnum' of 'str' objects>", "<method '__exit__' of '_thread.lock' objects>", "<method 'pop' of 'list' objects>", "__enter__", "disable", "owns_connection", "connect", "<method 'close' of '_io.BytesIO' objects>", "<method 'sort' of 'list' objects>", "<method 'keys' of 'dict' objects>",
                        "<method 'connect' of '_socket.socket' objects>", "_releaseLock", "<method 'acquire' of '_thread.RLock' objects>", "get_connection",
                        "<method 'truncate' of '_io.BytesIO' objects>", "close", "_releaseLock", "_connect", "<method 'replace' of 'str' objects>",
                        "getaddrinfo", "<method 'replace' of 'str' objects>", "<method 'add' of 'set' objects>",  "<method 'rpartition' of 'str' objects>", '<genexpr>', '<lambda>',  '<listcomp>', '<dictcomp>', "<method 'disable' of '_lsprof.Profiler' objects>", "<method 'values' of 'dict' objects>", "<method 'release' of '_thread.RLock' objects>", "<method 'remove' of 'set' objects>",
                        "getaddrinfo", "__exit__", "__init__", "check_health", "<method 'replace' of 'str' objects>", "<method 'add' of 'set' objects>",  "<method 'rpartition' of 'str' objects>", '<genexpr>', '<lambda>',  '<listcomp>', '<dictcomp>', "<method 'disable' of '_lsprof.Profiler' objects>", "<method 'values' of 'dict' objects>",
                        "<method 'end' of 're.Match' objects>",  "length", "__del__", "<method 'items' of 'dict' objects>", "<method 'release' of '_thread.RLock' objects>", "<method 'remove' of 'set' objects>"]
    target_functions = ['graph_coalescer.py', 'single_node_coalescer.py', 'property_coalesce.py']
    targetdict = {'graph_coalescer.py':'gc', 'single_node_coalescer.py': 'snc', 'property_coalesce.py':'pc'}
    stats.strip_dirs()
    stats.sort_stats('cumulative')

    stats_data = {
        'ncalls': [stats.stats[key][0] for key in stats.stats if key[-1] not in excluded_function and '<built-in' not in key[-1] and key[0] in target_functions],
        'tottime': [stats.stats[key][2] for key in stats.stats if key[-1] not in excluded_function and '<built-in' not in key[-1] and key[0] in target_functions],
        'percall_tottime': [stats.stats[key][2] / stats.stats[key][0] if stats.stats[key][0] != 0 else 0 for key in
                            stats.stats if key[-1] not in excluded_function and '<built-in' not in key[-1] and key[0] in target_functions],
        'cumtime': [stats.stats[key][3] for key in stats.stats if key[-1] not in excluded_function and '<built-in' not in key[-1] and key[0] in target_functions],
        'percall_cumtime': [stats.stats[key][3] / stats.stats[key][0] if stats.stats[key][0] != 0 else 0 for key in
                            stats.stats if key[-1] not in excluded_function and '<built-in' not in key[-1] and key[0] in target_functions],
        'filename(function)': [targetdict.get(key[0])+'_'+key[-1] for key in stats.stats if key[-1] not in excluded_function and '<built-in' not in key[-1] and key[0] in target_functions]
    }

    cumtime = np.array(stats_data['cumtime'])
    sorted_indices = np.argsort(cumtime)[::-1]
    filename_function = np.array(stats_data['filename(function)'])[sorted_indices]
    ncalls = np.array(stats_data['ncalls'])[sorted_indices]
    tottime = np.array(stats_data['tottime'])[sorted_indices]
    percall_tottime = np.array(stats_data['percall_tottime'])[sorted_indices]
    percall_cumtime = np.array(stats_data['percall_cumtime'])[sorted_indices]
    cumtime = cumtime[sorted_indices]

    rows = list(zip(filename_function, ncalls, tottime, percall_tottime, cumtime, percall_cumtime))

    # Headers
    headers = ["Function", "ncalls", "tottime", "percall_tottime", "cumtime", "percall_cumtime"]

    # Calculate the maximum width for each column
    col_widths = [max(len(str(header)), max(len(str(row[i])) for row in rows)) for i, header in enumerate(headers)]

    # Print the headers
    header_line = "|".join(f"{header:<{col_widths[i]}}" for i, header in enumerate(headers))
    print(header_line)
    print("-" * sum(col_widths + [len(headers) - 1]))

    # Print the rows
    for row in rows:
        row_line = "|".join(f"{str(value):<{col_widths[i]}}" for i, value in enumerate(row))
        print(row_line)
    # plt.figure(figsize=(10, 6))
    # plt.plot(filename_function, cumtime, label='Cumulative Time', marker='o', linestyle='-')
    # plt.xticks(rotation=45, ha="right")
    # plt.title("Cumulative Time for the Functions")
    # plt.xlabel("Functions")
    # plt.ylabel("Cumulative Time (secs)")
    # plt.legend()
    # plt.grid(linewidth=0.1)
    # plt.tight_layout()
    # plt.show()

    print(f"***{len(newset['results'])} *** results returned")
    #uncomment this to save the result to the directory
    # with open(f"newset{datetime.now()}.json", 'w') as outf:
    #     json.dump(newset, outf, indent=4)
    assert PDResponse.parse_obj({'message': newset})

    nodeset = {}
    for qg_id, node_data in newset.get("query_graph", {}).get("nodes", {}).items():
        if 'ids' in node_data and node_data.get('is_set'):
            nodeset = set(node_data.get('ids', []))
    if newset['results']:
        print(f"Samples: {[newset['knowledge_graph']['nodes'][idx]['name'] for idx in random.sample(list(set(newset['knowledge_graph']['nodes']).difference(nodeset)), 2)]}")
    # assert len(newset['results']) >= len(nodeset)

def get_qg(target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers=None):
    query_template = Template(qg_template())
    query = {}
    source_ids = source_ids if source_ids== None else []
    # print('source_ids: ', source_ids)
    is_source = True if source_ids else False
    # print('is_source: ', is_source)
    quali = []
    if qualifiers:
        q_split = qualifiers.split('_')
        if len(q_split)==2:
            quali = [{
                            "qualifier_type_id": "biolink:object_aspect_qualifier",
                            "qualifier_value": q_split[1]
                        },
                        {
                            "qualifier_type_id": "biolink:object_direction_qualifier",
                            "qualifier_value": q_split[0]
                        }
                    ]

    qs = query_template.substitute(source=source, target=target, source_id=json.dumps(source_ids), target_id=json.dumps(target_ids),
                                           source_category=json.dumps([source_category]),
                                           target_category=json.dumps([target_category]), predicate=predicate,
                                           qualifier= json.dumps(quali))

    try:
        query = json.loads(qs)

        if is_source:
            del query["query_graph"]["nodes"][target]["ids"]
        else:
            del query["query_graph"]["nodes"][source]["ids"]
    except UnicodeDecodeError as e:
        print(e)

    return query

if __name__ == '__main__':
    if len(sys.argv) > 1:
        try:
            target_ids = sys.argv[1]
            target = sys.argv[2]
            target_category = sys.argv[3]
            predicate = sys.argv[4]
            source_ids = sys.argv[5]
            source = sys.argv[6]
            source_category = sys.argv[7]
            qualifiers = sys.argv[8]
        except IndexError:
            print("Not enough command-line arguments provided.")
            print(
                "Usage: python your_script.py target_ids target target_category predicate source_ids source source_category qualifiers")
            print(
                "Example: test_acPathfinder.py NCBIGene:3693,NCBIGene:19894 gene 'biolink:Gene' 'biolink:affects' None chemical 'biolink:ChemicalEntity' '' ")

            sys.exit(1)
    else:
        print(
            "Usage: python your_script.py target_ids target target_category predicate source_ids source source_category qualifiers")
        print(
            "Example: test_acPathfinder.py NCBIGene:3693,NCBIGene:19894 gene 'biolink:Gene' 'biolink:affects' None chemical 'biolink:ChemicalEntity' '' ")
        sys.exit(1)
    # Call your function with the provided or default values
    xtest_pathfinderac(target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers)
