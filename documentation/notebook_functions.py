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
