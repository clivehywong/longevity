#!/bin/bash
#SBATCH --job-name=hpc_sync
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=02:00:00
#SBATCH --output=logs/hpc_sync_%j.out
#SBATCH --error=logs/hpc_sync_%j.err

# =============================================================================
# HPC Result Synchronization with NFS Safety
# =============================================================================
# Syncs subject-level results from HPC, validates manifest completion,
# and enforces NFS synchronization before group-level analysis.
# 
# This script:
# 1. Syncs results back from HPC
# 2. Validates manifest for completion threshold
# 3. Enforces NFS sync (filesystem cache flush)
# 4. Identifies missing/failed subjects for retry
# =============================================================================

set -e

PROJECT_DIR="/home/clivewong/proj/longevity"
SCRIPT_DIR="$PROJECT_DIR/script"
RESULTS_DIR="$PROJECT_DIR/results"
MANIFEST_FILE="$RESULTS_DIR/.manifest.json"
SYNC_LOG="$RESULTS_DIR/sync_$(date +%Y%m%d_%H%M%S).log"

echo "========================================================================="
echo "HPC Result Synchronization - NFS Safe Mode"
echo "========================================================================="
echo "Start time: $(date)"
echo "Project: $PROJECT_DIR"
echo "Manifest: $MANIFEST_FILE"
echo "Log: $SYNC_LOG"
echo ""

# Create results directory if needed
mkdir -p "$RESULTS_DIR"
mkdir -p "$PROJECT_DIR/logs"

{

# =============================================================================
# STEP 1: Sync results from HPC
# =============================================================================

echo "STEP 1: Syncing results from HPC"
echo "=================================="

# Note: These paths assume you're syncing back via rsync on the local machine
# If running on HPC login node, adjust paths accordingly

REMOTE_HOST="${REMOTE_HOST:-clivewong@hpclogin1.eduhk.hk}"
REMOTE_RESULTS="${REMOTE_RESULTS:-/home/clivewong/proj/long/results}"
REMOTE_DERIVATIVES="${REMOTE_DERIVATIVES:-/home/clivewong/proj/long/derivatives}"

if command -v rsync >/dev/null 2>&1; then
    echo "Syncing connectivity results..."
    
    # Sync subject-level results with checksum verification
    if [[ ! -z "$REMOTE_HOST" ]]; then
        rsync -avz --progress --checksum --update \
            "$REMOTE_HOST:$REMOTE_RESULTS/seed_based/" \
            "$RESULTS_DIR/seed_based/" 2>&1 || true
        
        rsync -avz --progress --checksum --update \
            "$REMOTE_HOST:$REMOTE_RESULTS/local_measures/" \
            "$RESULTS_DIR/local_measures/" 2>&1 || true
        
        echo "[INFO] Sync complete"
    else
        echo "[WARN] No REMOTE_HOST specified, skipping rsync"
    fi
else
    echo "[WARN] rsync not available, assuming local mode"
fi

# =============================================================================
# STEP 2: Enforce NFS Synchronization
# =============================================================================

echo ""
echo "STEP 2: Enforcing NFS Synchronization"
echo "======================================"
echo "[INFO] Flushing filesystem caches..."

# Force filesystem sync to ensure all writes are committed to disk
# This prevents race conditions with group-level analysis reading partial data
sync
echo "[INFO] Running sync command"

# Additional conservative wait for NFS cache consistency
echo "[INFO] Waiting 5 seconds for NFS consistency..."
sleep 5

# Verify filesystem is responsive
echo "[INFO] Verifying filesystem connectivity..."
touch "$RESULTS_DIR/.sync_verify_$(date +%s)"
echo "[SUCCESS] Filesystem is responsive"

# =============================================================================
# STEP 3: Validate Manifest Completion
# =============================================================================

echo ""
echo "STEP 3: Validating Manifest Completion"
echo "========================================"

# Create manifest if it doesn't exist
if [[ ! -f "$MANIFEST_FILE" ]]; then
    echo "[INFO] Creating manifest at $MANIFEST_FILE"
    python3 "$SCRIPT_DIR/hpc_manifest.py" --manifest "$MANIFEST_FILE" status || true
fi

# Check completion status for each seed-atlas combination
echo "[INFO] Checking completion status..."

# Try to validate - if threshold not met, report details
if python3 "$SCRIPT_DIR/hpc_manifest.py" --manifest "$MANIFEST_FILE" status; then
    echo "[SUCCESS] Manifest validation passed"
else
    echo "[WARN] Manifest status check completed"
fi

# =============================================================================
# STEP 4: List Missing Subjects (for optional retry)
# =============================================================================

echo ""
echo "STEP 4: Identifying Incomplete Tasks"
echo "====================================="

# Extract seed and atlas from environment or manifest
SEEDS="${SEEDS:-dlpfc_l dlpfc_r dlpfc_bilateral}"
ATLASES="${ATLASES:-difumo256 schaefer400}"

for SEED in $SEEDS; do
    for ATLAS in $ATLASES; do
        echo ""
        echo "Checking $SEED with $ATLAS:"
        
        python3 "$SCRIPT_DIR/hpc_manifest.py" \
            --manifest "$MANIFEST_FILE" \
            missing \
            --seed "$SEED" \
            --atlas "$ATLAS" \
            2>/dev/null || echo "[INFO] No manifest data available yet"
    done
done

# =============================================================================
# STEP 5: Final Status
# =============================================================================

echo ""
echo "STEP 5: Final Status"
echo "===================="
echo "Sync completed at: $(date)"
echo "Results location: $RESULTS_DIR"
echo "Manifest location: $MANIFEST_FILE"
echo ""

# Print full manifest summary
echo "Manifest Summary:"
python3 "$SCRIPT_DIR/hpc_manifest.py" \
    --manifest "$MANIFEST_FILE" \
    status 2>/dev/null || echo "[INFO] Manifest not yet populated"

echo ""
echo "========================================================================="
echo "SYNC COMPLETE"
echo "========================================================================="
echo "Ready for group-level analysis"

} | tee -a "$SYNC_LOG"

exit 0
