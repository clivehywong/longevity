#!/bin/bash
# Monitor XCP-D jobs and auto-download when complete
# Jobs: FC=4073, FC+GSR=4074, EC=4075

LOG="/home/clivewong/proj/longevity/tmp/monitor_download.log"
LOCAL_XCPD="/home/clivewong/proj/longevity/derivatives/preprocessing/xcpd"
REMOTE_BASE="/home/clivewong/proj/long/derivatives/preprocessing/xcpd"
SSH="ssh -p 2222 localhost"
RSYNC_SSH="ssh -p 2222"

mkdir -p "$(dirname $LOG)"
mkdir -p "$LOCAL_XCPD"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

job_running() {
    local jid=$1
    $SSH "squeue -j $jid --noheader" 2>/dev/null | grep -q "$jid"
}

job_completed_ok() {
    # Check if job completed successfully (exit code 0 in job accounting)
    local jid=$1
    local result
    result=$($SSH "sacct -j $jid --format=State --noheader --parsable2 2>/dev/null | head -1" 2>/dev/null)
    [[ "$result" == "COMPLETED" ]]
}

rsync_pipeline() {
    local pipeline=$1  # fc, fc_gsr, ec
    local remote_dir="$REMOTE_BASE/$pipeline"
    local local_dir="$LOCAL_XCPD/$pipeline"
    mkdir -p "$local_dir"
    log "Starting rsync for $pipeline: $remote_dir → $local_dir"
    rsync -avz --no-perms \
        -e "$RSYNC_SSH" \
        "clivewong@localhost:${remote_dir}/" \
        "${local_dir}/" \
        2>&1 | tee -a "$LOG"
    local rc=${PIPESTATUS[0]}
    if [[ $rc -eq 0 || $rc -eq 24 ]]; then
        log "✅ rsync $pipeline completed (rc=$rc)"
        return 0
    else
        log "❌ rsync $pipeline FAILED (rc=$rc)"
        return 1
    fi
}

count_relmat() {
    local pipeline=$1
    local local_dir="$LOCAL_XCPD/$pipeline"
    find "$local_dir" -name '*relmat*' 2>/dev/null | wc -l
}

update_pipeline_state() {
    local key=$1
    local status=$2
    python3 -c "
import json, datetime, sys
state_file = '/home/clivewong/proj/longevity/.neuconn/xcpd_pipeline_state.json'
with open(state_file) as f:
    d = json.load(f)
key = '$key'
status = '$status'
if key in d.get('runs', {}):
    d['runs'][key]['status'] = status
    d['runs'][key]['completed_at'] = datetime.datetime.now().isoformat()
    d['log'].append({'level': 'info', 'message': f'Job {key} marked {status}', 'timestamp': datetime.datetime.now().isoformat()})
with open(state_file, 'w') as f:
    json.dump(d, f, indent=2)
print(f'Updated {key} → {status}')
" 2>&1 | tee -a "$LOG"
}

log "=== Monitor started ==="
log "Watching jobs: FC=4073, FC+GSR=4074, EC=4075"

FC_DONE=false
FCGSR_DONE=false
EC_DONE=false

# Check if jobs already completed before monitor started
if ! job_running 4073 && job_completed_ok 4073; then
    log "FC job 4073 already completed"
    FC_DONE=true
fi
if ! job_running 4074 && job_completed_ok 4074; then
    log "FC+GSR job 4074 already completed"
    FCGSR_DONE=true
fi
if ! job_running 4075 && job_completed_ok 4075; then
    log "EC job 4075 already completed"
    EC_DONE=true
fi

while true; do
    sleep 300  # Poll every 5 minutes

    # --- Check FC ---
    if ! $FC_DONE; then
        if ! job_running 4073; then
            log "FC job 4073 no longer in queue"
            if job_completed_ok 4073; then
                log "FC job COMPLETED successfully"
                relmat_before=$(count_relmat fc)
                log "FC relmat count before rsync: $relmat_before"
                if rsync_pipeline fc; then
                    relmat_after=$(count_relmat fc)
                    log "FC relmat count after rsync: $relmat_after"
                    update_pipeline_state xcpd_fc completed
                    FC_DONE=true
                    log "🎉 FC pipeline download complete!"
                else
                    log "⚠️  rsync FC failed, will retry next cycle"
                fi
            else
                log "⚠️  FC job 4073 not COMPLETED (may have failed)"
                state=$($SSH "sacct -j 4073 --format=State --noheader --parsable2 2>/dev/null | head -1" 2>/dev/null)
                log "    State: $state"
                FC_DONE=true  # Don't keep retrying failed job
            fi
        else
            running_time=$($SSH "squeue -j 4073 --format='%M' --noheader" 2>/dev/null)
            relmat_count=$(ssh -p 2222 localhost "find /home/clivewong/proj/long/derivatives/preprocessing/xcpd/fc/ -name '*relmat*' 2>/dev/null | grep -o 'sub-[0-9]*' | sort -u | wc -l" 2>/dev/null)
            log "FC still running ($running_time), relmat subjects: $relmat_count/33"
        fi
    fi

    # --- Check FC+GSR ---
    if $FC_DONE && ! $FCGSR_DONE; then
        if ! job_running 4074; then
            log "FC+GSR job 4074 no longer in queue"
            if job_completed_ok 4074; then
                log "FC+GSR job COMPLETED successfully"
                if rsync_pipeline fc_gsr; then
                    update_pipeline_state xcpd_fc_gsr completed
                    FCGSR_DONE=true
                    log "🎉 FC+GSR pipeline download complete!"
                fi
            else
                log "⚠️  FC+GSR job 4074 not COMPLETED"
                state=$($SSH "sacct -j 4074 --format=State --noheader --parsable2 2>/dev/null | head -1" 2>/dev/null)
                log "    State: $state"
                FCGSR_DONE=true
            fi
        fi
    fi

    # --- Check EC ---
    if $FCGSR_DONE && ! $EC_DONE; then
        if ! job_running 4075; then
            log "EC job 4075 no longer in queue"
            if job_completed_ok 4075; then
                log "EC job COMPLETED successfully"
                if rsync_pipeline ec; then
                    update_pipeline_state xcpd_ec completed
                    EC_DONE=true
                    log "🎉 EC pipeline download complete!"
                fi
            else
                log "⚠️  EC job 4075 not COMPLETED"
                state=$($SSH "sacct -j 4075 --format=State --noheader --parsable2 2>/dev/null | head -1" 2>/dev/null)
                log "    State: $state"
                EC_DONE=true
            fi
        fi
    fi

    # --- All done: cleanup ---
    if $FC_DONE && $FCGSR_DONE && $EC_DONE; then
        log "=== All jobs done, cleaning up HPC work dirs ==="
        $SSH "rm -rf /home/clivewong/proj/long/work/xcpd/ 2>/dev/null && echo 'work dir cleaned' || echo 'work dir already gone'" | tee -a "$LOG"
        $SSH "quota -s 2>/dev/null | tail -2" | tee -a "$LOG"
        log "=== Monitor complete, exiting ==="
        break
    fi
done
