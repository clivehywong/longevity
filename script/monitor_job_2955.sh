#!/bin/bash
# Quick monitoring script for HPC Job 2955 (FrontoParietal Phase 2)

echo "========================================"
echo "HPC Job 2955 - Phase 2 Progress Monitor"
echo "========================================"
echo ""

# Check job status
echo "Job Status:"
echo "----------"
ssh clivewong@hpclogin1.eduhk.hk "squeue -u clivewong -j 2955" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Job not running (may have completed or failed)"
    echo "Check logs: ssh clivewong@hpclogin1.eduhk.hk \"cat /home/clivewong/proj/long/logs/fp_phase2_2955.out\""
fi
echo ""

# Phase 2 Progress (24 FP component seeds)
echo "Phase 2: FrontoParietal Component Seeds"
echo "----------------------------------------"
ssh clivewong@hpclogin1.eduhk.hk "
# Count z-maps for each FP seed
fp_seeds=(FP_001_MFG_Ant_RH FP_003_IFS_Post_RH FP_023_POS_Mid FP_028_Angular_Sup_RH
          FP_056_IFG_LH FP_066_MFG_Mid_RH FP_074_IFS_Post_LH FP_078_FP_Lat_RH
          FP_093_IFS_Ant_LH FP_115_SFG_Med FP_117_IPS_Inf_RH FP_120_dmPFC
          FP_128_PrCS_RH FP_140_IFG_Ant_LH FP_143_IFS_Ant_RH FP_144_Angular_Sup_LH
          FP_145_IPJ_RH FP_182_IPS_LH FP_184_FP_Lat_LH FP_191_MFG_Post_RH
          FP_204_PCS_Mid FP_213_MFG_Ant FP_240_Precuneus_Post FP_247_SFS_RH)

completed_seeds=0
total_zmaps=0

for seed in \${fp_seeds[@]}; do
    seed_lower=\$(echo \$seed | tr '[:upper:]' '[:lower:]')
    count=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/\$seed_lower/ -name '*.nii.gz' 2>/dev/null | wc -l)
    total_zmaps=\$((total_zmaps + count))
    if [ \$count -eq 32 ]; then
        completed_seeds=\$((completed_seeds + 1))
    fi
done

echo \"  Completed seeds: \$completed_seeds / 24\"
echo \"  Total z-maps: \$total_zmaps / 768\"
printf '  Progress: %d%%\n' \$((total_zmaps * 100 / 768))
"
echo ""

# Overall progress (including Phase 1)
echo "Overall Progress (Phase 1 + Phase 2):"
echo "--------------------------------------"
ssh clivewong@hpclogin1.eduhk.hk "
phase1=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/{dlpfc_l,dlpfc_r,dlpfc_bilateral}/ -name '*.nii.gz' 2>/dev/null | wc -l)
phase2=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/fp_*/ -name '*.nii.gz' 2>/dev/null | wc -l)
total=\$((phase1 + phase2))
echo \"  Phase 1 (DLPFC): \$phase1 / 96\"
echo \"  Phase 2 (FP components): \$phase2 / 768\"
echo \"  Total: \$total / 864\"
printf '  Overall progress: %d%%\n' \$((total * 100 / 864))
"
echo ""

# Recent activity
echo "Recent Activity (last 5 z-maps):"
echo "--------------------------------"
ssh clivewong@hpclogin1.eduhk.hk "
recent=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/fp_*/ -name '*.nii.gz' 2>/dev/null | xargs ls -lt 2>/dev/null | head -5)
if [ -n \"\$recent\" ]; then
    echo \"\$recent\" | awk '{printf \"  %s %s %s - %s\n\", \$6, \$7, \$8, \$9}' | sed 's|.*seed_based/||' | sed 's|/| - |'
else
    echo '  No FP component files found yet'
fi
"
echo ""

# Estimate completion
echo "Timeline:"
echo "---------"
ssh clivewong@hpclogin1.eduhk.hk "
runtime=\$(squeue -u clivewong -j 2955 -h -o '%M' 2>/dev/null)
if [ -n \"\$runtime\" ]; then
    echo \"  Current runtime: \$runtime\"
    echo \"  Started: Fri Feb 13 07:36:09 AM HKT\"
    echo \"  Est. completion: 16-20 hours from start\"
    echo \"  Est. finish time: ~23:36-03:36 HKT (Feb 13-14)\"
else
    echo \"  Job not running\"
fi
"
echo ""
echo "========================================"
echo "To monitor in real-time:"
echo "  ssh clivewong@hpclogin1.eduhk.hk 'tail -f /home/clivewong/proj/long/logs/fp_phase2_2955.out'"
echo ""
echo "To run this script again:"
echo "  bash script/monitor_job_2955.sh"
echo "========================================"
