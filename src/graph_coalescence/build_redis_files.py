import csv
from collections import defaultdict
import json,jsonlines

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

def go():
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
    """
    categories = {}
    catcount = defaultdict(int)
    with jsonlines.open('nodes.jsonl','r') as nodefile, open('nodelabels.txt','w') as labelfile, open('nodenames.txt','w') as namefile:
        for node in nodefile:
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
    with open('category_count.txt','w') as catcountout:
        for c,v in catcount.items():
            catcountout.write(f'{c}\t{v}\n')
    with jsonlines.open('edges.jsonl','r') as inf, open('prov.txt','w') as provout:
        nl = 0
        for line in inf:
            nl += 1
            source_id = line['subject']
            target_id = line['object']
            pred = line['predicate']
            #Remove variant/anatomy edges from GTEX.  These are going away in the new load anyway
            if source_id.startswith('CAID'):
                if target_id.startswith('UBERON'):
                    if pred == 'biolink:affects_expression_of':
                        continue
            if source_id.startswith('UBERON'):
                if target_id.startswith('NCBIGene'):
                    if pred == 'biolink:expresses':
                        continue
            if pred == 'biolink:expressed_in' and target_id.startswith('UBERON'):
                continue
            source_link = (target_id,pred,True)
            target_link = (source_id,pred,False)
            nodes_to_links[source_id].append(source_link)
            nodes_to_links[target_id].append(target_link)
            for tcategory in categories[target_id]:
                edgecounts[ (source_id, pred, True, tcategory) ] += 1
            for scategory in categories[source_id]:
                edgecounts[ (target_id, pred, False, scategory) ] += 1
            pkey=f'{source_id} {pred} {target_id}'
            prov = {x:line[x] for x in ['biolink:original_knowledge_source','biolink:aggregator_knowledge_source'] if x in line}
            provout.write(f'{pkey}\t{json.dumps(prov)}\n')
            if nl % 1000000 == 0:
                print(nl)
        print('node labels and names done')

    with open('links.txt','w') as outf:
        for node,links in nodes_to_links.items():
            outf.write(f'{node}\t{json.dumps(links)}\n')
        print('links done')

    with open('backlinks.txt','w') as outf:
        for key,value in edgecounts.items():
            outf.write(f'{key}\t{value}\n')
        print('backlinks done')


if __name__ == '__main__':
    go()
