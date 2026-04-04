#!/bin/bash
# Usage: ./trigger.sh [date]
# Example: ./trigger.sh 2026-04-03

set -euo pipefail

SCRIPT_DIR="$(dirname "$0")"
source "$SCRIPT_DIR/config.env"

# Optional date override
if [[ $# -gt 0 ]]; then
    DATE_OVERRIDE=$1
    sed -i "s|OUTDIR=.*|OUTDIR=/projects/stars/var/answer_coalesce/${DATE_OVERRIDE}|" \
        "$SCRIPT_DIR/config.env"
    echo "OUTDIR updated to: /projects/stars/var/answer_coalesce/${DATE_OVERRIDE}"
    source "$SCRIPT_DIR/config.env"
fi

mkdir -p /projects/stars/var/answer_coalesce/logs

JOB_ID=$(sbatch "$SCRIPT_DIR/ac_pipeline.sbatch" | awk '{print $NF}')

echo ""
echo "Job submitted: $JOB_ID"
echo "Monitor:  squeue -j $JOB_ID"
echo "Tail log: tail -f /projects/stars/var/answer_coalesce/logs/ac_pipeline_${JOB_ID}.log"