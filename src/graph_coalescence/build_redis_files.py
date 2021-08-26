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

def go_obsolete():
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
    This version reads a csv file created with this cypher query: WITH "MATCH path = (a)-[x]->(b)
    RETURN a.id AS source_id, labels(a) AS source_labels, type(x) AS predicate,
           b.id AS target_id, labels(b) AS target_labels" AS query
    CALL apoc.export.csv.query(query, "everything.csv", {})
    YIELD file, source, format, nodes, relationships, properties, time, rows, batchSize, batches, done, data
    RETURN file, source, format, nodes, relationships, properties, time, rows, batchSize, batches, done, data;
    """
    wrote_labels = set()
    nodes_to_links = defaultdict(list)
    edgecounts = defaultdict(int)
    with open('everything.csv','r') as inf, open('nodelabels.txt','w') as labelfile:
        reader = csv.DictReader(inf)
        nl = 0
        for line in reader:
            nl += 1
            source_id = line['source_id']
            target_id = line['target_id']
            if source_id == '':
                continue
            pred = line['predicate']
            add_labels(labelfile,source_id,line['source_labels'],wrote_labels)
            add_labels(labelfile,target_id,line['target_labels'],wrote_labels)
            #Remove variant/anatomy edges from GTEX.  These are going away in the new load anyway
            if source_id.startswith('CAID'):
                if target_id.startswith('UBERON'):
                    if pred == 'affects_expression_of':
                        continue
            if source_id.startswith('UBERON'):
                if target_id.startswith('NCBIGene'):
                    if pred == 'expresses':
                        continue
            source_link = (target_id,pred,True)
            target_link = (source_id,pred,False)
            nodes_to_links[source_id].append(source_link)
            nodes_to_links[target_id].append(target_link)
            for tlabel in str2list(line['target_labels']):
                edgecounts[ (source_id, pred, True, tlabel) ] += 1
            for slabel in str2list(line['source_labels']):
                edgecounts[ (target_id, pred, False, slabel) ] += 1
            if nl % 1000000 == 0:
                print(nl)
    print('ate the whole thing')
    with open('links.txt','w') as outf:
        for node,links in nodes_to_links.items():
            outf.write(f'{node}\t{json.dumps(links)}\n')
    with open('backlinks.txt','w') as outf:
        for key,value in edgecounts.items():
            outf.write(f'{key}\t{value}\n')

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
    with jsonlines.open('nodes.jsonl','r') as nodefile, open('nodelabels.txt','w') as labelfile:
        for node in nodefile:
            labelfile.write(f'{node["id"]}\t{node["categories"]}\n')
    nodes_to_links = defaultdict(list)
    edgecounts = defaultdict(int)
    with jsonlines.open('edges.jsonl','r') as inf:
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
            source_link = (target_id,pred,True)
            target_link = (source_id,pred,False)
            nodes_to_links[source_id].append(source_link)
            nodes_to_links[target_id].append(target_link)
            for tlabel in str2list(line['target_labels']):
                edgecounts[ (source_id, pred, True, tlabel) ] += 1
            for slabel in str2list(line['source_labels']):
                edgecounts[ (target_id, pred, False, slabel) ] += 1
            if nl % 1000000 == 0:
                print(nl)
    print('ate the whole thing')
    with open('links.txt','w') as outf:
        for node,links in nodes_to_links.items():
            outf.write(f'{node}\t{json.dumps(links)}\n')
    with open('backlinks.txt','w') as outf:
        for key,value in edgecounts.items():
            outf.write(f'{key}\t{value}\n')


if __name__ == '__main__':
    go()
