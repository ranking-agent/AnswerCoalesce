# AC Pipeline Automation
## Prerequisites

### On ht1
- `helm` installed at `~/.local/bin/helm` (v3.14.0)
- `kubectl` installed at `~/.local/bin/kubectl`
- `kubectl oidc-login` plugin installed
- Sterling kubeconfig at `~/.kube/config`
- conda environment `base` with pipeline dependencies installed
- `~/.local/bin` in PATH

### Current Blocker (Pending RENCI ACIS Ticket)
**ht1 cannot reach Sterling Kubernetes API on TCP:443.**
- Ping to `sterling-cluster.k8s.renci.org` works from ht1
- curl to `https://sterling-cluster.k8s.renci.org:443` times out
- A Hatteras Connectivity Request has been submitted to RENCI ACIS
  requesting port 443 be opened from ht1 to Sterling, and a service
  account token for the `translator-exp` namespace for non-interactive
  kubectl authentication in SLURM batch jobs
- Steps 1 (txt file generation) works and completes successfully
- Steps 2-9 (helm/kubectl) are blocked until ACIS resolves the ticket

## Configuration

Edit `config.env` before running:
```bash
# Input files
NODES=/projects/stars/Data_services/biolink3/graphs/Baseline/61f48d345103d107/nodes.jsonl
EDGES=/projects/stars/Data_services/biolink3/graphs/Baseline/61f48d345103d107/edges.jsonl
OUTDIR=/projects/stars/var/answer_coalesce/YYYY-MM-DD   # <update date, and nodes and edges dirs>

# Repo paths
AC_REPO=/projects/translator/AnswerCoalesce
CHART=/projects/translator/AnswerCoalesce/helm/ac-loader

# Kubernetes
NAMESPACE=translator-exp
RELEASE=ac-loader

# SLURM
SLURM_PARTITION=batch
SLURM_TIME=90-00:00:00
SLURM_NODES=1
SLURM_NTASKS=1
SLURM_CPUS=8
SLURM_MEMORY=128G

# Python
CONDA_BASE=/home/<username>/miniconda3
CONDA_ENV=base
```

## Usage
```bash
cd /projects/translator/AnswerCoalesce/src/ac_pipeline
chmod +x trigger.sh ac_pipeline.sbatch

# Pass the date for this run
./trigger.sh YYYY-MM-DD
```

Monitor the job:
```bash
squeue -j <job_id>
tail -f /projects/stars/var/answer_coalesce/logs/ac_pipeline_<job_id>.log
tail -f /projects/stars/var/answer_coalesce/logs/ac_pipeline_<job_id>.err
```

## Output

| File | Location |
|---|---|
| txt files | `/projects/stars/var/answer_coalesce/YYYY-MM-DD/txt_files/` |
| answer-coalesce.rdb | `/projects/stars/var/answer_coalesce/YYYY-MM-DD/answer-coalesce.rdb` |
| logs | `/projects/stars/var/answer_coalesce/logs/` |

## Pipeline Steps

| Step | Description | Status |
|---|---|---|
| 1 | Decompress input files if `.gz` | Working |
| 2 | Generate `.txt` files via `generate_ac_files.py` | Working |
| 3 | Patch helm `values_override.yaml` and deploy | Blocked (TCP:443) |
| 4 | Wait for loader pod to be running | Blocked (TCP:443) |
| 5 | Wait for file downloads inside pod | Blocked (TCP:443) |
| 6 | Run `load_redis.py` inside pod | Blocked (TCP:443) |
| 7 | Wait for Redis load to complete | Blocked (TCP:443) |
| 8 | Trigger final BGSAVE and wait | Blocked (TCP:443) |
| 9 | Copy `.rdb` back to ht1 | Blocked (TCP:443) |
| 10 | Tear down helm release | Blocked (TCP:443) |

## Known Issues and Fixes Applied

### bmt v1.2.1 Compatibility
`Toolkit.is_symmetric()` in [ORION](https://github.com/RobokopU24/ORION/blob/master/orion/biolink_utils.py) was removed in bmt v1.2.1. Fixed in
`utils/biolink_utils.py` by replacing with `get_element()` and
checking the `symmetric` attribute directly:
```python
@cache
def is_symmetric(self, property_name):
    element = self.toolkit.get_element(property_name)
    if element is None:
        return False
    return bool(getattr(element, 'symmetric', False))
```

### SLURM config.env Path
SLURM copies the sbatch script to its spool directory so
`$(dirname "$0")` does not resolve correctly. Fixed by hardcoding
the absolute path to `config.env` in `ac_pipeline.sbatch`.

### PYTHONPATH in SLURM
`PYTHONPATH` may be unset in the SLURM environment. Fixed by using
`${PYTHONPATH:-}` to default to empty string if unset.

## Contact
Chris Bizon & Evan Morris - cbizon@renci.org

