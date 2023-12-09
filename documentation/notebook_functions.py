def reasonerGraphToCytoscape(graph):
    csGraph = {}
    nodes = []
    edges = []
    for node in graph["nodes"]:
        csNode = {}
        node_types = ""
        if isinstance(node["type"], str):
            node_types = node["type"]
        else:
            node_types = "\n".join(node["type"])
        csNode["data"] = {"id": node["id"], "label": node_types + "\n[" + node.get("curie", "") + "]", "curie": node.get("curie", ""), "type": node_types}
        nodes.append(csNode)
    for edge in graph["edges"]:
        csEdge = {
            "data": {
                "id": edge["id"],
                "source": edge["source_id"],
                "target": edge["target_id"],
                "label": edge["type"]
            }
        }
        edges.append(csEdge)
    csGraph["elements"] = {"nodes": nodes, "edges": edges}
    csGraph["style"] = [
        { "selector": 'node', "style": {
            'label': 'data(label)',
            'color': 'white',
            'background-color': '#60f', # #009 looks good too
            'shape': 'rectangle',
            'text-valign': 'center',
            'text-border-style': 'solid',
            'text-border-width': 5,
            'text-border-color': 'red',
            'width': '15em',
            'height': '5em',
            'text-wrap': 'wrap'
        } }, 
        {"selector": "edge", "style": {
            "curve-style": "unbundled-bezier",
            # "control-point-distances": [20, -20],
            # "control-point-weights": [0.250, 0.75],
            "control-point-distances": [-20, 20],
            "control-point-weights": [0.5],
            'content': 'data(label)',
            'line-color': '#808080',
            'target-arrow-color': '#808080',
            'target-arrow-shape': 'triangle',
            'target-arrow-fill': 'filled'}
        }
    ]
                       
    #print(json.dumps(csGraph, indent=4))
    return csGraph

def knowledgeGraphToCytoscape(graph):
    csGraph = {}
    nodes = []
    edges = []
    for node in graph["nodes"]:
        csNode = {}
        node_types = ""
        if isinstance(node["type"], str):
            node_types = node["type"]
        else:
            node_types = "\n".join(node["type"])
        csNode["data"] = {"id": node["id"], "label": (node["name"] or " ") + "\n[" + node["id"] + "]", "curie": node["id"], "type": node_types}
        nodes.append(csNode)
    for edge in graph["edges"]:
        csEdge = {
            "data": {
                "id": edge["id"],
                "source": edge["source_id"],
                "target": edge["target_id"],
                "label": edge["type"]
            }
        }
        edges.append(csEdge)
    csGraph["elements"] = {"nodes": nodes, "edges": edges}
    csGraph["style"] = [
        { "selector": 'node', "style": {
            'label': 'data(label)',
            'color': 'white',
            'background-color': '#60f', # #009 looks good too
            'shape': 'rectangle',
            'text-valign': 'center',
            'text-border-style': 'solid',
            'text-border-width': 5,
            'text-border-color': 'red',
            'width': '20em',
            'height': '5em',
            'text-wrap': 'wrap'
        } }, 
        {"selector": "edge", "style": {
            "curve-style": "unbundled-bezier",
            # "control-point-distances": [20, -20],
            # "control-point-weights": [0.250, 0.75],
            "control-point-distances": [-20, 20],
            "control-point-weights": [0.5],
            'content': 'data(label)',
            'line-color': '#808080',
            'target-arrow-color': '#808080',
            'target-arrow-shape': 'triangle',
            'target-arrow-fill': 'filled'}
        }
    ]
                       
    #print(json.dumps(csGraph, indent=4))
    return csGraph

def answerGraphToCytoscape(answer,knowledge_graph):
    csGraph = {}
    nodes = []
    edges = []
    node_kg_ids = set()
    edge_kg_ids = set()
    for nodeb in answer['node_bindings']:
        nbk = nodeb['kg_id']
        if isinstance(nbk,list):
            node_kg_ids.update(nbk)
        else:
            node_kg_ids.add(nbk)
    for edgeb in answer['edge_bindings']:
        ebk = edgeb['kg_id']
        if isinstance(ebk,list):
            edge_kg_ids.update(ebk)
        else:
            edge_kg_ids.add(ebk)
    for node in knowledge_graph["nodes"]:
        if node['id'] not in node_kg_ids:
            continue
        csNode = {}
        node_types = ""
        if isinstance(node["type"], str):
            node_types = node["type"]
        else:
            node_types = "\n".join(node["type"])
        if 'name' not in node:
            node['name'] = ''
        csNode["data"] = {"id": node["id"], "label": (node["name"] or " ") + "\n[" + node["id"] + "]", "curie": node["id"], "type": node_types}
        nodes.append(csNode)
    for edge in knowledge_graph["edges"]:
        if edge['id'] not in edge_kg_ids:
                continue
        csEdge = {
            "data": {
                "id": edge["id"],
                "source": edge["source_id"],
                "target": edge["target_id"],
                "label": edge["type"]
            }
        }
        edges.append(csEdge)
    csGraph["elements"] = {"nodes": nodes, "edges": edges}
    csGraph["style"] = [
        { "selector": 'node', "style": {
            'label': 'data(label)',
            'color': 'white',
            'background-color': '#60f', # #009 looks good too
            'shape': 'rectangle',
            'text-valign': 'center',
            'text-border-style': 'solid',
            'text-border-width': 5,
            'text-border-color': 'red',
            'width': '20em',
            'height': '5em',
            'text-wrap': 'wrap'
        } },
        {"selector": "edge", "style": {
            "curve-style": "unbundled-bezier",
            # "control-point-distances": [20, -20],
            # "control-point-weights": [0.250, 0.75],
            "control-point-distances": [-20, 20],
            "control-point-weights": [0.5],
            'content': 'data(label)',
            'line-color': '#808080',
            'target-arrow-color': '#808080',
            'target-arrow-shape': 'triangle',
            'target-arrow-fill': 'filled'}
        }
    ]

    #print(json.dumps(csGraph, indent=4))
    return csGraph


def get_enriched_results(res):
    return list(filter(lambda message: message['enrichments'], res))



def get_enrichments2results(r):
    """
    params: result_message
    return: 
    """
    results = r["message"]["results"]
    result_to_enrichments = {}
    enrichments_to_results = {}
    for result in results:
        keys = [key for key in result['node_bindings'] if not 'qnode_id' in result['node_bindings'][key][0]]
        k = keys[0]
        identifier = result["node_bindings"][k][0]["id"]
        name = r["message"]["knowledge_graph"]["nodes"][identifier]["name"]
        name = identifier
        result_to_enrichments[name] = result["enrichments"]
    for result, enrichments in result_to_enrichments.items():
        for enrichment in enrichments:
            if enrichment not in enrichments_to_results:
                enrichments_to_results[enrichment] = []
            enrichments_to_results[enrichment].append(result)
    return enrichments_to_results