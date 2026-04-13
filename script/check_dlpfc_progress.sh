#!/bin/bash
# Check progress of DLPFC seed processing on HPC

echo "=========================================="
echo "DLPFC Job Progress Check"
echo "=========================================="
echo "Time: $(date)"
echo ""

# Check job status
echo "Job status:"
ssh clivewong@hpclogin1.eduhk.hk "squeue -u clivewong"
echo ""

# Check z-map counts
echo "Z-map counts on HPC:"
ssh clivewong@hpclogin1.eduhk.hk "
cd /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based 2>/dev/null
for seed in dlpfc_l dlpfc_r dlpfc_bilateral; do
    if [ -d \$seed ]; then
        count=\$(find \$seed -name '*_zmap.nii.gz' 2>/dev/null | wc -l)
        echo \"  \$seed: \$count/48 z-maps\"
    else
        echo \"  \$seed: 0/48 (directory not yet created)\"
    fi
done
echo \"\"
total=\$(find dlpfc_* -name '*_zmap.nii.gz' 2>/dev/null | wc -l)
echo \"  Total: \$total/144 z-maps\"
pct=\$((total * 100 / 144))
echo \"  Progress: \$pct%\"
"
echo ""

# Check latest log output
echo "Latest log output (last 20 lines):"
ssh clivewong@hpclogin1.eduhk.hk "tail -20 /home/clivewong/proj/long/logs/dlpfc_all24_2961.out"
