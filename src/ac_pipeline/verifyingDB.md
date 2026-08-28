# Verifying an AnswerCoalesce DuckDB Release

Set the database path:

```bash
export AC_DUCKDB_PATH=/path/to/answer-coalesce.duckdb
```

Run structural and count checks:

```bash
uv run --with duckdb python - <<'PY'
import os
import duckdb

path = os.environ["AC_DUCKDB_PATH"]
con = duckdb.connect(path, read_only=True)
print(con.execute("PRAGMA database_size").fetchall())
print(con.execute("SELECT * FROM metadata ORDER BY key").fetchall())
for table in (
    "node",
    "relation",
    "fact",
    "evidence",
    "feature",
    "membership",
    "category_count",
    "feature_stats",
):
    print(table, con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
con.close()
PY
```

Expected invariants:

- `evidence` equals the accepted raw KGX edge count.
- `fact` is no greater than `evidence`; duplicate semantic edges remain separate
  evidence records.
- `membership` is at most twice `fact`.
- `feature` contains one row per unique neighbor, relation, and direction.
- `membership` contains only numeric `(member_node_id, feature_id)` pairs and
  is ordered by `member_node_id`.
- Every evidence record joins to one fact.
- Every raw edge was validated to have exactly one primary knowledge source.
- `feature_stats` contains one exact background count per numeric category and
  feature pair and is ordered by `(category_id, feature_id)`.
- `metadata.schema_version` is `4`.

The application opens this file read-only. A failed or partial build never
replaces the prior release artifact.
