import cProfile
import pstats
import builtins
import pytest
import os, json
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

def test_profile():
    name = 'ArthrochalasiaEhlers-Danlos.json'
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, common_diseasesdir, name)
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        answerset = answerset['message']

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

