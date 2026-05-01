import pytest
from src.graph_coalescence.build_redis_files import generate_ac_files
import os, json, jsonlines, bmt

def test_redis_build():
    testdir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "RedisParseTestData")
    edgefile = os.path.join(testdir, 'edges.jsonl')
    nodefile = os.path.join(testdir, 'nodes.jsonl')
    outdir = os.path.join(testdir, 'output')
    os.makedirs(outdir, exist_ok=True)
    generate_ac_files(input_node_file=nodefile,
       input_edge_file=edgefile,
       output_dir=outdir)

    linkfile = os.path.join(outdir, 'links.txt')
    with open(linkfile, 'r') as inf:
        linkfile_content = [line for line in inf]
    tk = bmt.Toolkit()
    assertion = []

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
            element = tk.get_element(line['predicate'])
            is_target = element is not None and element["symmetric"] is True
            assert f'{line["object"]}\t{json.dumps([(line["subject"], predicate_string, is_target)])}\n' in linkfile_content
            if f'{line["object"]}\t{json.dumps([(line["subject"], predicate_string, is_target)])}\n' not in assertion:
                assertion.append(f'{line["object"]}\t{json.dumps([(line["subject"], predicate_string, is_target)])}\n')
        assert assertion == linkfile_content