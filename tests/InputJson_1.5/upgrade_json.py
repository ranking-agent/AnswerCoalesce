# This script will upgrade TRAPI messages from 1.4 to 1.5.
import os
import json

def main():
    # Get all the TRAPI messages in files called "*_1.4.json" and parse them into "*.json"
    filenames = [f for f in os.listdir() if f.endswith("_1.4.json")]
    for filename in filenames:
        with open(filename,"r") as f:
            message = json.load(f)
            newmessage = upgrade(message)
        with open(filename[:-9]+".json","w") as f:
            json.dump(newmessage,f,indent=2)

def upgrade(message):
    message = add_attributes_to_node_bindings(message)
    message = add_attributes_to_edge_bindings(message)
    return message

def add_attributes_to_node_bindings(message):
    """NODE bindings are found in message["message"]["results"][i]["node_bindings"].
    node binding is structured like {'n0': [{'id': 'CHEBI:18295'}], 'n1': [{'id': 'MONDO:0004979'}]}
    And we need to transform it to look like {'n0': [{'id': 'CHEBI:18295', 'attributes': []}], 'n1': [{'id': 'MONDO:0004979', 'attributes':[]}]}{"""
    for result in message["message"]["results"]:
        for node,bindings in result["node_bindings"].items():
            for binding in bindings:
                binding["attributes"] = []
    return message

def add_attributes_to_edge_bindings(message):
    """EDGE bindings are found in message["message"]["results"][i]["analyses"][j]["edge_bindings"].
    Each edge binding is structured like {'e0': [{'id': 'e0'}], 'e1': [{'id': 'e1'}]}, and we need to
    transform it to look like {'e0': [{'id': 'e0', 'attributes': []}], 'e1': [{'id': 'e1', 'attributes': []}]}."""
    for result in message["message"]["results"]:
        for analysis in result["analyses"]:
            for edge,bindings in analysis["edge_bindings"].items():
                for binding in bindings:
                    binding["attributes"] = []
    return message

if __name__ == "__main__":
    main()