# AC Pipeline Automation

Builds the Answer Coalesce Redis dump (`answer-coalesce.rdb`) end-to-end on Hatteras. A local Redis is launched on the compute node, loaded, snapshotted, and torn down inside a single SLURM job.

## First-time setup on Hatteras

Clone the repo into `/projects/translator/` so the sbatch's hardcoded paths resolve:

```bash
cd /projects/translator
git clone https://github.com/ranking-agent/AnswerCoalesce.git
cd AnswerCoalesce/src/ac_pipeline
chmod +x trigger.sh ac_pipeline.sbatch
```

If the repo is already there, just pull the latest:
```bash
cd /projects/translator/AnswerCoalesce 
git pull
cd src/ac_pipeline
```

From then on, everything (config edits, triggering, log tailing) happens from `/projects/translator/AnswerCoalesce/src/ac_pipeline`.

## Prerequisites

### On ht1 / compute nodes
- Conda environment `base` activated at job start
- `redis-server` and `redis-cli` available on `$PATH` inside the conda env
  (install with `conda install -c conda-forge redis-server` if missing)
- Read access to the input graph under `/projects/stars/Data_services/...`
- Write access to `/projects/stars/var/answer_coalesce/`

Python dependencies are listed in `requirements.txt` and are installed by
the sbatch itself (STEP 0) at the start of every run — no manual `pip install`
needed.

## Configuration

Edit `config.env` before running:
```bash
# Input files
NODES=/projects/stars/Data_services/biolink3/graphs/Baseline/<hash>/nodes.jsonl
EDGES=/projects/stars/Data_services/biolink3/graphs/Baseline/<hash>/edges.jsonl
OUTDIR=/projects/stars/var/answer_coalesce/YYYY-MM-DD   # update date, nodes, edges

# Repo paths
AC_REPO=/projects/translator/AnswerCoalesce

# Local Redis
REDIS_PORT=6400

# SLURM
SLURM_PARTITION=batch
SLURM_TIME=90-00:00:00
SLURM_NODES=1
SLURM_NTASKS=1
SLURM_CPUS=8
SLURM_MEMORY=240G

# Python
CONDA_BASE=/home/<username>/miniconda3
CONDA_ENV=base
```

### Partition / memory notes
- The job asks for `--mem=240G` to fit Redis (`maxmemory 220gb`) plus OS/Python headroom.
- On `batch`, only `compute-13-[1-15]` (256 GB) can satisfy the request; `compute-6-*` are 191 GB and will be skipped automatically.
- `largemem` nodes (1.5 TB) are a fine alternative when they come out of drain — switch `SLURM_PARTITION` accordingly.
- Expect queuing under `Reason=Priority` when compute-13 is busy; nothing to do but wait.

## Usage

Edit `config.env` with whatever you need (dates, input paths, memory, etc.), then run a single command:

```bash
cd /projects/translator/AnswerCoalesce/src/ac_pipeline
./trigger.sh                   # uses OUTDIR as set in config.env
# or, to override OUTDIR's date in one go:
./trigger.sh YYYY-MM-DD
```

`trigger.sh` submits the sbatch, reports queue state while the job is `PENDING`, and then streams the pipeline log to your terminal automatically. Ctrl+C stops the tail — the SLURM job keeps running.

If you disconnect and want to reattach to a running job later:
```bash
tail -F $OUTDIR/ac_pipeline_<job_id>.log $OUTDIR/ac_pipeline_<job_id>.err
```

Redis-server's own log is separate and useful when debugging the load step:
```bash
tail -f $OUTDIR/redis_<job_id>.log
```

Completion check:
```bash
sacct -j <job_id> --format=JobID,JobName,State,ExitCode,Elapsed,MaxRSS
```
Expect `State=COMPLETED` + `ExitCode=0:0`, log ending with `Pipeline complete!`, and a non-zero `answer-coalesce.rdb` in `$OUTDIR`.

## Output

Everything for a run is self-contained in the date folder:

```
/projects/stars/var/answer_coalesce/YYYY-MM-DD/
├── txt_files/                       # generate_ac_files.py output
├── answer-coalesce.rdb              # final Redis dump
├── ac_pipeline_<job_id>.log         # sbatch stdout
├── ac_pipeline_<job_id>.err         # sbatch stderr
└── redis_<job_id>.log               # redis-server log
```

## Pipeline Steps

| Step | Description |
|---|---|
| 0 | `pip install -r requirements.txt` (idempotent; fast when already satisfied) |
| 1 | Generate `.txt` files via `generate_ac_files.py` (accepts plain JSONL or `.gz`) |
| 2 | Start local Redis on the compute node |
| 3 | Run `load_redis.py` against the local Redis |
| 4 | Trigger `BGSAVE`, wait for `LASTSAVE` to tick |
| 5 | Shut down Redis — the `.rdb` is already at its final path |

Redis is configured with `maxmemory 220gb`, `stop-writes-on-bgsave-error no`, `proto-max-bulk-len 1000mb`, `timeout 60`, `dbfilename answer-coalesce.rdb`, and `--save ""` (periodic snapshots disabled; we BGSAVE once at the end).

## Verifying an RDB

Quick structural check (no server needed, runs on ht1 in seconds):

```bash
redis-check-rdb $OUTDIR/answer-coalesce.rdb
```

Expect six `Selecting DB ID` lines (IDs 0-5), `Checksum OK`, and `\o/ RDB looks OK! \o/`.

For key count validation, per-DB checks, and the full load-and-inspect workflow on a largemem node, see [verifyingDB.md](verifyingDB.md).

## Contact
Chris Bizon & Evan Morris — cbizon@renci.org