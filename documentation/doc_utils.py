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