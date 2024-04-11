import pytest
from datetime import datetime
from string import Template
import os, sys, json, requests, cProfile, io, pstats, numpy as np, random
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from src.query_graph_templates import qg_template
from reasoner_pydantic import Response as PDResponse

jsondir ='InputJson_1.4'

#Used in test_graph_coalesce to extract values from attributes, which can be a list or a string
def flatten(ll):
    if isinstance(ll, list):
        temp = []
        for ele in ll:
            temp.extend(flatten(ele))
        return temp
    else:
        return [ll]
def test_gouper():
    x = 'abcdefghi'
    n = 0
    for group in gc.grouper(3,x):
        x = group
        n += 1
    assert n == 3
    assert x == ('g','h','i')
def test_gouper_keys():
    d = {x:x for x in 'abcdefg'}
    n = 0
    for group in gc.grouper(3, d.keys()):
        x = group
        n += 1
    assert n == 3
    assert x == ('g',)
@pytest.mark.nongithub
def xtest_multicurieac():
    """NO rules"""
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'sample_multicurie_set.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        assert PDResponse.parse_obj(answerset)
        answerset = answerset['message']

    newset = snc.coalesce(answerset, method='graph', mode='query')

    #uncomment this to save the result to the directory
    # with open(f"newset{datetime.now()}.json", 'w') as outf:
    #     json.dump(newset, outf, indent=4)
    assert PDResponse.parse_obj({'message': newset})
    # Must be at least the length of the initial nodeset
    nodeset = {}
    for qg_id, node_data in newset.get("query_graph", {}).get("nodes", {}).items():
        if 'ids' in node_data and node_data.get('is_set'):
            nodeset = set(node_data.get('ids', []))
    assert len(newset['results']) >= len(nodeset)
# @pytest.mark.nongithub


import asyncio
from pyinstrument import Profiler
# from pathlib import Path
# TESTS_ROOT = Path.cwd()

# @pytest.fixture(autouse=True)
def test_infer():
    # PROFILE_ROOT = (TESTS_ROOT / ".profiles")
    # # Turn profiling on


    """We can comment this out since the same appears in test_endpoint.py"""
    """Lookup Trapi with added workflow parameters"""
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'alzheimers_qg.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)

    assert PDResponse.parse_obj(answerset)
    predicates_to_exclude = None
    pvalue_threshold = None
    properties_to_exclude = None
    if 'workflow' in answerset and 'parameters' in answerset['workflow'][0]:
        pvalue_threshold = answerset.get('workflow')[0].get('parameters').get('pvalue_threshold', 0)
        predicates_to_exclude = answerset.get('workflow')[0].get('parameters').get('predicates_to_exclude', None)
        properties_to_exclude = answerset.get('workflow', [])[0].get('parameters').get('properties_to_exclude',
                                                                                       None)
    # profiler = Profiler()
    # with profiler:
    newset = asyncio.run(snc.coalesce(answerset['message'], method='all', mode='infer', predicates_to_exclude=predicates_to_exclude,
                          properties_to_exclude=properties_to_exclude, pvalue_threshold=pvalue_threshold))
    # PROFILE_ROOT.mkdir(exist_ok=True)
    # results_file = PROFILE_ROOT / f"{request.node.name}.html"
    # profiler.print()
    assert PDResponse.parse_obj({'message': newset})

def resolvename(name):
    name_resolver_url = f'https://name-resolution-sri.renci.org/lookup?string={name}&offset=0&limit=2'
    res = requests.post(name_resolver_url).json()
    curie = ''
    for rs in res:
        if rs['label']==name or rs['label'].lower() == name.lower():
            curie = rs['curie']
            break
    return curie

# TO run the test from terminal. Specially made for profiling
def xtest_multicurierac(target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers):
    # target_ids =  ["NCBIGene:3693", "NCBIGene:19894", "NCBIGene:2778", "NCBIGene:7070", "NCBIGene:103178432"]
    # target = 'gene'
    # source_id = 'chemical'
    # input_category = 'biolink:Gene'
    # output_category = 'biolink:ChemicalEntity'
    # predicate = 'affects'
    # qualifiers = 'increased_activity'
