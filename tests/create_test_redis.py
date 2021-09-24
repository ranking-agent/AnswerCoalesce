import json

def load_jsons(input_json):
    """Given a json file, find all the kg_ids for nodes, except any that are in the qg"""
    with open(input_json,'r') as inf:
        data = json.load(inf)
    node_ids = set( [node for node in data['message']['knowledge_graph']['nodes']])

    # remove nodes that have empty curies
    #qg_node_ids = set( [node['curie'][0] for node in data['query_graph']['nodes'] if 'curie' in node and node['curie'] is not None])

    #node_ids.difference_update(qg_node_ids)

    return node_ids

def collect_input_nodes():
    #These are curies that are used as the inputs to some graph coalesce test
    test_curies = set(['NCBIGene:106632262', 'NCBIGene:106632263', 'NCBIGene:106632261'])
    test_curies.update( set(['NCBIGene:191', 'NCBIGene:55832', 'NCBIGene:645', 'NCBIGene:54884', 'NCBIGene:8239', 'NCBIGene:4175', 'NCBIGene:10469', 'NCBIGene:8120', 'NCBIGene:3840', 'NCBIGene:55705', 'NCBIGene:2597', 'NCBIGene:23066', 'NCBIGene:7514', 'NCBIGene:10128']))
    input_jsons = ['famcov_new.json','bigger_new.json','graph_named_thing_issue.json','EdgeIDAsStrAndPerfTest.json']
    for ij in input_jsons:
        test_curies.update( load_jsons('InputJson_1.1/'+ij) )
    return test_curies

def filter_links(infname,outfname,input_nodes):
    link_ids = set()
    edges = set()
    with open(infname,'r') as inf, open(outfname,'w') as outf:
        for line in inf:
            x = line.strip().split('\t')
            if x[0] in input_nodes:
                outf.write(line)
                some_links = json.loads(x[1])
                nodes = [sl[0] for sl in some_links]
                link_ids.update(nodes)
                edges.update([f'{x[0]} {sl[1]} {sl[0]}' for sl in some_links if sl[2]])
                edges.update([f'{sl[0]} {sl[1]} {x[0]}' for sl in some_links if not sl[2]])
    return link_ids,edges

def filter_backlinks(infname,outfname,stypes,link_ids):
    with open(infname,'r') as inf, open(outfname,'w') as outf:
        for line in inf:
            x = line.strip().split("'")
            if x[1] in link_ids and x[5] in stypes:
                outf.write(line)

def filter_prov(infname,outfname,edges):
    with open(infname,'r') as inf, open(outfname,'w') as outf:
        for line in inf:
            x = line.strip().split("\t")
            if x[0] in edges:
                outf.write(line)

def filter_types(infname,outfname,idents):
    with open(infname, 'r') as inf, open(outfname, 'w') as outf:
        for line in inf:
            x = line.strip().split("\t")
            if x[0] in idents:
                outf.write(line)

def go():
    nodes = collect_input_nodes()
    links,edges = filter_links('../src/graph_coalescence/links.txt','test_links.txt',nodes)
    back_types = set(['biolink:Gene','biolink:NamedThing','biolink:ChemicalEntity'])
    filter_backlinks('../src/graph_coalescence/backlinks.txt','test_backlinks.txt',back_types,links)
    filter_prov('../src/graph_coalescence/prov.txt','test_prov.txt',edges)
    nodes.update(links)
    filter_types('../src/graph_coalescence/nodelabels.txt','test_nodelabels.txt',nodes)
    #names has the same format as types
    filter_types('../src/graph_coalescence/nodenames.txt','test_nodenames.txt',nodes)

if __name__ == '__main__':
    go()
