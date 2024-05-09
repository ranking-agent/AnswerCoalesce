import pytest
from src.graph_coalescence.build_redis_files import go
import os, json, jsonlines, bmt

def test_redis_build():
    jsondir = "RedisParseTestData"
    edgefile = os.path.join(os.path.abspath(os.path.dirname(__file__)), jsondir, 'edges.jsonl')
    nodefile = os.path.join(os.path.abspath(os.path.dirname(__file__)), jsondir, 'nodes.jsonl')
    provfile = os.path.join(os.path.abspath(os.path.dirname(__file__)), jsondir, 'prov.txt')
    linkfile = os.path.join(os.path.abspath(os.path.dirname(__file__)), jsondir, 'links.txt')
    backfile = os.path.join(os.path.abspath(os.path.dirname(__file__)), jsondir, 'backlinks.txt')
    namefile = os.path.join(os.path.abspath(os.path.dirname(__file__)), jsondir, 'names.txt')
    labelfile = os.path.join(os.path.abspath(os.path.dirname(__file__)), jsondir, 'nodelabels.txt')
    categoryfile = os.path.join(os.path.abspath(os.path.dirname(__file__)), jsondir, 'category_count.txt')
    go(input_edge_file=edgefile,
       input_node_file=nodefile,
       output_prov=provfile,
       output_links=linkfile,
       output_backlinks=backfile,
       output_nodenames=namefile,
       output_nodelabels=labelfile,
       output_category_count=categoryfile)

    with open(linkfile, 'r') as inf:
        linkfile_content = [line for line in inf]
    tk = bmt.Toolkit()
    assertion = []
    print(linkfile_content)
    with jsonlines.open(edgefile, 'r') as inf:
        for line in inf:
            predicate_parts = {'predicate': line['predicate']}
            for key, value in line.items():
                if 'qualifier' in key:
                    predicate_parts[key] = value
            predicate_string = json.dumps(predicate_parts, sort_keys=True)
            assert f'{line["subject"]}\t{json.dumps([(line["object"], predicate_string, True)])}\n' in linkfile_content
            if f'{line["subject"]}\t{json.dumps([(line["object"], predicate_string, True)])}\n' not in assertion:
                assertion.append(f'{line["subject"]}\t{json.dumps([(line["object"], predicate_string, True)])}\n')
            if tk.get_element(line['predicate'])["symmetric"]:
                is_target = True
            else:
                is_target = False
            assert f'{line["object"]}\t{json.dumps([(line["subject"], predicate_string, is_target)])}\n' in linkfile_content
            if f'{line["object"]}\t{json.dumps([(line["subject"], predicate_string, is_target)])}\n' not in assertion:
                assertion.append(f'{line["object"]}\t{json.dumps([(line["subject"], predicate_string, is_target)])}\n')
        assert assertion == linkfile_content

