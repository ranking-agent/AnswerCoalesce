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

DATABASE_DEST="$OUTDIR/answer-coalesce.duckdb"
REQUIREMENTS="$AC_REPO/src/ac_pipeline/requirements.txt"

mkdir -p "$OUTDIR"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "Activating conda: $CONDA_ENV"
source "$CONDA_BASE/etc/profile.d/conda.sh" 2>/dev/null
conda activate "$CONDA_ENV"

log "=== STEP 0: Installing Python requirements ==="
uv pip install --python "$CONDA_PREFIX/bin/python" -r "$REQUIREMENTS"

log "=== STEP 1: Building DuckDB graph store ==="
export PYTHONPATH="$AC_REPO:${PYTHONPATH:-}"
python -m src.graph_coalescence.build_duckdb \
    --nodes "$NODES" \
    --edges "$EDGES" \
    --output "$DATABASE_DEST"
log "DuckDB graph store written to $DATABASE_DEST"

log "=== STEP 2: Rebuild property DB if newer CHEBI release exists ==="
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

log ""
log "============================"
log " Pipeline complete!"
log " DuckDB saved to: $DATABASE_DEST"
log "============================"
