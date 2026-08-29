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
    "relation_implication",
    "relation_hierarchy",
    "fact",
    "evidence",
    "feature",
    "feature_hierarchy",
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
- Every concrete relation maps to itself in `relation_implication`.
- Every relation implication references existing concrete and implied relation
  rows.
- Every `relation_hierarchy` row references a strict descendant and ancestor
  relation, and no relation maps to itself.
- `membership` contains the deduplicated concrete and Biolink-implied graph
  patterns produced from `fact`.
- `feature` contains one row per unique neighbor, relation, and direction.
- Every `feature_hierarchy` row links features with the same neighbor and
  direction through a strict relation-hierarchy pair.
- `membership` contains only numeric `(member_node_id, feature_id)` pairs and
  is ordered by `member_node_id`.
- Every evidence record joins to one fact.
- Every raw edge was validated to have exactly one primary knowledge source.
- `feature_stats` contains one exact background count per numeric category and
  feature pair and is ordered by `(category_id, feature_id)`.
- `metadata.schema_version` is `7`.

The application opens this file read-only. A failed or partial build never
replaces the prior release artifact.
