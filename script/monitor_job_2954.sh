#!/bin/bash
# Quick monitoring script for HPC Job 2954 (FrontoParietal Seeds)

echo "========================================"
echo "HPC Job 2954 - Progress Monitor"
echo "========================================"
echo ""

# Check job status
echo "Job Status:"
echo "----------"
ssh clivewong@hpclogin1.eduhk.hk "squeue -u clivewong -j 2954" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Job not running (may have completed or failed)"
    echo "Check logs: ssh clivewong@hpclogin1.eduhk.hk \"cat /home/clivewong/proj/long/logs/fp_seeds_2954.out\""
fi
echo ""

# Phase 1 Progress
echo "Phase 1: DLPFC Seeds (with new threshold)"
echo "-------------------------------------------"
ssh clivewong@hpclogin1.eduhk.hk "
for seed in dlpfc_l dlpfc_r dlpfc_bilateral; do
    count=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/\$seed/ -name '*.nii.gz' 2>/dev/null | wc -l)
    printf '  %-20s: %2d / 32 z-maps\n' \"\$seed\" \$count
done
phase1_total=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/{dlpfc_l,dlpfc_r,dlpfc_bilateral}/ -name '*.nii.gz' 2>/dev/null | wc -l)
echo ''
printf '  Phase 1 Total: %d / 96 z-maps (%d%%)\n' \$phase1_total \$((phase1_total * 100 / 96))
"
echo ""

# Phase 2 Progress
echo "Phase 2: FrontoParietal Component Seeds"
echo "----------------------------------------"
ssh clivewong@hpclogin1.eduhk.hk "
phase2_total=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/fp_*/ -name '*.nii.gz' 2>/dev/null | wc -l)
if [ \$phase2_total -gt 0 ]; then
    printf '  Phase 2 Total: %d / 768 z-maps (%d%%)\n' \$phase2_total \$((phase2_total * 100 / 768))
else
    echo '  Phase 2: Not started yet (waiting for Phase 1)'
fi
"
echo ""

# Overall progress
echo "Overall Progress:"
echo "-----------------"
ssh clivewong@hpclogin1.eduhk.hk "
new_total=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/{dlpfc_l,dlpfc_r,dlpfc_bilateral,fp_*}/ -name '*.nii.gz' 2>/dev/null | wc -l)
printf '  New z-maps: %d / 864 (%d%%)\n' \$new_total \$((new_total * 100 / 864))
all_total=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/ -name '*_zmap.nii.gz' 2>/dev/null | wc -l)
echo \"  All z-maps (including old): \$all_total\"
"
echo ""

# Recent activity
echo "Recent Activity:"
echo "----------------"
ssh clivewong@hpclogin1.eduhk.hk "
recent=\$(find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/{dlpfc_l,dlpfc_r,dlpfc_bilateral,fp_*}/ -name '*.nii.gz' 2>/dev/null | xargs ls -lt 2>/dev/null | head -3)
if [ -n \"\$recent\" ]; then
    echo \"\$recent\" | awk '{printf \"  %s %s %s - %s\n\", \$6, \$7, \$8, \$9}' | sed 's|.*seed_based/||' | sed 's|/| - |'
else
    echo '  No recent files found'
fi
"
echo ""

# Estimate completion
echo "Timeline:"
echo "---------"
ssh clivewong@hpclogin1.eduhk.hk "
runtime=\$(squeue -u clivewong -j 2954 -h -o '%M' 2>/dev/null)
if [ -n \"\$runtime\" ]; then
    echo \"  Current runtime: \$runtime\"
    echo \"  Started: Fri Feb 13 02:41:34 AM HKT 2026\"
    echo \"  Est. Phase 1 done: ~04:41 HKT (2-3 hours from start)\"
    echo \"  Est. Phase 2 done: ~12:41 HKT (8-10 hours after Phase 1)\"
    echo \"  Est. completion: 10-12 hours total\"
else
    echo \"  Job not running\"
fi
"
echo ""
echo "========================================"
echo "To monitor in real-time:"
echo "  ssh clivewong@hpclogin1.eduhk.hk 'tail -f /home/clivewong/proj/long/logs/fp_seeds_2954.out'"
echo ""
echo "To run this script again:"
echo "  bash script/monitor_job_2954.sh"
echo "========================================"
