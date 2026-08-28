# AnswerCoalesce Graph Build Pipeline

This Slurm pipeline builds the immutable DuckDB graph store used by
AnswerCoalesce. It reads KGX node and edge JSONL directly and writes one
`answer-coalesce.duckdb` release artifact.

## Setup

Clone the repository on Hatteras and make the scripts executable:

```bash
cd /projects/translator
git clone https://github.com/ranking-agent/AnswerCoalesce.git
cd AnswerCoalesce/src/ac_pipeline
chmod +x trigger.sh ac_pipeline.sbatch
```

The compute environment needs:

- The configured conda environment and `uv`
- Read access to the KGX node and edge files
- Write access to the configured output directory

Python dependencies are installed from `requirements.txt` at the start of the
job.

## Configuration

Edit `config.env`:

```bash
NODES=/path/to/nodes.jsonl
EDGES=/path/to/edges.jsonl
OUTDIR=/projects/stars/var/answer_coalesce/YYYY-MM-DD
AC_REPO=/projects/translator/AnswerCoalesce

SLURM_PARTITION=batch
SLURM_TIME=90-00:00:00
SLURM_NODES=1
SLURM_NTASKS=1
SLURM_CPUS=8
SLURM_MEMORY=240G

CHEBI_PROPS_BASE=/projects/stars/Data_services/biolink3/storage/CHEBIProps
CONDA_BASE=/home/<username>/miniconda3
CONDA_ENV=base
```

## Run

```bash
cd /projects/translator/AnswerCoalesce/src/ac_pipeline
./trigger.sh
```

The final graph artifact is:

```text
$OUTDIR/answer-coalesce.duckdb
```

The builder writes a temporary `.building` file and atomically replaces the
final database only after validation, index creation, `ANALYZE`, and
`CHECKPOINT` complete.

The build defaults to a 6 GB DuckDB memory limit, 20 GB of temporary spill
space, and four threads. Override these explicitly when the allocated job
supports more:

```bash
export AC_DUCKDB_BUILD_MEMORY_LIMIT=32GB
export AC_DUCKDB_BUILD_MAX_TEMP_DIRECTORY_SIZE=100GB
export AC_DUCKDB_BUILD_THREADS=8
```

The database assigns compact release-local IDs to nodes and graph features.
`membership(member_node_id, feature_id)` is ordered by member, while
`feature_stats(category_id, feature_id, background_count)` is ordered by
category and feature. Statistics are built one category at a time so each
aggregation remains within the configured memory and spill limits.

At query time, DuckDB performs an indexed lookup of the input memberships and
materializes those matched rows once. Support counting, filtering, scoring,
top-K selection, and linked-member construction all reuse that bounded
relation rather than rescanning the complete membership table. Raw evidence
source provenance and CURIE mappings remain in separate tables for TRAPI
support-edge construction. The database does not preserve arbitrary KGX node
and edge properties.

The property coalescence SQLite rebuild remains a separate step in the same
job.

## Runtime

Mount the database read-only and set:

```bash
export AC_DUCKDB_PATH=/data/answer-coalesce.duckdb
export AC_DUCKDB_QUERY_MEMORY_LIMIT=1GB
export AC_DUCKDB_QUERY_MAX_TEMP_DIRECTORY_SIZE=8GB
export AC_DUCKDB_QUERY_THREADS=2
```

See [verifyingDB.md](verifyingDB.md) for release checks.
