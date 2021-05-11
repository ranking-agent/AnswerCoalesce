# Testing Answer Coalescence

### Setup

Answer Coalescence relies on a redis server loaded with a reduced version of the normal enrichment data. As shown in the
travis.yml file, once a local version of redis is running, the command `python src/graph_coalescence/load_redis.py test` 
loads the necessary test information into it.

### Test Files

* [`test_graph_coalescer.py`](test_graph_coalescer.py):

  Test the functions producing graph based answer coalescence.  Requires access to the redis server data described above.

* [`test_property_coalescer.py`](test_property_coalescer.py):

  Test the functions used in property coalescence.  

* [`test_ontology_coalsecer.py`](test_ontology_coalsecer.py):

  Test the functions used in ontology coalescence.  

* [`test_node_coalsecer.py`](test_node_coalsecer.py):

  Test the functions used to find opportunities for coalescence in a set of results.

* [`test_bigs.py`](test_bigs.py):
  
  Test performance of the coalsecer on large inputs to verify that performance is acceptable.

* [`test_endpoints.py`](test_endpoints.py):

  High level tests calling the external endpoints.

* [`test_ubergraph.py`](test_ubergraph.py):
  
  We check our integration with ubergraph, used in calculating coalescence via ontology.

### Workflow

Tests are run automatically via GitHub Actions whenever a pull request review is requested.


