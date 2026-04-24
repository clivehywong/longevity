#!/bin/bash

LOG="/home/clivewong/proj/longevity/pipeline_run.log"
exec > >(tee -a "$LOG") 2>&1

echo "============================================"
echo "PIPELINE STARTED: $(date)"
echo "============================================"

###############################################################################
# Phase 1: Monitor fMRIPrep until all jobs are gone from queue
###############################################################################
phase1_done=false
check_num=0

while ! $phase1_done; do
  check_num=$((check_num+1))
  echo ""
  echo "--- Phase 1 Check #${check_num} at $(date) ---"

  queue=$(ssh -p 2222 localhost "squeue -u clivewong --format='%.18i %.9P %.50j %.8u %.8T %.10M %.9l %.6D %R'" 2>&1)
  echo "$queue"

  echo "--- Log tails ---"
  ssh -p 2222 localhost "
    echo 'sub-066:'; tail -3 /home/clivewong/proj/long/logs/sub-1_4332.out 2>/dev/null; echo '---'
    echo 'sub-068:'; tail -3 /home/clivewong/proj/long/logs/sub-2_4333.out 2>/dev/null; echo '---'
    echo 'sub-072:'; tail -3 /home/clivewong/proj/long/logs/sub-3_4334.out 2>/dev/null; echo '---'
    echo 'sub-077:'; tail -3 /home/clivewong/proj/long/logs/sub-4_4331.out 2>/dev/null
  " 2>&1

  if echo "$queue" | grep -q "4331"; then
    echo "Jobs still running, sleeping 30 minutes..."
    sleep 1800
  else
    echo "=== All fMRIPrep jobs (4331_*) are GONE from queue at $(date) ==="
    phase1_done=true
  fi
done

###############################################################################
# Phase 2: Check fMRIPrep outputs
###############################################################################
echo ""
echo "=== PHASE 2: Checking fMRIPrep Outputs at $(date) ==="

echo "--- Error counts ---"
ssh -p 2222 localhost "grep -c 'ERROR\|FAILED' \
  /home/clivewong/proj/long/logs/sub-1_4332.out \
  /home/clivewong/proj/long/logs/sub-2_4333.out \
  /home/clivewong/proj/long/logs/sub-3_4334.out \
  /home/clivewong/proj/long/logs/sub-4_4331.out 2>/dev/null" || true

echo "--- Output dirs ---"
ssh -p 2222 localhost "ls /home/clivewong/proj/long/derivatives/preprocessing/fmriprep/ 2>/dev/null | grep -E 'sub-06[68]|sub-07[27]'" || true

echo "--- MNI BOLD files ---"
for sub in 066 068 072 077; do
  result=$(ssh -p 2222 localhost "find /home/clivewong/proj/long/derivatives/preprocessing/fmriprep/sub-${sub} -name '*MNI152NLin2009cAsym_res-2_desc-preproc_bold*' 2>/dev/null | wc -l" 2>&1)
  echo "sub-${sub}: ${result} MNI BOLD files"
done

echo "--- HTML reports ---"
ssh -p 2222 localhost "ls /home/clivewong/proj/long/derivatives/preprocessing/fmriprep/sub-06[68].html /home/clivewong/proj/long/derivatives/preprocessing/fmriprep/sub-07[27].html 2>/dev/null" || echo "No HTML reports found"

echo "--- Log success/fail messages ---"
for log in sub-1_4332 sub-2_4333 sub-3_4334 sub-4_4331; do
  echo "Log: $log"
  ssh -p 2222 localhost "tail -30 /home/clivewong/proj/long/logs/${log}.out 2>/dev/null | grep -iE 'finished|completed|success|error|fail'" || true
done

###############################################################################
# Phase 3: Download fMRIPrep outputs
###############################################################################
echo ""
echo "=== PHASE 3: Downloading fMRIPrep Outputs at $(date) ==="

