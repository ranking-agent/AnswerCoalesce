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
    input_jsons = ['famcov_new.json','bigger_new.json','graph_named_thing_issue.json','EdgeIDAsStrAndPerfTest.json']
    for ij in input_jsons:
        test_curies.update( load_jsons('InputJson_1.1/'+ij) )
    return test_curies

def filter_links(infname,outfname,input_nodes):
    link_ids = set()
    with open(infname,'r') as inf, open(outfname,'w') as outf:
        for line in inf:
            x = line.strip().split('\t')
            if x[0] in input_nodes:
                outf.write(line)
                some_links = json.loads(x[1])
                nodes = [sl[0] for sl in some_links]
                link_ids.update(nodes)
    return link_ids

def filter_backlinks(infname,outfname,stypes,link_ids):
    with open(infname,'r') as inf, open(outfname,'w') as outf:
        for line in inf:
            x = line.strip().split("'")
            if x[1] in link_ids and x[5] in stypes:
                outf.write(line)


def filter_types(infname,outfname,idents):
    with open(infname, 'r') as inf, open(outfname, 'w') as outf:
        for line in inf:
            x = line.strip().split("\t")
            if x[0] in idents:
                outf.write(line)

def go():
    nodes = collect_input_nodes()
    links = filter_links('../src/graph_coalescence/links.txt','test_links.txt',nodes)
    back_types = set(['biolink:Gene','biolink:NamedThing','biolink:ChemicalEntity'])
    filter_backlinks('../src/graph_coalescence/backlinks.txt','test_backlinks.txt',back_types,links)
    nodes.update(links)
    filter_types('../src/graph_coalescence/nodelabels.txt','test_nodelabels.txt',nodes)

if __name__ == '__main__':
    go()
