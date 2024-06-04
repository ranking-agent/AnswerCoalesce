import json

def load_jsons(input_json):
    """Given an MCQ json, get the member_ids of the qnodes"""
    with open(input_json,'r') as inf:
        data = json.load(inf)

    node_ids = set()
    for nid,node in data['message']['query_graph']['nodes'].items():
        if 'member_ids' in node:
            node_ids.update(node['member_ids'])

    print(input_json, len(node_ids))

    # remove nodes that have empty curies
    #qg_node_ids = set( [node['curie'][0] for node in data['query_graph']['nodes'] if 'curie' in node and node['curie'] is not None])

    #node_ids.difference_update(qg_node_ids)

    return node_ids

def collect_input_nodes():
    #These are curies that are used as the inputs to some graph coalesce test
    test_curies = set(['NCBIGene:106632262', 'NCBIGene:106632263', 'NCBIGene:106632261'])
    test_curies.update( set(['NCBIGene:191', 'NCBIGene:55832', 'NCBIGene:645', 'NCBIGene:54884', 'NCBIGene:8239',
                             'NCBIGene:4175', 'NCBIGene:10469', 'NCBIGene:8120', 'NCBIGene:3840', 'NCBIGene:55705',
                             'NCBIGene:2597', 'NCBIGene:23066', 'NCBIGene:7514', 'NCBIGene:10128']))
    # We used to use bigger_new, but it makes the link files too big for github
    #input_jsons = ['famcov_new.json','graph_named_thing_issue.json','EdgeIDAsStrAndPerfTest.json']
    input_jsons = ['famcov_new_with_params_and_pcut1e7_MCQ.json']
    for ij in input_jsons:
        test_curies.update( load_jsons('InputJson_1.5/'+ij) )
    #test_curies.update( load_jsons('InputJson_1.4/qualified.json'))
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
    for edge in ['NCBIGene:1500 {"predicate": "biolink:interacts_with"} NCBIGene:2932', 'NCBIGene:2932 {"predicate": "biolink:interacts_with"} NCBIGene:1500']:
        if edge in edges:
            print('found it:',edge)
        else:
            print('did not find it:',edge)

    return link_ids,edges

def filter_backlinks(infname,outfname,stypes,link_ids):
    with open(infname,'r') as inf, open(outfname,'w') as outf:
        for line in inf:
            x = line.strip().split("'")
            if x[1] in link_ids and x[5] in stypes:
                outf.write(line)

def filter_prov(infname,outfname,edges):
    """There is a very annoying thing happening where the direction of the edge and the direction
    of the prov are different, so we can't look for the edge directly, we need to break it up I guess"""
    #First chop up all the edges.  The edges are strings.  We need to separate them by tabs, put the chunks
    # into a frozenset and make a set of those
    edges_by_part = set( [frozenset(edge.split()) for edge in edges] )
    with open(infname,'r') as inf, open(outfname,'w') as outf:
        for line in inf:
            x = line.strip().split("\t")
            # Now split x[0] in the same way
            edge_parts = frozenset(x[0].split())
            if edge_parts in edges_by_part:
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
    #Note that we're not getting EVERYthing that could be used, just a subset to make things manageable.
    # But it does mean that you have to be a little careful in the testing and be aware of what is going on.
    back_types = set(['biolink:Gene','biolink:NamedThing','biolink:SmallMolecule','biolink:Disease'])
    filter_backlinks('../src/graph_coalescence/backlinks.txt','test_backlinks.txt',back_types,links)
    filter_prov('../src/graph_coalescence/prov.txt','test_prov.txt',edges)
    nodes.update(links)
    filter_types('../src/graph_coalescence/nodelabels.txt','test_nodelabels.txt',nodes)
    #names has the same format as types
    filter_types('../src/graph_coalescence/nodenames.txt','test_nodenames.txt',nodes)

if __name__ == '__main__':
    go()