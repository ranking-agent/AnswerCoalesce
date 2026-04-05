#!/bin/bash
#SBATCH --job-name=ac_pipeline
#SBATCH --partition=batch
#SBATCH --time=90-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/projects/stars/var/answer_coalesce/logs/ac_pipeline_%j.log
#SBATCH --error=/projects/stars/var/answer_coalesce/logs/ac_pipeline_%j.err

set -euo pipefail

# ── Load config
source "/projects/translator/AnswerCoalesce/src/ac_pipeline/config.env"

TXT_DIR="$OUTDIR/txt_files"
RDB_DEST="$OUTDIR/answer-coalesce.rdb"
LOG_DIR="/projects/stars/var/answer_coalesce/logs"

mkdir -p "$TXT_DIR" "$LOG_DIR"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "Activating conda: $CONDA_ENV"
source "$CONDA_BASE/etc/profile.d/conda.sh" 2>/dev/null
conda activate "$CONDA_ENV"

log "=== STEP 1: Generating .txt files ==="
export PYTHONPATH="$AC_REPO/src/ac_pipeline:${PYTHONPATH:-}"
python "$AC_REPO/src/ac_pipeline/generate_ac_files.py" \
    --nodes "$NODES" \
    --edges "$EDGES" \
    --outdir "$TXT_DIR"
log "Done. Files written to $TXT_DIR"

log "=== 2: Deploying helm chart ==="

STARS_DATE=$(basename "$OUTDIR")
STARS_BASE_URL="https://stars.renci.org/var/answer_coalesce"

cat > "$CHART/values_override.yaml" << EOF
dataFiles:
  - ${STARS_BASE_URL}/${STARS_DATE}/txt_files/links.txt
  - ${STARS_BASE_URL}/${STARS_DATE}/txt_files/nodelabels.txt
  - ${STARS_BASE_URL}/${STARS_DATE}/txt_files/backlinks.txt
  - ${STARS_BASE_URL}/${STARS_DATE}/txt_files/nodenames.txt
  - ${STARS_BASE_URL}/${STARS_DATE}/txt_files/prov.txt
  - ${STARS_BASE_URL}/${STARS_DATE}/txt_files/category_count.txt
EOF

helm -n "$NAMESPACE" upgrade --install "$RELEASE" "$CHART" \
    -f "$CHART/values.yaml" \
    -f "$CHART/values_override.yaml"
log "Helm deploy triggered."

log "=== 3: Waiting for loader pod ==="
POD_NAME=""
for i in $(seq 1 60); do
    POD_NAME=$(kubectl -n "$NAMESPACE" get pods \
        --selector="app.kubernetes.io/name=${RELEASE}" \
        --field-selector=status.phase=Running \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [[ -n "$POD_NAME" ]]; then
        log "Pod ready: $POD_NAME"
        break
    fi
    log "Waiting for pod... ($i/60)"
    sleep 10
done

if [[ -z "$POD_NAME" ]]; then
    log "ERROR: Pod did not become ready. Check: kubectl -n $NAMESPACE get pods"
    exit 1
fi

log "=== 4: Waiting for file downloads inside pod ==="
kubectl -n "$NAMESPACE" exec "$POD_NAME" -- bash -c "
    until ls /data/links.txt /data/nodelabels.txt \
              /data/backlinks.txt /data/nodenames.txt \
              /data/prov.txt /data/category_count.txt \
              > /dev/null 2>&1; do
        echo 'Waiting for downloads...'
        sleep 15
    done
    echo 'All files present.'
"

log "=== 5: Loading Redis ==="
kubectl -n "$NAMESPACE" exec "$POD_NAME" -- bash -c "
    cd /repo/AnswerCoalesce/src/graph_coalescence
    nohup python load_redis.py > /data/load_redis.log 2>&1 &
    echo 'load_redis.py started (PID: '$!')'
"

log "=== 6: Waiting for Redis load to complete ==="
kubectl -n "$NAMESPACE" exec "$POD_NAME" -- bash -c "
    while ps aux | grep -q '[l]oad_redis.py'; do
        tail -1 /data/load_redis.log 2>/dev/null || true
        sleep 30
    done
    echo 'Load complete.'
"

log "===  7: Triggering final BGSAVE ==="
REDIS_POD=""
ALL_PODS=$(kubectl -n "$NAMESPACE" get pods \
    --no-headers -o custom-columns=":metadata.name" \
    | grep "$RELEASE" || true)

for pod in $ALL_PODS; do
    STATUS=$(kubectl -n "$NAMESPACE" exec "$pod" -- \
        redis-cli ping 2>/dev/null || true)
    if [[ "$STATUS" == "PONG" ]]; then
        REDIS_POD="$pod"
        log "Found Redis pod: $REDIS_POD"
        break
    fi
done

if [[ -z "$REDIS_POD" ]]; then
    log "ERROR: Could not find Redis pod."
    kubectl -n "$NAMESPACE" get pods | grep "$RELEASE"
    exit 1
fi

kubectl -n "$NAMESPACE" exec "$REDIS_POD" -- redis-cli BGSAVE

log "Waiting for BGSAVE to complete..."
kubectl -n "$NAMESPACE" exec "$REDIS_POD" -- bash -c "
    BEFORE=\$(redis-cli LASTSAVE)
    while true; do
        sleep 10
        AFTER=\$(redis-cli LASTSAVE)
        if [[ \"\$AFTER\" != \"\$BEFORE\" ]]; then
            echo 'BGSAVE complete.'
            break
        fi
        echo 'Still saving...'
    done
"

log "===  8: Copying .rdb to ht1 ==="
kubectl -n "$NAMESPACE" cp \
    "$REDIS_POD:/data/answer-coalesce.rdb" \
    "$RDB_DEST"
log "RDB saved to: $RDB_DEST"

log "===  9: Tearing down helm release ==="
helm -n "$NAMESPACE" uninstall "$RELEASE"
log "Helm release $RELEASE uninstalled."

log ""
log "============================"
log " Pipeline complete!"
log " RDB saved to: $RDB_DEST"
log "============================"