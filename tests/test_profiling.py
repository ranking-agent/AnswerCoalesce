import cProfile
import pstats
import builtins
import requests
import pytest
import os, sys, json
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from reasoner_pydantic import Response as PDResponse

def set_workflowparams(lookup_results):
    # Dummy parameters to check igf reasoner pydantic accepts the new parameters
    return lookup_results.update({"workflow": [
        {
            "id": "enrich_results",
            "parameters":
            {
                "predicates_to_exclude": ["biolink:causes", "biolink:biomarker_for", "biolink:biomarker_for", "biolink:contraindicated_for",
                    "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"],
                "properties_to_exclude": ["CHEBI_ROLE_drug", 'CHEBI_ROLE_pharmaceutical', 'CHEBI_ROLE_pharmacological_role'],
            }
        }
    ]})


common_diseasesdir = 'CommonDiseases'


def xtest_profile(name, idx):
    req = requests.get(f"https://ars.test.transltr.io/ars/api/messages/{idx}")
    answerset = req.json()['fields']['data']

    predicates_to_exclude = None
    pvalue_threshold = None
    properties_to_exclude = None
    # set_workflowparams(answerset)
    # if 'workflow' in answerset and 'parameters' in answerset['workflow'][0]:
    #     pvalue_threshold = answerset.get('workflow')[0].get('parameters').get('pvalue_threshold', 0)
    #     predicates_to_exclude = answerset.get('workflow')[0].get('parameters').get('predicates_to_exclude', None)
    #     properties_to_exclude = answerset.get('workflow', [])[0].get('parameters').get('properties_to_exclude', None)

    answerset = answerset['message']

    print(f'\n==Coalesce for{name}===')
    #now generate new answers
    # Local redis only do property enrichment because there is no sufficient datss for graph enrichment
    with cProfile.Profile() as profile:
        newset = snc.coalesce(answerset, method='all', predicates_to_exclude= predicates_to_exclude, properties_to_exclude=properties_to_exclude, pvalue_threshold=pvalue_threshold)
    stats= pstats.Stats(profile)
    stats.strip_dirs().sort_stats("filename")
    stats.print_stats()
    aux = newset['message']['auxiliary_graphs']
    if aux:
        count_n_ac = sum(1 for key in aux.keys() if '_n_ac' in key)
        count_e_ac = sum(1 for key in aux.keys() if '_e_ac' in key)
        print(f'{"*" * 30}')
        print(f"*Count of '_n_ac' pattern keys: {count_n_ac} *")
        print(f"*Count of '_e_ac' pattern keys: {count_e_ac} *")
        print(f'{"*" * 30}')


if __name__ == '__main__':
    if len(sys.argv) < 3:
        border = "*" * 60
        print(border)
        print("* Usage: python test_profiling.py 'alzheimers' '47674b0d-3a50-4272-a3bd-a50c3bbba322' *")
        print("* Usage: python test_profiling.py 'castleman' '513e239f-e00e-4397-97fc-91beb09df868' *")
        print("* Usage: python test_profiling.py 'Bethlem_myopathy' '21c78af9-4055-4407-afa4-6ba9a7994719' *")
        print("* Usage: python test_profiling.py 'hyperlipidemia' '3a258bce-725c-4119-8ef5-79bd87386241' *")
        print("* OR ********************")
        print("* 1. Go to: https://ui.test.transltr.io/main and search for a disease *")
        print("* 1.1 Copy the search id from the address bar eg. f6a1ed69-b09a-4376-87e5-424b145fe446 *")
        print("* 2. Go to: https://ars.test.transltr.io/ars/api/messages/ and append the id eg https://ars.test.transltr.io/ars/api/messages/f6a1ed69-b09a-4376-87e5-424b145fe446 *")
        print("* Look for the merged_version and copy the value eg 513e239f-e00e-4397-97fc-91beb09df868 *")
        print("* 3. Enter the value as an argument *")
        print(border)
    else:
        name = sys.argv[1]
        idx = sys.argv[2]
        xtest_profile(name, idx)


