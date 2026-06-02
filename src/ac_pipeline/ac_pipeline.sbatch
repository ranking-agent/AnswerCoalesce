#!/bin/bash
# All #SBATCH directives below are FALLBACKS for direct `sbatch ac_pipeline.sbatch`
# invocations. When launched via trigger.sh (the normal path), partition/time/mem/
# cpus/output/error are overridden by CLI flags using config.env values.
#SBATCH --job-name=ac_pipeline
#SBATCH --partition=batch
#SBATCH --time=90-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=240G
#SBATCH --output=ac_pipeline_%j.log
#SBATCH --error=ac_pipeline_%j.err

set -euo pipefail

# ── Load config
source "/projects/translator/AnswerCoalesce/src/ac_pipeline/config.env"

RDB_DEST="$OUTDIR/answer-coalesce.rdb"
REDIS_PORT="${REDIS_PORT:-6400}"
REDIS_LOG="$OUTDIR/redis_${SLURM_JOB_ID:-$$}.log"
REDIS_PIDFILE="$OUTDIR/redis.pid"
REQUIREMENTS="$AC_REPO/src/ac_pipeline/requirements.txt"

mkdir -p "$OUTDIR"

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

log "=== STEP 1: Starting local Redis on port $REDIS_PORT ==="
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

log "=== STEP 1.5: Rebuild property DB if newer CHEBI release exists ==="
PROP_DIR="$AC_REPO/src/property_coalescence"
PROP_MARKER="$PROP_DIR/.last_chebi_release"

LATEST_RELEASE=$(ls -d "$CHEBI_PROPS_BASE"/*/ 2>/dev/null \
    | xargs -I{} basename {} \
    | sort -t_ -k3,3n -k1,1n -k2,2n \
    | tail -1)

if [[ -n "$LATEST_RELEASE" ]]; then
    PREV_RELEASE=""
    [[ -f "$PROP_MARKER" ]] && PREV_RELEASE=$(cat "$PROP_MARKER")

    if [[ "$LATEST_RELEASE" != "$PREV_RELEASE" ]]; then
        CHEBI_FILE=$(find "$CHEBI_PROPS_BASE/$LATEST_RELEASE" -name "normalized_nodes.jsonl" -print -quit 2>/dev/null)
        if [[ -n "$CHEBI_FILE" ]]; then
            log "New CHEBI release: $LATEST_RELEASE (prev: ${PREV_RELEASE:-none})"
            cp "$CHEBI_FILE" "$PROP_DIR/biolink.ChemicalEntity_properties.jsonl"
            (cd "$PROP_DIR" && python generate_property_counts.py -t biolink:ChemicalEntity)
            echo "$LATEST_RELEASE" > "$PROP_MARKER"
            log "Property DB rebuilt."
        else
            log "WARNING: No normalized_nodes.jsonl found in $CHEBI_PROPS_BASE/$LATEST_RELEASE"
        fi
    else
        log "CHEBI release unchanged ($LATEST_RELEASE), skipping property DB rebuild."
    fi
else
    log "WARNING: No releases found in $CHEBI_PROPS_BASE"
fi

log "=== STEP 2: Processing JSONL and loading directly into Redis ==="
export PYTHONPATH="$AC_REPO:${PYTHONPATH:-}"
python "$AC_REPO/src/ac_pipeline/generate_ac_files.py" \
    --nodes "$NODES" \
    --edges "$EDGES" \
    --redis \
    --redis-host localhost \
    --redis-port "$REDIS_PORT"
log "Load complete."

log "=== STEP 3: Triggering BGSAVE ==="
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

log "=== STEP 4: Shutting down Redis ==="
redis-cli -p "$REDIS_PORT" shutdown nosave || true
log "RDB saved to: $RDB_DEST"

log ""
log "============================"
log " Pipeline complete!"
log " RDB saved to: $RDB_DEST"
log "============================"
