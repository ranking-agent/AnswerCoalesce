# Tests

The default test suite builds a temporary DuckDB graph store from
`GraphParseTestData` through the same KGX builder used for release artifacts.

```bash
uv run --isolated --with-requirements requirements-test.txt \
  pytest -m "not nongithub" tests/
```

Tests marked `nongithub` require a full release database. Set
`AC_DUCKDB_PATH` before running them:

```bash
export AC_DUCKDB_PATH=/path/to/answer-coalesce.duckdb
uv run --isolated --with-requirements requirements-test.txt \
  pytest -m nongithub tests/
```
