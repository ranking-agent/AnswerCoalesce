#!/bin/bash
#SBATCH --job-name=ac_pipeline
#SBATCH --partition=batch
#SBATCH --time=90-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=240G
# NOTE: --output/--error are overridden by trigger.sh to land in $OUTDIR.
# These fallbacks are only used if you run `sbatch ac_pipeline.sbatch` directly.
#SBATCH --output=ac_pipeline_%j.log
#SBATCH --error=ac_pipeline_%j.err

set -euo pipefail

# ── Load config
source "/projects/translator/AnswerCoalesce/src/ac_pipeline/config.env"

TXT_DIR="$OUTDIR/txt_files"
RDB_DEST="$OUTDIR/answer-coalesce.rdb"
REDIS_PORT="${REDIS_PORT:-6400}"
REDIS_LOG="$OUTDIR/redis_${SLURM_JOB_ID:-$$}.log"
REDIS_PIDFILE="$OUTDIR/redis.pid"
REQUIREMENTS="$AC_REPO/src/ac_pipeline/requirements.txt"

mkdir -p "$TXT_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

cleanup() {
    if [[ -f "$REDIS_PIDFILE" ]] && kill -0 "$(cat "$REDIS_PIDFILE")" 2>/dev/null; then
        log "Cleanup: shutting down Redis"
        redis-cli -p "$REDIS_PORT" shutdown nosave 2>/dev/null \
            || kill "$(cat "$REDIS_PIDFILE")" 2>/dev/null \
            || true
    fi
}
trap cleanup EXIT

log "Activating conda: $CONDA_ENV"
source "$CONDA_BASE/etc/profile.d/conda.sh" 2>/dev/null
conda activate "$CONDA_ENV"

log "=== STEP 0: Installing Python requirements ==="
pip install --quiet --disable-pip-version-check -r "$REQUIREMENTS"

log "=== STEP 1: Generating .txt files ==="
export PYTHONPATH="$AC_REPO/src/ac_pipeline:${PYTHONPATH:-}"
python "$AC_REPO/src/ac_pipeline/generate_ac_files.py" \
    --nodes "$NODES" \
    --edges "$EDGES" \
    --outdir "$TXT_DIR"
log "Done. Files written to $TXT_DIR"

log "=== STEP 2: Starting local Redis on port $REDIS_PORT ==="
# Settings mirror helm/ac-loader/values.yaml (redis 6.2.6, 220gb maxmemory).
# --save "" disables periodic RDB snapshots during the load; we BGSAVE once at the end.
redis-server \
    --daemonize yes \
    --port "$REDIS_PORT" \
    --bind 127.0.0.1 \
    --dir "$OUTDIR" \
    --dbfilename answer-coalesce.rdb \
    --pidfile "$REDIS_PIDFILE" \
    --maxmemory 220gb \
    --loglevel notice \
    --logfile "$REDIS_LOG" \
    --stop-writes-on-bgsave-error no \
    --proto-max-bulk-len 1000mb \
    --timeout 60 \
    --save ""

for i in $(seq 1 30); do
    if redis-cli -p "$REDIS_PORT" ping 2>/dev/null | grep -q PONG; then
        log "Redis is up (pid $(cat "$REDIS_PIDFILE"))."
        break
    fi
    sleep 1
    if [[ $i -eq 30 ]]; then
        log "ERROR: Redis failed to start. See $REDIS_LOG"
        exit 1
    fi
done

log "=== STEP 3: Loading data into Redis ==="
REDIS_HOST=localhost REDIS_PORT="$REDIS_PORT" DATA_DIR="$TXT_DIR" \
    python "$AC_REPO/src/graph_coalescence/load_redis.py"
log "Load complete."

log "=== STEP 4: Triggering BGSAVE ==="
BEFORE=$(redis-cli -p "$REDIS_PORT" LASTSAVE)
redis-cli -p "$REDIS_PORT" BGSAVE
while true; do
    sleep 10
    AFTER=$(redis-cli -p "$REDIS_PORT" LASTSAVE)
    if [[ "$AFTER" != "$BEFORE" ]]; then
        log "BGSAVE complete."
        break
    fi
    log "Still saving..."
done

log "=== STEP 5: Shutting down Redis ==="
redis-cli -p "$REDIS_PORT" shutdown nosave || true
log "RDB saved to: $RDB_DEST"

log ""
log "============================"
log " Pipeline complete!"
log " RDB saved to: $RDB_DEST"
log "============================"
