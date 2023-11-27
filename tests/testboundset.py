import pytest
import os, json
import src.graph_coalescence.graph_coalescer as gc
import src.single_node_coalescer as snc
from reasoner_pydantic import Response as PDResponse
from datetime import datetime

jsondir ='InputJson_1.4'

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
                "nodesets_to_exclude": ["MONDO:0001", 'MONDO:00002']
            }
        }
    ]})


def test_all_coalesce_with_workflow():
    """Make sure that results are well formed."""
    dir_path = os.path.dirname(os.path.realpath(__file__))
    testfilename = os.path.join(dir_path, jsondir, 'sampleset.json')
    with open(testfilename, 'r') as tf:
        answerset = json.load(tf)
        # assert PDResponse.parse_obj(answerset)
        answerset = answerset['message']
    # Some of these edges are old, we need to know which ones...
    # now generate new answers
    newset = snc.coalesce(answerset, method='graph')
    with open(f"newset{datetime.now()}.json", 'w') as outf:
        json.dump(newset, outf, indent=4)
    assert PDResponse.parse_obj({'message': newset})
    # Must be at least the length of the initial answers

    # assert len(newset['results']) == len(answerset['results'])