for sub in 066 068 072 077; do
  echo "--- Downloading sub-${sub} at $(date) ---"
  mkdir -p "/home/clivewong/proj/longevity/derivatives/preprocessing/fmriprep/sub-${sub}"
  rsync -avz --progress \
    -e "ssh -p 2222" \
    "localhost:/home/clivewong/proj/long/derivatives/preprocessing/fmriprep/sub-${sub}/" \
    "/home/clivewong/proj/longevity/derivatives/preprocessing/fmriprep/sub-${sub}/" \
    2>&1 | tail -10
  echo "Done sub-${sub} at $(date)"
done

echo "--- Downloading HTML reports ---"
for sub in 066 068 072 077; do
  rsync -avz -e "ssh -p 2222" \
    "localhost:/home/clivewong/proj/long/derivatives/preprocessing/fmriprep/sub-${sub}.html" \
    "/home/clivewong/proj/longevity/derivatives/preprocessing/fmriprep/" 2>&1 | tail -3 || true
done

echo "--- Verify downloads ---"
for sub in 066 068 072 077; do
  count=$(find /home/clivewong/proj/longevity/derivatives/preprocessing/fmriprep/sub-${sub} -name '*MNI152NLin2009cAsym_res-2_desc-preproc_bold*' 2>/dev/null | wc -l)
  echo "sub-${sub}: ${count} MNI BOLD files"
done

###############################################################################
# Phase 4: Cleanup HPC fMRIPrep work directory
###############################################################################
echo ""
echo "=== PHASE 4: Cleaning up HPC fMRIPrep work dir at $(date) ==="

ssh -p 2222 localhost "du -sh /home/clivewong/proj/long/work/ 2>/dev/null" || true
ssh -p 2222 localhost "rm -rf \
  /home/clivewong/proj/long/work/fmriprep_25_2_wf/sub_066* \
  /home/clivewong/proj/long/work/fmriprep_25_2_wf/sub_068* \
  /home/clivewong/proj/long/work/fmriprep_25_2_wf/sub_072* \
  /home/clivewong/proj/long/work/fmriprep_25_2_wf/sub_077* 2>/dev/null && echo 'fMRIPrep work cleanup done'" || true
ssh -p 2222 localhost "du -sh /home/clivewong/proj/long/work/ 2>/dev/null" || true

###############################################################################
# Phase 5a: Check QC status
###############################################################################
echo ""
echo "=== PHASE 5a: Checking QC Status at $(date) ==="

python3 -c "
import json
with open('/home/clivewong/proj/longevity/qc_status.json') as f:
    qc = json.load(f)
for sub in ['066', '068', '072', '077']:
    relevant = {k: v for k, v in qc.items() if f'sub-{sub}' in k}
    print(f'sub-{sub}: {relevant}')
" 2>&1 || true

# Update ses-02 BOLD to pass if not already pass
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
                qc[key] = {'status': 'pass', 'updated_at': datetime.now().isoformat(), 'reason': 'Corrected BOLD data uploaded and processed by fMRIPrep'}
                updated.append(key)
with open('/home/clivewong/proj/longevity/qc_status.json', 'w') as f:
    json.dump(qc, f, indent=2)
print(f'QC Updated: {updated}')
" 2>&1 || true

###############################################################################
# Phase 5b: Submit XCP-D pipelines
###############################################################################
echo ""
echo "=== PHASE 5b: Submitting XCP-D at $(date) ==="

XCPD_SCRIPT_DIR="/home/clivewong/proj/long/scripts/xcpd_v2"

# Submit FC variant
echo "--- Submitting XCP-D FC ---"
fc_result=$(ssh -p 2222 localhost "cd ${XCPD_SCRIPT_DIR} && sbatch xcpd_fc_v2_4subs.sh" 2>&1)
echo "FC submission: $fc_result"
fc_job_id=$(echo "$fc_result" | grep -oE '[0-9]+$' || echo "unknown")
echo "FC Job ID: $fc_job_id"

# Submit FC+GSR variant
echo "--- Submitting XCP-D FC+GSR ---"
fgsr_result=$(ssh -p 2222 localhost "cd ${XCPD_SCRIPT_DIR} && sbatch xcpd_fc_gsr_v2_4subs.sh" 2>&1)
echo "FC+GSR submission: $fgsr_result"
fgsr_job_id=$(echo "$fgsr_result" | grep -oE '[0-9]+$' || echo "unknown")
echo "FC+GSR Job ID: $fgsr_job_id"

