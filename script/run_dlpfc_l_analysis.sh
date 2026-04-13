#!/bin/bash
set -e

python3 script/group_level_analysis_fast.py \
    --input-maps derivatives/connectivity-difumo256/subject-level/seed_based/dlpfc_l/*.nii.gz \
    --metadata derivatives/connectivity-difumo256/participants_all24_final.csv \
    --output derivatives/connectivity-difumo256/group-level/seed_based/dlpfc_l \
    --cluster-threshold 0.05 \
    --min-cluster-size 50 \
    --n-jobs 8
