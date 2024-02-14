# Testing Answer Coalescence

### Setup

Answer Coalescence relies on a redis server loaded with a reduced version of the normal enrichment data. As shown in the
travis.yml file, once a local version of redis is running, the command `python src/graph_coalescence/load_redis.py test` 
loads the necessary test information into it.

### Test Files

* [`test_prototyping.py`](test_prototyping.py):

  Test the functions producing multiquery answer coalescence.  Requires access to the redis server data described above.

* [`test_endpoints.py`](test_endpoints.py):

  High level tests calling the external endpoints.

### Workflow

Tests are run automatically via GitHub Actions whenever a pull request review is requested.


