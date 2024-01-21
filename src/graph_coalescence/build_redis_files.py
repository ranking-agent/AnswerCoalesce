import csv
from collections import defaultdict
import json,jsonlines
import requests
from bmt import Toolkit

#A link is: link = (other_node, predicate, source)
# source is a boolean that is true if node is the source, and false if other_node is the source

def str2list(nlabels):
    x = nlabels[1:-1] #strip [ ]
    parts = x.split(',')
    labs = [ pi[1:-1] for pi in parts] #strip ""
    return labs

def add_labels(lfile,nid,nlabels,done):
    if nid in done:
        return
    labs = str2list(nlabels)
    lfile.write(f'{nid}\t{labs}\n')
    done.add(nid)


def parse_line(line):
    source_id = line['subject']
    target_id = line['object']
    pred = line['predicate']
    # Remove variant/anatomy edges from GTEX.  These are going away in the new load anyway
    if source_id.startswith('CAID'):
        if target_id.startswith('UBERON'):
            if pred == 'biolink:affects_expression_of':
                return source_id, target_id, None
    if source_id.startswith('UBERON'):
        if target_id.startswith('NCBIGene'):
            if pred == 'biolink:expresses':
                return source_id, target_id, None
    if pred == 'biolink:expressed_in' and target_id.startswith('UBERON'):
        return source_id, target_id, None
    predicate_parts = {'predicate': line['predicate']}
    for key,value in line.items():
        if 'qualifier' in key:
            predicate_parts[key] = value
    predicate_string = json.dumps(predicate_parts,sort_keys=True)
    return source_id, target_id, predicate_string, pred

def get_filter_nodes():
    """Pull the ARS blocklist of nodes that we don't want to return. This consists of a lot of UMLS terms
    that we don't have anyway, but also a bunch of very generic terms (Disease, Human) that are not useful
    and make lots of links in our database."""

    #At the moment, we are going to get the blocklist from my PR but this can very soon be replaced with
    # the real one
    blocklist_url = "https://raw.githubusercontent.com/cbizon/Relay/master/config/blocklist.json"
    #blocklist_url = "https://raw.githubusercontent.com/NCATSTranslator/Relay/master/config/blocklist.json"

    blocklist = json.loads(requests.get(blocklist_url).text)
    return set(blocklist)

def go(input_node_file="nodes.jsonl", output_nodelabels='nodelabels.txt', output_nodenames='nodenames.txt',
       output_category_count='category_count.txt', input_edge_file='edges.jsonl', output_prov='prov.txt',
       output_links='links.txt', output_backlinks='backlinks.txt'):
    """Given a dump of a graph a la robokop, produce 3 files:
    nodelabels.txt which is 2 columns, (id), (list of labels):
    CAID:CA13418922 ['named_thing', 'biological_entity', 'molecular_entity', 'genomic_entity', 'sequence_variant']
    MONDO:0005011   ['named_thing', 'biological_entity', 'disease', 'disease_or_phenotypic_feature']
    MONDO:0004955   ['named_thing', 'biological_entity', 'disease', 'disease_or_phenotypic_feature']
    EFO:0004612     ['named_thing', 'biological_entity', 'disease_or_phenotypic_feature', 'phenotypic_feature']
    EFO:0005110     ['named_thing', 'biological_entity', 'disease_or_phenotypic_feature', 'phenotypic_feature']
    links.txt:
    2 columns, id -> list of lists. Each element is (other_id, predicate, id is subject)
    CAID:CA13418922 [["MONDO:0005011", "has_phenotype", true], ["MONDO:0004955", "has_phenotype", true], ["EFO:0004612", "has_phenotype", true], ["EFO:0005110", "has_phenotype", true], ["EFO:0004639", "has_phenotype", true], ["EFO:0007759", "has_phenotype", true]
    backlinks.txt:
    Counts of how many of each type of link there are.
    ('CAID:CA13418922', 'has_phenotype', True, 'named_thing')       21
    ('CAID:CA13418922', 'has_phenotype', True, 'biological_entity') 21
    ('CAID:CA13418922', 'has_phenotype', True, 'disease')   3
    ('CAID:CA13418922', 'has_phenotype', True, 'disease_or_phenotypic_feature')     21
    This version reads KGX node and edge json files

    We are filtering nodes that are in the ARS blocklist, and predicates that clutter.
    We are also handling symmetric predicates.  In our links and backlinks we are going to merge both
     True and False (subject) edges into True. Then, in the TRAPI version, we'll need to be careful
     to make sure and look for the right thing, even if the input TRAPI is pointed into a False direction.
    """
    tk = Toolkit()
    filter_nodes = get_filter_nodes()
    filter_predicates = ["biolink:related_to_at_concept_level", "biolink:related_to_at_instance_level"]
    categories = {}
    catcount = defaultdict(int)
    with jsonlines.open(input_node_file,'r') as nodefile, open(output_nodelabels, 'w') as labelfile, open(output_nodenames, 'w') as namefile:
        for node in nodefile:
            if node["id"] in filter_nodes:
                continue
            labelfile.write(f'{node["id"]}\t{node["category"]}\n')
            categories[node["id"]] = node["category"]
            for c in node['category']:
                catcount[c] += 1
            name = node.get("name","")
            if name is not None:
                name = name.encode('ascii',errors='ignore').decode(encoding="utf-8")
            namefile.write(f'{node["id"]}\t{name}\n')
    nodes_to_links = defaultdict(list)
    edgecounts = defaultdict(int)
    with open(output_category_count, 'w') as catcountout:
        for c,v in catcount.items():
            catcountout.write(f'{c}\t{v}\n')
    with jsonlines.open(input_edge_file, 'r') as inf, open(output_prov, 'w') as provout:
        nl = 0
        for line in inf:
            nl += 1
            source_id, target_id, pred, just_predicate = parse_line(line)
            if source_id in filter_nodes or target_id in filter_nodes:
                continue
            if pred is None:
                continue
            if just_predicate in filter_predicates:
                continue
            source_link = (target_id,pred,True)
            #Here's how we're handling symmetric predicates.
            # The source link and count is going to be just the same, but we're going to modify the target link
            # to look like it's going from target to source.
            if tk.get_element(just_predicate)["symmetric"]:
                target_is_source = True
            else:
                target_is_source = False
            target_link = (source_id,pred,target_is_source)
            nodes_to_links[source_id].append(source_link)
            nodes_to_links[target_id].append(target_link)
            for tcategory in set(categories[target_id]):
                edgecounts[ (source_id, pred, True, tcategory) ] += 1
            for scategory in set(categories[source_id]):
                edgecounts[ (target_id, pred, target_is_source, scategory) ] += 1
            pkey=f'{source_id} {pred} {target_id}'
            prov = {x:line[x] for x in ['biolink:primary_knowledge_source','biolink:aggregator_knowledge_source'] if x in line}
            provout.write(f'{pkey}\t{json.dumps(prov)}\n')
            if nl % 1000000 == 0:
                print(nl)
        print('node labels and names done')

    with open(output_links, 'w') as outf:
        for node,links in nodes_to_links.items():
            outf.write(f'{node}\t{json.dumps(links)}\n')
        print('links done')

    with open(output_backlinks, 'w') as outf:
        for key,value in edgecounts.items():
            outf.write(f'{key}\t{value}\n')
        print('backlinks done')


if __name__ == '__main__':
    go()
