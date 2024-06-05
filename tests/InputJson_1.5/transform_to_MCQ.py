#In older versions of AC, we were starting with a file that had already been run, i.e. with the result of a query.
# In MCQ we are just taking the stuff to be enriched as part of the query graph itself.
# We already have a lot of test cases in that original format, and the point of this is to transform
# them into McQ format so that we can keep the good tests.

# So we will have a query graph with some input and output nodes.  The output node of the original query
# will be the one that we want to transform into the input node of the new query.  We'll want to get rid of all the
# other query nodes and create one new output node.  We'll need to find all the nodes bound to that original
# output nodes and put them into the member_ids of the new input node.  The knowledge graph needs to include
# only this list of member nodes.  No edges.   The results and auxiliary graphs should also be set to empty.

# We will also need to create a new query edge connecting the new input node to the new output node.

import json

def run(input_filename, output_filename, original_output_qnode, new_input_category = "biolink:NamedThing"):
    """Transform the input json file into an MCQ format."""
    # Load the input json file
    with open(input_filename, "r") as file:
        in_message = json.load(file)
    input_nodes = get_bound_nodes(in_message, original_output_qnode)
    # Make a new message
    new_message = {
        "message": {
            "query_graph": {
                "edges": {
                    "e1": {
                        "subject": "input",
                        "object": "output"
                    }
                },
                "nodes": {
                    "input": {
                        "ids": ["uuid:1"],
                        "categories": [new_input_category],
                        "set_interpretation": "MANY",
                        "member_ids": input_nodes
                    },
                    "output": {
                        "categories": ["biolink:NamedThing"],
                    }
                }
            },
            "knowledge_graph": {
                "nodes": {node: in_message["message"]["knowledge_graph"]["nodes"][node] for node in input_nodes},
                "edges": {}
            },
            "results": [],
            "auxiliary_graphs": {}
        }
    }
    rewrite_parameters(in_message, new_message)
    # write the new message to a file
    with open(output_filename, "w") as file:
        json.dump(new_message, file, indent=2)

def rewrite_parameters(in_message, new_message):
    """The old message may have a workflow object like this:
        "workflow": [
        {
            "id": "enrich_results",
            "parameters": {"pvalue_threshold": 1e-7,
            "predicates_to_exclude": [
                "biolink:causes", "biolink:biomarker_for", "biolink:biomarker_for", "biolink:contraindicated_for",
                "biolink:contributes_to", "biolink:has_adverse_event", "biolink:causes_adverse_event"
            ]
}
        }
    ]
    If this exists next to "message", and if it has a "parameters" in it, then we want to put that parameters
    object into the new envelope
    """
    if "workflow" in in_message:
        for step in in_message["workflow"]:
            if "parameters" in step:
                new_message["parameters"] = step["parameters"]

def get_bound_nodes(in_message, output_qnode):
    """Get the nodes bound to the output_qnode."""
    bound_nodes = set()
    for result in in_message["message"]["results"]:
        if result["node_bindings"][output_qnode]:
            bound_nodes.update([x["id"] for x in result["node_bindings"][output_qnode]])
    return list(bound_nodes)

if __name__ == "__main__":
    run("famcov_new_with_params_and_pcut1e7.json",
        "famcov_new_with_params_and_pcut1e7_MCQ.json",
        "b", "biolink:Disease")