import pytest
from src.graph_coalescence.build_redis_files import go
import os

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