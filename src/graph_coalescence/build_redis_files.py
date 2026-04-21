import csv
from collections import defaultdict
import os
import json
import orjson
import gzip
import requests
import bmt

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# A link is: link = (other_node, predicate, source)
# source is a boolean that is true if node is the source, and false if other_node is the source
FILTER_PREDICATES = ["biolink:related_to_at_concept_level", "biolink:related_to_at_instance_level"]
BLOCKLIST_URL = "https://raw.githubusercontent.com/NCATSTranslator/Relay/master/config/blocklist.json"


def parse_line(line):
    source_id = line['subject']
    target_id = line['object']
    pred = line['predicate']
    # Remove variant/anatomy edges from GTEX.  These are going away in the new load anyway
    if source_id.startswith('CAID'):
        if target_id.startswith('UBERON'):
            if pred == 'biolink:affects_expression_of':
                return source_id, target_id, None, None
    if source_id.startswith('UBERON'):
        if target_id.startswith('NCBIGene'):
            if pred == 'biolink:expresses':
                return source_id, target_id, None, None
    if pred == 'biolink:expressed_in' and target_id.startswith('UBERON'):
        return source_id, target_id, None, None
    predicate_parts = {'predicate': line['predicate']}
    for key, value in line.items():
        if 'qualifier' in key:
            predicate_parts[key] = value
    predicate_string = json.dumps(predicate_parts, sort_keys=True)
    return source_id, target_id, predicate_string, pred


def extract_prov(line):
    # old format: ROBOKOP
    pks = line.get('primary_knowledge_source')
    if pks:
        print ("old")
        prov = {'primary_knowledge_source': pks}
        aks = line.get('aggregator_knowledge_source')
        if aks:
            prov['aggregator_knowledge_source'] = aks
        return prov

    print("new")
    # new format: Translator
    sources = line.get('sources')
    if not sources:
        return {}

    prov = {}
    for source in sources:
        role = source.get('resource_role')
        rid = source.get('resource_id')
        if not role or not rid:
            continue
        if role == 'primary_knowledge_source':
            prov['primary_knowledge_source'] = rid
        elif role == 'aggregator_knowledge_source':
            prov.setdefault('aggregator_knowledge_source', []).append(rid)
    return prov


def get_filter_nodes():
    """Pull the ARS blocklist of nodes that we don't want to return. This consists of a lot of UMLS terms
    that we don't have anyway, but also a bunch of very generic terms (Disease, Human) that are not useful
    and make lots of links in our database."""

    blocklist = json.loads(requests.get(BLOCKLIST_URL).text)
    return set(blocklist)


def quick_jsonl_file_iterator(json_file, is_gzip=False):
    with gzip.open(json_file, 'rt') if is_gzip \
            else open(json_file, 'r', encoding='utf-8') as fp:
        for line in fp:
            yield orjson.loads(line)


def generate_ac_files(input_node_file, input_edge_file, output_dir):
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
    output_nodelabels_filepath = os.path.join(output_dir, 'nodelabels.txt')
    output_nodenames_filepath = os.path.join(output_dir, 'nodenames.txt')
    output_category_count_filepath = os.path.join(output_dir, 'category_count.txt')
    output_prov_filepath = os.path.join(output_dir, 'prov.txt')
    output_links_filepath = os.path.join(output_dir, 'links.txt')
    output_backlinks_filepath = os.path.join(output_dir, 'backlinks.txt')

    tk = bmt.Toolkit()

    filter_nodes = get_filter_nodes()
    categories = {}
    catcount = defaultdict(int)
    with open(output_nodelabels_filepath, 'w') as labelfile, open(output_nodenames_filepath, 'w') as namefile:
        for node in tqdm(quick_jsonl_file_iterator(input_node_file)) if TQDM_AVAILABLE else quick_jsonl_file_iterator(input_node_file):
            node_id = node["id"]
            if node_id.startswith('CAID') or node_id in filter_nodes:
                continue
            node_category = node["category"]
            labelfile.write(f'{node_id}\t{node_category}\n')
            categories[node_id] = node_category
            for c in node_category:
                catcount[c] += 1
            name = node.get("name", "")
            if name is not None:
                name = name.encode('ascii', errors='ignore').decode(encoding="utf-8")
            namefile.write(f'{node_id}\t{name}\n')
    nodes_to_links = defaultdict(list)
    edgecounts = defaultdict(int)
    with open(output_category_count_filepath, 'w') as catcountout:
        for c, v in catcount.items():
            catcountout.write(f'{c}\t{v}\n')
    with open(output_prov_filepath, 'w') as provout:
        nl = 0
        for line in quick_jsonl_file_iterator(input_edge_file):
            if line["subject"].startswith('CAID') or line["object"].startswith('CAID'):
                continue
            nl += 1
            source_id, target_id, pred, just_predicate = parse_line(line)
            if source_id in filter_nodes or target_id in filter_nodes:
                continue
            if pred is None:
                continue
            if just_predicate in FILTER_PREDICATES:
                continue
            source_link = (target_id, pred, True)
            #Here's how we're handling symmetric predicates.
            # The source link and count is going to be just the same, but we're going to modify the target link
            # to look like it's going from target to source.
            if tk.get_element(just_predicate)["symmetric"]:
                target_is_source = True
            else:
                target_is_source = False
            target_link = (source_id, pred, target_is_source)
            nodes_to_links[source_id].append(source_link)
            nodes_to_links[target_id].append(target_link)
            for tcategory in set(categories[target_id]):
                edgecounts[(source_id, pred, True, tcategory)] += 1
            for scategory in set(categories[source_id]):
                edgecounts[(target_id, pred, target_is_source, scategory)] += 1
            pkey = f'{source_id} {pred} {target_id}'
            prov = extract_prov(line)
            if not prov or not pkey:
                continue
            provout.write(f'{pkey}\t{json.dumps(prov)}\n')
            if nl % 1000000 == 0:
                print(nl)
        print('node labels and names done')

    with open(output_links_filepath, 'w') as outf:
        for node, links in nodes_to_links.items():
            outf.write(f'{node}\t{json.dumps(links)}\n')
        print('links done')

    with open(output_backlinks_filepath, 'w') as outf:
        for key, value in edgecounts.items():
            outf.write(f'{key}\t{value}\n')
        print('backlinks done')


if __name__ == '__main__':
    generate_ac_files()