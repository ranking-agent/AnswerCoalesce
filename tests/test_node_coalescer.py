import pytest
from copy import deepcopy
import json, os, asyncio
import src.single_node_coalescer as snc
from collections import defaultdict
#from src.components import PropertyPatch,Answer
from reasoner_pydantic import Response as PDResponse


def make_answer_set():
    # This test is based on a kg that looks like
    #           D
    #         /   \
    #   A - B - E - G
    #     \   X   /     (the X is a path from B-F and one from C-E
    #       C - F
    # And the answers trace al paths from A to G
    # ABEG, ABDG, ABFG, ACFG, ACEG

    #Create the testing KG
    nodenames ='ABCDEFG'
    nodes = {n: {"category":"biolink:NamedThing"} for n in nodenames}
    inputedges = ['AB','AC','BD','BE','BF','CE','CF','DG','EG','FG']
    edges = {e:{ "subject":e[0], "object":e[1], "predicate":"biolink:related_to"} for e in inputedges}
    kg = {'nodes': nodes, 'edges':edges}
    #Create the QG
    qnodes = {'n0':{'id':'A','categories':'biolink:NamedThing'},'n1':{'categories':'biolink:NamedThing'},
              'n2':{'categories':'biolink:NamedThing'},'n3':{'id':'D','categories':'biolink:NamedThing'}}
    qedges = {'e0':{'subject':'n0','object':'n1'},
              'e1':{'subject':'n1','object':'n2'},
              'e2':{'subject':'n2','object':'n3'}}
    qg = {'nodes':qnodes, 'edges':qedges}
    ans = ['ABEG','ABDG','ABFG','ACFG','ACEG']
    answers = []
    analyses = []
    tempdict = {}
    for i,a in enumerate(ans):
        nb = {f'n{i}': [ {'id': xi} for xi in x] for i,x in enumerate(a)}
        eb = {f'e{i}': [{'id':f'{a[i]}{a[i+1]}'}] for i in range(len(a)-1)}
        tempdict.update({"resource_id": "infores:automat-robokop"})
        tempdict.update({"edge_bindings": eb })
        tempdict.update({'score': 10-i})
        analyses.append(tempdict)
        assert len(eb) == len(nb) -1
        answers.append( {'node_bindings':nb, 'analyses':analyses})
    answerset = {'query_graph': qg, 'knowledge_graph':kg, 'results': answers}
    return answerset


def test_double_predicates():
    # This test is based on a kg that looks like
    #   B
    #  / \
    # A  D
    #  \/
    #  C
    # Except all the edges are doubled (there are 2 predicates between each)

    #Create the testing KG
    nodenames ='ABCD'
    nodes = { n:{"category":"biolink:NamedThing"} for n in nodenames}
    inputedges = ['AB','AC','BD','CD']
    edges = {f'r{e}': {"subject":e[0], "object":e[1], "predicate":"biolink:related_to"} for e in inputedges}
    edges.update({f'a{e}':{ "subject":e[0], "object":e[1], "predicate":"biolink:also_related_to"} for e in inputedges})
    kg = {'nodes': nodes, 'edges':edges}
    #Create the QG
    qnodes = {'n0':{'id':'A','categories':'biolink:NamedThing'},'n1':{'categories':'biolink:NamedThing'},
              'n2':{'id':'D','categories':'biolink:NamedThing'}}
    qedges = {'e0':{'subject':'n0','object':'n1'},
              'e1':{'subject':'n1','object':'n2'}}
    qg = {'nodes':qnodes, 'edges':qedges}
    ans = ['ABD','ACD']
    answers = []
    for i,a in enumerate(ans):
        nb = {f'n{i}': [{'id': x}] for i,x in enumerate(a)}
        eb = {f'e{i}': [{'id':f'r{a[i]}{a[i+1]}'},{'id':f'a{a[i]}{a[i+1]}'}] for i in range(len(a)-1)}
        assert len(eb) == len(nb) -1
        answers.append( {'node_bindings':nb, 'edge_bindings':eb, 'score': 10-i})
    answerset = {'query_graph': qg, 'knowledge_graph':kg, 'results': snc.is_trapi1_4(answers)}
    #Now, this answerset should produce 1 single opportunity
    groups = snc.identify_coalescent_nodes(answerset)
    assert len(groups) == 1
    print(groups)
