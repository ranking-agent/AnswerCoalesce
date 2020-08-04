import csv
from collections import defaultdict
import json

#A link is: link = (other_node, predicate, source)
# source is a boolean that is true if node is the source, and false if other_node is the source

def add_labels(lfile,nid,nlabels,done):
    if nid in done:
        return
    x = nlabels[1:-1] #strip [ ]
    parts = x.split(',')
    labs = [ pi[1:-1] for pi in parts] #strip ""
    lfile.write(f'{nid}\t{labs}\n')
    done.add(nid)

def go():
    wrote_labels = set()
    nodes_to_links = defaultdict(list)
    with open('everything.csv','r') as inf, open('nodelabels.txt','w') as labelfile:
        reader = csv.DictReader(inf)
        for line in reader:
            source_id = line['source_id']
            target_id = line['target_id']
            if source_id == '':
                continue
            pred = line['predicate']
            source_link = (target_id,pred,True)
            target_link = (source_id,pred,False)
            nodes_to_links[source_id].append(source_link)
            nodes_to_links[target_id].append(target_link)
            add_labels(labelfile,source_id,line['source_labels'],wrote_labels)
            add_labels(labelfile,target_id,line['target_labels'],wrote_labels)
            if len(nodes_to_links) > 10:
                break
    print('ate the whole thing')
    with open('links.txt','w') as outf:
        for node,links in nodes_to_links.items():
            outf.write(f'{node}\t{json.dumps(links)}\n')

if __name__ == '__main__':
    go()
