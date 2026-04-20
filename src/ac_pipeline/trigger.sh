#!/bin/bash
# Usage: ./trigger.sh [date]
#
# Edits OUTDIR in config.env (if a date is passed), submits the sbatch,
# then streams the pipeline log so you can watch progress live.
# Ctrl+C stops the tail, not the SLURM job.

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

mkdir -p "$OUTDIR"

JOB_ID=$(sbatch \
    --partition="$SLURM_PARTITION" \
    --time="$SLURM_TIME" \
    --nodes="$SLURM_NODES" \
    --ntasks="$SLURM_NTASKS" \
    --cpus-per-task="$SLURM_CPUS" \
    --mem="$SLURM_MEMORY" \
    --output="$OUTDIR/ac_pipeline_%j.log" \
    --error="$OUTDIR/ac_pipeline_%j.err" \
    "$SCRIPT_DIR/ac_pipeline.sbatch" | awk '{print $NF}')

LOG="$OUTDIR/ac_pipeline_${JOB_ID}.log"
ERR="$OUTDIR/ac_pipeline_${JOB_ID}.err"

echo ""
echo "Job submitted: $JOB_ID"
echo "Output dir:    $OUTDIR"
echo ""
echo "Waiting for job to start (queue state below). Ctrl+C to stop watching — job will keep running."
echo "----------------------------------------------------------------------"

# Show queue state while PENDING; break once it starts or the log appears
while true; do
    STATE=$(squeue -j "$JOB_ID" -h -o '%T' 2>/dev/null || true)
    if [[ -z "$STATE" ]]; then
        break  # job already finished (fast failure or very fast run)
    fi
    if [[ "$STATE" != "PENDING" ]] || [[ -f "$LOG" ]]; then
        break
    fi
    REASON=$(squeue -j "$JOB_ID" -h -o '%R' 2>/dev/null || true)
    echo "[$(date '+%H:%M:%S')] PENDING — $REASON"
    sleep 30
done

echo "----------------------------------------------------------------------"
echo "Streaming $LOG (and any stderr from $ERR)"
echo "----------------------------------------------------------------------"

# tail -F follows even if the file doesn't exist yet; shows both streams
tail -F "$LOG" "$ERR" 2>/dev/null
