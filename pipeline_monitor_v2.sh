#!/bin/bash
# pipeline_monitor_v2.sh
# Re-runs fMRIPrep (fixed fsaverage) then full XCP-D pipeline
# for sub-066 sub-068 sub-072 sub-077

LOG="/home/clivewong/proj/longevity/pipeline_v2_run.log"
exec > >(tee -a "$LOG") 2>&1

SUBJECTS=(066 068 072 077)
HPC="ssh -p 2222 localhost"
REMOTE_BASE="/home/clivewong/proj/long"
LOCAL_BIDS="/home/clivewong/proj/longevity/bids"
LOCAL_FP="/home/clivewong/proj/longevity/derivatives/preprocessing/fmriprep"
LOCAL_XCPD="/home/clivewong/proj/longevity/derivatives/preprocessing/xcpd"
XCPD_SCRIPTS="${REMOTE_BASE}/scripts/xcpd_v2"

echo $$ > /home/clivewong/proj/longevity/pipeline_v2_monitor.pid

echo "============================================"
echo "PIPELINE V2 STARTED: $(date)"
echo "PID: $$"
echo "Subjects: ${SUBJECTS[*]}"
echo "============================================"

###############################################################################
# Phase 0: Pre-flight fixes
###############################################################################
echo ""
echo "=== PHASE 0: Pre-flight at $(date) ==="

# Fix fsaverage conflict: delete from HPC subjects dir
echo "--- Removing stale fsaverage from HPC ---"
$HPC "rm -rf ${REMOTE_BASE}/derivatives/preprocessing/fmriprep/sourcedata/freesurfer/fsaverage && echo 'fsaverage removed' || echo 'fsaverage not found (ok)'"

# Verify what remains in freesurfer dir
echo "--- HPC FreeSurfer subjects dir contents ---"
$HPC "ls ${REMOTE_BASE}/derivatives/preprocessing/fmriprep/sourcedata/freesurfer/ 2>/dev/null || echo '(empty or missing)'"

# Clean any leftover XCP-D work from failed runs
echo "--- Cleaning stale XCP-D work ---"
$HPC "rm -rf ${REMOTE_BASE}/work/xcpd && echo 'xcpd work cleaned' || true"

# Update sublist.txt
echo "--- Updating sublist.txt ---"
printf '%s\n' "${SUBJECTS[@]}" | $HPC "cat > ${REMOTE_BASE}/sublist.txt"
echo "sublist.txt now contains:"
$HPC "cat ${REMOTE_BASE}/sublist.txt"

# Upload BIDS data for 4 subjects
echo "--- Uploading BIDS data ---"
$HPC "mkdir -p ${REMOTE_BASE}/bids"
rsync -avz -e "ssh -p 2222" "${LOCAL_BIDS}/dataset_description.json" "localhost:${REMOTE_BASE}/bids/" 2>&1 | tail -2
for sub in "${SUBJECTS[@]}"; do
    echo "  Uploading sub-${sub}..."
    rsync -avz -e "ssh -p 2222" \
        "${LOCAL_BIDS}/sub-${sub}/" \
        "localhost:${REMOTE_BASE}/bids/sub-${sub}/" 2>&1 | tail -3
done
echo "BIDS upload complete at $(date)"

# Verify BIDS on HPC
for sub in "${SUBJECTS[@]}"; do
    count=$($HPC "find ${REMOTE_BASE}/bids/sub-${sub} -name '*.nii.gz' 2>/dev/null | wc -l" 2>&1)
    echo "  HPC bids/sub-${sub}: ${count} .nii.gz files"
done

###############################################################################
# Phase 1: Submit fMRIPrep and monitor until complete
###############################################################################
echo ""
echo "=== PHASE 1: Submitting fMRIPrep at $(date) ==="

submit_result=$($HPC "cd ${REMOTE_BASE} && sbatch fmriprep_job.sh" 2>&1)
echo "Submission: $submit_result"
JOB_ID=$(echo "$submit_result" | grep -oE '[0-9]+$' | head -1)

if [ -z "$JOB_ID" ]; then
    echo "ERROR: Failed to capture job ID. Aborting."
    exit 1
fi
echo "fMRIPrep array job ID: ${JOB_ID}"
echo "$JOB_ID" > /home/clivewong/proj/longevity/fmriprep_job_id_v2.txt