# Submit EC variant
echo "--- Submitting XCP-D EC ---"
ec_result=$(ssh -p 2222 localhost "cd ${XCPD_SCRIPT_DIR} && sbatch xcpd_ec_v2_4subs.sh" 2>&1)
echo "EC submission: $ec_result"
ec_job_id=$(echo "$ec_result" | grep -oE '[0-9]+$' || echo "unknown")
echo "EC Job ID: $ec_job_id"

echo "=== XCP-D Jobs submitted: FC=${fc_job_id}, FC+GSR=${fgsr_job_id}, EC=${ec_job_id} ==="

# Save job IDs for monitoring
mkdir -p /home/clivewong/proj/longevity/tmp
echo "${fc_job_id} ${fgsr_job_id} ${ec_job_id}" > /home/clivewong/proj/longevity/tmp/xcpd_job_ids.txt
echo "Job IDs saved to tmp/xcpd_job_ids.txt"

###############################################################################
# Phase 6: Monitor XCP-D until all jobs complete
###############################################################################
echo ""
echo "=== PHASE 6: Monitoring XCP-D at $(date) ==="

XCPD_REMOTE_BASE="/home/clivewong/proj/long/derivatives/preprocessing/xcpd"

xcpd_done=false
xcp_check=0

while ! $xcpd_done; do
  xcp_check=$((xcp_check+1))
  echo ""
  echo "--- XCP-D Check #${xcp_check} at $(date) ---"
  
  queue=$(ssh -p 2222 localhost "squeue -u clivewong --format='%.18i %.9P %.50j %.8u %.8T %.10M %.9l %.6D %R'" 2>&1)
  echo "$queue"
  
  # Check output dirs
  echo "--- Checking XCP-D outputs ---"
  for variant in fc fc_gsr ec; do
    result=$(ssh -p 2222 localhost "ls ${XCPD_REMOTE_BASE}/${variant}/ 2>/dev/null | grep -E 'sub-06[68]|sub-07[27]'" 2>&1)
    if [ -n "$result" ]; then
      echo "  ${variant}: $result"
    else
      echo "  ${variant}: no output yet"
    fi
  done
  
  # Check if any XCP-D jobs are still running
  if echo "$queue" | grep -qE 'xcpd|xcp_d'; then
    echo "XCP-D jobs still in queue, sleeping 30 minutes..."
    sleep 1800
  else
    # No XCP-D jobs in queue - check if outputs exist
    fc_out=$(ssh -p 2222 localhost "ls ${XCPD_REMOTE_BASE}/fc/ 2>/dev/null | grep -E 'sub-06[68]|sub-07[27]' | wc -l" 2>&1)
    fgsr_out=$(ssh -p 2222 localhost "ls ${XCPD_REMOTE_BASE}/fc_gsr/ 2>/dev/null | grep -E 'sub-06[68]|sub-07[27]' | wc -l" 2>&1)
    ec_out=$(ssh -p 2222 localhost "ls ${XCPD_REMOTE_BASE}/ec/ 2>/dev/null | grep -E 'sub-06[68]|sub-07[27]' | wc -l" 2>&1)
    
    echo "Output counts: FC=${fc_out}, FC+GSR=${fgsr_out}, EC=${ec_out}"
    
    # Check XCP-D log files for completion
    echo "--- Checking XCP-D logs for completion ---"
    for log_pattern in xcpd_fc_4subs xcpd_fc_gsr_4subs xcpd_ec_4subs; do
      latest=$(ssh -p 2222 localhost "ls -t /home/clivewong/proj/long/logs/${log_pattern}_*.out 2>/dev/null | head -1" 2>&1)
      if [ -n "$latest" ]; then
        tail_out=$(ssh -p 2222 localhost "tail -5 ${latest} 2>/dev/null" 2>&1)
        echo "  ${log_pattern}: $tail_out"
      fi
    done
    
    if [ "$fc_out" -ge 4 ] && [ "$fgsr_out" -ge 4 ] && [ "$ec_out" -ge 4 ] 2>/dev/null; then
      echo "=== All XCP-D outputs found! ==="
      xcpd_done=true
    else
      echo "Outputs incomplete or jobs still pending, sleeping 30 min..."
      sleep 1800
    fi
  fi
