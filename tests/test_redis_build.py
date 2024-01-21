import pytest
from src.graph_coalescence.build_redis_files import go

def test_redis_build():
    go(input_edge_file="RedisParseTestData/edges.jsonl",
       input_node_file="RedisParseTestData/nodes.jsonl",
       output_prov="RedisParseTestData/prov.txt",
       output_links="RedisParseTestData/links.txt",
       output_backlinks="RedisParseTestData/backlinks.txt",
       output_nodenames="RedisParseTestData/names.txt",
       output_nodelabels="RedisParseTestData/node_labels.txt",
       output_category_count="RedisParseTestData/category_count.txt" )