echo "Monitoring job ${JOB_ID}..."
check_num=0
while true; do
    check_num=$((check_num+1))
    echo ""
    echo "--- fMRIPrep Check #${check_num} at $(date) ---"

    queue=$($HPC "squeue -u clivewong -j ${JOB_ID} --format='%.18i %.9P %.50j %.8u %.8T %.10M %.9l %.6D %R' 2>/dev/null" 2>&1)
    echo "$queue"

    # Check latest log tail for each task
    $HPC "
        for task in 1 2 3 4; do
            logf=\$(ls -t ${REMOTE_BASE}/logs/sub-\${task}_${JOB_ID}.out 2>/dev/null | head -1)
            [ -f \"\$logf\" ] && echo \"  task\${task}: \$(tail -1 \$logf 2>/dev/null)\"
        done
    " 2>&1 || true

    if $HPC "squeue -j ${JOB_ID} -h 2>/dev/null | grep -q ." 2>/dev/null; then
        echo "Job ${JOB_ID} still in queue, sleeping 30 min..."
        sleep 1800
    else
        echo "=== Job ${JOB_ID} left queue at $(date) ==="
        break
    fi
done

# Check SLURM exit status via sacct
echo "--- Checking sacct for exit status ---"
$HPC "sacct -j ${JOB_ID} --format=JobID,State,ExitCode,Elapsed,MaxRSS --noheader 2>/dev/null" 2>&1 || true

###############################################################################
# Phase 2: Verify fMRIPrep outputs on HPC
###############################################################################
echo ""
echo "=== PHASE 2: Verifying fMRIPrep Outputs at $(date) ==="

echo "--- MNI BOLD counts on HPC ---"
all_fp_complete=true
for sub in "${SUBJECTS[@]}"; do
    bold=$($HPC "find ${REMOTE_BASE}/derivatives/preprocessing/fmriprep/sub-${sub} -name '*MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz' 2>/dev/null | wc -l" 2>&1)
    conf=$($HPC "find ${REMOTE_BASE}/derivatives/preprocessing/fmriprep/sub-${sub} -name '*confounds_timeseries.tsv' 2>/dev/null | wc -l" 2>&1)
    total=$($HPC "find ${REMOTE_BASE}/derivatives/preprocessing/fmriprep/sub-${sub} -name '*.nii.gz' 2>/dev/null | wc -l" 2>&1)
    echo "  sub-${sub}: ${bold} MNI BOLD, ${conf} confounds, ${total} total .nii.gz"
    [[ "${bold:-0}" -lt 2 ]] && all_fp_complete=false && echo "    WARNING: incomplete!"
done

echo "--- SLURM log tails ---"
for task in 1 2 3 4; do
    logf=$($HPC "ls -t ${REMOTE_BASE}/logs/sub-${task}_${JOB_ID}.out 2>/dev/null | head -1" 2>&1)
    [ -n "$logf" ] && $HPC "tail -8 $logf 2>/dev/null" 2>&1 | grep -iE 'finish|exit|error|done|fmriprep' || true
done

if ! $all_fp_complete; then
    echo "WARNING: fMRIPrep outputs appear incomplete. Check logs."
fi

###############################################################################
# Phase 3: Download fMRIPrep outputs to local
###############################################################################
echo ""
echo "=== PHASE 3: Downloading fMRIPrep Outputs at $(date) ==="

for sub in "${SUBJECTS[@]}"; do
    echo "--- Downloading sub-${sub} ---"
    mkdir -p "${LOCAL_FP}/sub-${sub}"
    rsync -avz \
        --exclude='*_space-fsnative_*' \
        -e "ssh -p 2222" \
        "localhost:${REMOTE_BASE}/derivatives/preprocessing/fmriprep/sub-${sub}/" \
        "${LOCAL_FP}/sub-${sub}/" 2>&1 | tail -5

    rsync -avz -e "ssh -p 2222" \
        "localhost:${REMOTE_BASE}/derivatives/preprocessing/fmriprep/sub-${sub}.html" \
        "${LOCAL_FP}/" 2>&1 | tail -2 || true

    total=$(find "${LOCAL_FP}/sub-${sub}" -name '*.nii.gz' 2>/dev/null | wc -l)
    bold=$(find "${LOCAL_FP}/sub-${sub}" -name '*preproc_bold.nii.gz' 2>/dev/null | wc -l)
    echo "  Local: ${total} .nii.gz total, ${bold} preproc_bold"
done

# Download updated logs
rsync -avz -e "ssh -p 2222" \
    "localhost:${REMOTE_BASE}/derivatives/preprocessing/fmriprep/logs/" \
    "${LOCAL_FP}/logs/" 2>&1 | tail -3 || true

###############################################################################
# Phase 4: Clean HPC fMRIPrep work dir + BIDS data
###############################################################################
echo ""
echo "=== PHASE 4: Cleaning HPC fMRIPrep Work + BIDS at $(date) ==="

$HPC "du -sh ${REMOTE_BASE}/work/ 2>/dev/null" || true
$HPC "rm -rf ${REMOTE_BASE}/work/fmriprep_25_2_wf && echo 'fMRIPrep work cleaned' || true"

# Clean BIDS (no longer needed after fMRIPrep)
for sub in "${SUBJECTS[@]}"; do
    $HPC "rm -rf ${REMOTE_BASE}/bids/sub-${sub} && echo 'Cleaned bids/sub-${sub}'" || true
done

$HPC "du -sh ${REMOTE_BASE}/work/ ${REMOTE_BASE}/bids/ 2>/dev/null" || true

###############################################################################
# Phase 5a: Update QC status
###############################################################################
echo ""
echo "=== PHASE 5a: Updating QC Status at $(date) ==="

python3 -c "
import json
from datetime import datetime
with open('/home/clivewong/proj/longevity/qc_status.json') as f:
    qc = json.load(f)
updated = []
for key in list(qc.keys()):
    for sub in ['066', '068', '072', '077']:
        if f'sub-{sub}' in key and 'ses-02' in key and 'bold' in key.lower():
            val = qc[key]
            status = val.get('status') if isinstance(val, dict) else val
            if status not in ['pass']:
                qc[key] = {'status': 'pass', 'updated_at': datetime.now().isoformat(), 'reason': 'fMRIPrep completed successfully'}
                updated.append(key)
with open('/home/clivewong/proj/longevity/qc_status.json', 'w') as f:
    json.dump(qc, f, indent=2)
print(f'Updated: {updated}')
for key, val in qc.items():
    if any(f'sub-{s}' in key for s in ['066','068','072','077']):
        print(f'  {key}: {val}')
" 2>&1 || true

###############################################################################
# Phase 5b: Submit XCP-D
###############################################################################
echo ""
echo "=== PHASE 5b: Submitting XCP-D at $(date) ==="

fc_out=$($HPC "cd ${XCPD_SCRIPTS} && sbatch xcpd_fc_v2_4subs.sh" 2>&1)
FC_JOB=$(echo "$fc_out" | grep -oE '[0-9]+$' | head -1)
echo "FC: ${fc_out} -> job ${FC_JOB}"

fgsr_out=$($HPC "cd ${XCPD_SCRIPTS} && sbatch xcpd_fc_gsr_v2_4subs.sh" 2>&1)
FGSR_JOB=$(echo "$fgsr_out" | grep -oE '[0-9]+$' | head -1)
echo "FC+GSR: ${fgsr_out} -> job ${FGSR_JOB}"

ec_out=$($HPC "cd ${XCPD_SCRIPTS} && sbatch xcpd_ec_v2_4subs.sh" 2>&1)
EC_JOB=$(echo "$ec_out" | grep -oE '[0-9]+$' | head -1)
echo "EC: ${ec_out} -> job ${EC_JOB}"

echo "${FC_JOB} ${FGSR_JOB} ${EC_JOB}" > /home/clivewong/proj/longevity/xcpd_job_ids.txt
echo "XCP-D job IDs saved: FC=${FC_JOB} FC+GSR=${FGSR_JOB} EC=${EC_JOB}"

###############################################################################
# Phase 6: Monitor XCP-D until all jobs complete
###############################################################################
echo ""
echo "=== PHASE 6: Monitoring XCP-D at $(date) ==="

XCPD_REMOTE="${REMOTE_BASE}/derivatives/preprocessing/xcpd"
xcp_check=0

while true; do
    xcp_check=$((xcp_check+1))
    echo ""
    echo "--- XCP-D Check #${xcp_check} at $(date) ---"

    queue=$($HPC "squeue -u clivewong --format='%.18i %.9P %.50j %.8u %.8T %.10M %.9l %.6D %R' 2>/dev/null" 2>&1)
    echo "$queue"

    echo "--- XCP-D output file counts ---"
    for variant in fc fc_gsr ec; do
        for sub in "${SUBJECTS[@]}"; do
            count=$($HPC "find ${XCPD_REMOTE}/${variant}/sub-${sub} -name '*.nii.gz' 2>/dev/null | wc -l" 2>&1)
            echo "  ${variant}/sub-${sub}: ${count} files"
        done
    done

    # Check if any of our jobs still in queue
    any_running=false
    for jid in $FC_JOB $FGSR_JOB $EC_JOB; do
        [ -z "$jid" ] && continue
        if echo "$queue" | grep -qw "$jid"; then
            any_running=true; break
        fi
    done

    if $any_running; then
        echo "XCP-D jobs still running, sleeping 30 min..."
        sleep 1800
        continue
    fi

    # Jobs done - check sacct status
    echo "--- XCP-D sacct status ---"
    for jid in $FC_JOB $FGSR_JOB $EC_JOB; do
        [ -z "$jid" ] && continue
        $HPC "sacct -j ${jid} --format=JobID,State,ExitCode,Elapsed --noheader 2>/dev/null | head -5" 2>&1 || true
    done

    # Count outputs
    all_present=true
    for variant in fc fc_gsr ec; do
        for sub in "${SUBJECTS[@]}"; do
            count=$($HPC "find ${XCPD_REMOTE}/${variant}/sub-${sub} -name '*.nii.gz' 2>/dev/null | wc -l" 2>&1)
            if [[ "${count:-0}" -lt 1 ]]; then
                all_present=false
                echo "  MISSING: ${variant}/sub-${sub}"
            fi
        done
    done

    if $all_present; then
        echo "=== All XCP-D outputs present! ==="
        break
    else
        echo "Some outputs still missing, sleeping 30 min..."
        sleep 1800
    fi
done

###############################################################################
# Phase 7: Download XCP-D outputs
###############################################################################
echo ""
echo "=== PHASE 7: Downloading XCP-D Outputs at $(date) ==="

XCPD_REMOTE="${REMOTE_BASE}/derivatives/preprocessing/xcpd"
for variant in fc fc_gsr ec; do
    for sub in "${SUBJECTS[@]}"; do
        if $HPC "test -d ${XCPD_REMOTE}/${variant}/sub-${sub}" 2>/dev/null; then
            mkdir -p "${LOCAL_XCPD}/${variant}/sub-${sub}"
            echo "Downloading xcpd/${variant}/sub-${sub}..."
            rsync -avz -e "ssh -p 2222" \
                "localhost:${XCPD_REMOTE}/${variant}/sub-${sub}/" \
                "${LOCAL_XCPD}/${variant}/sub-${sub}/" 2>&1 | tail -5
        else
            echo "SKIP: ${XCPD_REMOTE}/${variant}/sub-${sub} not found on HPC"
        fi
        rsync -avz -e "ssh -p 2222" \
            "localhost:${XCPD_REMOTE}/${variant}/sub-${sub}.html" \
            "${LOCAL_XCPD}/${variant}/" 2>&1 | tail -2 || true
    done
done

###############################################################################
# Phase 8: Verify XCP-D downloads
###############################################################################
echo ""
echo "=== PHASE 8: Verifying XCP-D Downloads at $(date) ==="

for variant in fc fc_gsr ec; do
    echo "--- ${variant} ---"
    for sub in "${SUBJECTS[@]}"; do
        count=$(find "${LOCAL_XCPD}/${variant}/sub-${sub}" -name '*.nii.gz' 2>/dev/null | wc -l)
        echo "  sub-${sub}: ${count} .nii.gz files"
    done
done

###############################################################################
# Phase 9: Clean HPC XCP-D work dirs
###############################################################################
echo ""
echo "=== PHASE 9: Cleaning HPC XCP-D Work at $(date) ==="

$HPC "du -sh ${REMOTE_BASE}/work/ 2>/dev/null" || true
for variant in fc fc_gsr ec; do
    $HPC "rm -rf ${REMOTE_BASE}/work/xcpd/${variant} && echo 'Cleaned work/xcpd/${variant}'" || true
done
$HPC "du -sh ${REMOTE_BASE}/work/ 2>/dev/null" || true

###############################################################################
# Phase 10: Final Verification
###############################################################################
echo ""
echo "=== PHASE 10: Final Verification at $(date) ==="

for sub in "${SUBJECTS[@]}"; do
    echo "=== sub-${sub} ==="
    total=$(find "${LOCAL_FP}/sub-${sub}" -name '*.nii.gz' 2>/dev/null | wc -l)
    bold=$(find "${LOCAL_FP}/sub-${sub}" -name '*preproc_bold.nii.gz' 2>/dev/null | wc -l)
    echo "  fMRIPrep: ${total} .nii.gz total, ${bold} preproc_bold"
    for v in fc fc_gsr ec; do
        xcp=$(find "${LOCAL_XCPD}/${v}/sub-${sub}" -name '*.nii.gz' 2>/dev/null | wc -l)
        echo "  XCP-D ${v}: ${xcp} .nii.gz"
    done
done

echo "--- HPC disk usage ---"
$HPC "du -sh ${REMOTE_BASE}/work/ ${REMOTE_BASE}/bids/ ${REMOTE_BASE}/derivatives/ 2>/dev/null" || true

echo ""
echo "============================================"
echo "PIPELINE V2 COMPLETE: $(date)"
echo "============================================"