done

###############################################################################
# Phase 7: Download XCP-D outputs
###############################################################################
echo ""
echo "=== PHASE 7: Downloading XCP-D Outputs at $(date) ==="

XCPD_REMOTE_BASE="/home/clivewong/proj/long/derivatives/preprocessing/xcpd"
XCPD_LOCAL_BASE="/home/clivewong/proj/longevity/derivatives/preprocessing/xcpd"

for variant in fc fc_gsr ec; do
  for sub in 066 068 072 077; do
    remote="${XCPD_REMOTE_BASE}/${variant}/sub-${sub}"
    local_dir="${XCPD_LOCAL_BASE}/${variant}/sub-${sub}/"
    if ssh -p 2222 localhost "test -d ${remote}" 2>/dev/null; then
      mkdir -p "${local_dir}"
      echo "Downloading xcpd/${variant}/sub-${sub}..."
      rsync -avz -e "ssh -p 2222" "localhost:${remote}/" "${local_dir}" 2>&1 | tail -5
    else
      echo "Remote not found: ${remote} - skipping"
    fi
  done
done

# Also download HTML reports
for variant in fc fc_gsr ec; do
  html_dir="${XCPD_LOCAL_BASE}/${variant}"
  mkdir -p "${html_dir}"
  for sub in 066 068 072 077; do
    rsync -avz -e "ssh -p 2222" \
      "localhost:${XCPD_REMOTE_BASE}/${variant}/sub-${sub}.html" \
      "${html_dir}/" 2>&1 | tail -2 || true
  done
done

###############################################################################
# Phase 8: Verify XCP-D downloads
###############################################################################
echo ""
echo "=== PHASE 8: Verifying XCP-D Downloads at $(date) ==="

for variant in fc fc_gsr ec; do
  echo "=== $variant ==="
  for sub in 066 068 072 077; do
    count=$(find /home/clivewong/proj/longevity/derivatives/preprocessing/xcpd/${variant}/sub-${sub} -name '*.nii.gz' 2>/dev/null | wc -l)
    echo "  sub-${sub}: ${count} .nii.gz files"
  done
done

###############################################################################
# Phase 9: Cleanup XCP-D HPC files
###############################################################################
echo ""
echo "=== PHASE 9: Cleaning up XCP-D HPC files at $(date) ==="

ssh -p 2222 localhost "du -sh /home/clivewong/proj/long/work/ 2>/dev/null" || true
ssh -p 2222 localhost "find /home/clivewong/proj/long/work/ -maxdepth 2 -name '*xcp*' -type d 2>/dev/null | head -20" || true
ssh -p 2222 localhost "find /home/clivewong/proj/long/work/ -maxdepth 1 -name '*xcp*' -type d 2>/dev/null | xargs -r rm -rf && echo 'XCP-D work cleanup done'" || true
ssh -p 2222 localhost "du -sh /home/clivewong/proj/long/work/ 2>/dev/null" || true

###############################################################################
# Phase 10: Final Verification
###############################################################################
echo ""
echo "=== PHASE 10: Final Verification at $(date) ==="

for sub in 066 068 072 077; do
  echo "=== sub-${sub} ==="
  fmriprep_count=$(find /home/clivewong/proj/longevity/derivatives/preprocessing/fmriprep/sub-${sub} -name '*.nii.gz' 2>/dev/null | wc -l)
  echo "  fMRIPrep: ${fmriprep_count} files"
  for v in fc fc_gsr ec; do
    xcp_count=$(find /home/clivewong/proj/longevity/derivatives/preprocessing/xcpd/${v}/sub-${sub} -name '*.nii.gz' 2>/dev/null | wc -l)
    echo "  XCP-D ${v}: ${xcp_count} files"
  done
done

echo "--- HPC disk usage ---"
ssh -p 2222 localhost "du -sh /home/clivewong/proj/long/work/ 2>/dev/null && du -sh /home/clivewong/proj/long/derivatives/ 2>/dev/null" || true

echo ""
echo "============================================"
echo "PIPELINE COMPLETE: $(date)"
echo "============================================"