# def test_pathfinderac(target_ids =[], target = '', input_category = '', source_ids='', source = '', output_category='',  predicate='', qualifiers='')
# def test_pathfinderac():
##Sources: https://link.springer.com/article/10.1007/s41048-019-0086-2
    # target_ids = ['JUN', 'GDI1', 'GNAI2']#["NCBIGene:3693", "NCBIGene:19894", "NCBIGene:2778", "NCBIGene:7070", "NCBIGene:103178432"]
    # target_ids= ["NCBIGene:3693", "NCBIGene:19894", "NCBIGene:2778", "NCBIGene:7070", "NCBIGene:103178432"]
    # target_ids = ['NPM1','FLT3','NRAS','BCL2']
    # target='gene'
    # target_category='biolink:Gene'
    # predicate= ['biolink:genetically_associated_with', 'biolink:genetic_association',
    #             'biolink:genetically_interacts_with', 'biolink:physically_interacts_with',
    #             'biolink:interacts_with', 'biolink:directly_physically_interacts_with', 'biolink:binds']
    #                                       #'biolink:affects'
    # source_ids=None
    # source='genes'
    # source_category='biolink:Gene'
    # qualifiers = 'increased_activity'
    # qualifiers=''

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

        # print('=====: ', target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers, end='\n')
        answerset = get_qg(target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers)
        # print(answerset)
    with cProfile.Profile() as profile:
        newset = snc.coalesce(answerset, method='graph')
    s = io.StringIO()
    stats = pstats.Stats(profile)
    nodeset = {}; question = ''
    for qg_id, node_data in newset.get("query_graph", {}).get("nodes", {}).items():
        if 'ids' in node_data and node_data.get('is_set'):
            nodeset = set(node_data.get('ids', []))
            question = qg_id
    print()
    print(f"*** {len(newset['results'])} *** results returned")
    print(f"nodeset: {nodeset}")
    #uncomment this to save the result to the directory
    # with open(f"newset{datetime.now()}.json", 'w') as outf:
    #     json.dump(newset, outf, indent=4)
    assert PDResponse.parse_obj({'message': newset})
    if newset['results']:
        print(f"Samples: {[newset['knowledge_graph']['nodes'][idx]['name'] for idx in random.sample(list(set(newset['knowledge_graph']['nodes']).difference(nodeset)), 2)]}")
    assert len(newset['results']) >= len(nodeset)

    excluded_function =["getEffectiveLevel", "<method 'isalnum' of 'str' objects>", "<method '__exit__' of '_thread.lock' objects>", "<method 'pop' of 'list' objects>", "__enter__", "disable", "owns_connection", "connect", "<method 'close' of '_io.BytesIO' objects>", "<method 'sort' of 'list' objects>", "<method 'keys' of 'dict' objects>",
                        "<method 'connect' of '_socket.socket' objects>", "_releaseLock", "<method 'acquire' of '_thread.RLock' objects>", "get_connection",
                        "<method 'truncate' of '_io.BytesIO' objects>", "close", "_releaseLock", "_connect", "<method 'replace' of 'str' objects>",
                        "getaddrinfo", "<method 'replace' of 'str' objects>", "<method 'add' of 'set' objects>",  "<method 'rpartition' of 'str' objects>", '<genexpr>', '<lambda>',  '<listcomp>', '<dictcomp>', "<method 'disable' of '_lsprof.Profiler' objects>", "<method 'values' of 'dict' objects>", "<method 'release' of '_thread.RLock' objects>", "<method 'remove' of 'set' objects>",
                        "getaddrinfo", "__exit__", "__init__", "check_health", "<method 'replace' of 'str' objects>", "<method 'add' of 'set' objects>",  "<method 'rpartition' of 'str' objects>", '<genexpr>', '<lambda>',  '<listcomp>', '<dictcomp>', "<method 'disable' of '_lsprof.Profiler' objects>", "<method 'values' of 'dict' objects>",
                        "<method 'end' of 're.Match' objects>",  "length", "__del__", "<method 'items' of 'dict' objects>", "<method 'release' of '_thread.RLock' objects>", "<method 'remove' of 'set' objects>"]
    target_functions = ['graph_coalescer.py', 'single_node_coalescer.py', 'property_coalesce.py', 'component.py']
    targetdict = {'graph_coalescer.py':'gc', 'single_node_coalescer.py': 'snc', 'property_coalesce.py':'pc'}
    stats.strip_dirs()
    stats.sort_stats('filename')
    stats.print_stats()

    filtered_stats = [(key, stats.stats[key]) for key in stats.stats
                      if key[-1] not in excluded_function and '<built-in' not in key[-1] and key[0] in target_functions]
    stats_data = {
        'ncalls': [data[0] for key, data in filtered_stats],
        # 'tottime': [data[2] for key, data in filtered_stats],
        # 'percall_tottime': [data[2] / data[0] if data[0] != 0 else 0 for key, data in filtered_stats],
        'cumtime': [data[3] for key, data in filtered_stats],
        # 'percall_cumtime': [data[3] / data[0] if data[0] != 0 else 0 for key, data in filtered_stats],
        'filename(function)': [targetdict.get(key[0]) + '_' + key[-1] for key, data in filtered_stats]
    }

    cumtime = np.array(stats_data['cumtime'])
    sorted_indices = np.argsort(cumtime)[::-1]
    filename_function = np.array(stats_data['filename(function)'])[sorted_indices]
    ncalls = np.array(stats_data['ncalls'])[sorted_indices]
    # tottime = np.array(stats_data['tottime'])[sorted_indices]
    # percall_tottime = np.array(stats_data['percall_tottime'])[sorted_indices]
    # percall_cumtime = np.array(stats_data['percall_cumtime'])[sorted_indices]
    cumtime = cumtime[sorted_indices]

    rows = list(zip(filename_function, ncalls, cumtime))

    headers = ["Function", "ncalls", "cumtime"]

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
    # plt.title(f"Cumulative Time for the Functions {len(nodeset)} {question}set")
    # plt.xlabel("Functions")
    # plt.ylabel("Cumulative Time (secs)")
    # plt.legend()
    # plt.grid(linewidth=0.1)
    # plt.tight_layout()
    # plt.show()

def get_qg(target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers=None):
    query_template = Template(qg_template())
    query = {}
    source_ids = source_ids if source_ids== None else []
    # print('source_ids: ', source_ids)
    is_source = True if source_ids else False
    # print('is_source: ', is_source)
    if isinstance(predicate, str):
        predicate = predicate.split(',')
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
                                           target_category=json.dumps([target_category]), predicate=json.dumps(predicate),
                                           qualifier= json.dumps(quali))

    try:
        query = json.loads(qs)

        if is_source:
            del query["query_graph"]["nodes"][target]["ids"]
        else:
            del query["query_graph"]["nodes"][source]["ids"]
    except UnicodeDecodeError as e:
        print(e)
    print(query)
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
    xtest_multicurierac(target_ids, target, target_category, predicate, source_ids, source, source_category, qualifiers)
