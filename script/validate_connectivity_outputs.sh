#!/bin/bash
# =============================================================================
# Validate Connectivity Analysis Pipeline Outputs
# =============================================================================
# This script validates that all expected outputs from the connectivity
# analysis pipeline have been generated successfully.
#
# Usage:
#   bash script/validate_connectivity_outputs.sh
# =============================================================================

set -e

PROJECT_DIR="/home/clivewong/proj/longevity"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"

PASSED=0
FAILED=0
WARNINGS=0

echo "================================================================"
echo "Connectivity Analysis Pipeline Output Validation"
echo "================================================================"
echo "Date: $(date)"
echo "Checking: $DERIVATIVE_ROOT"
echo ""

# Function to check file count
check_count() {
    local description=$1
    local pattern=$2
    local expected=$3
    local warn_threshold=$4

    count=$(find $pattern 2>/dev/null | wc -l)

    if [ "$count" -eq "$expected" ]; then
        echo "✅ PASS: $description"
        echo "   Expected: $expected, Found: $count"
        PASSED=$((PASSED + 1))
    elif [ "$count" -ge "$warn_threshold" ]; then
        echo "⚠️  WARN: $description"
        echo "   Expected: $expected, Found: $count (>= $warn_threshold, acceptable)"
        WARNINGS=$((WARNINGS + 1))
    else
        echo "❌ FAIL: $description"
        echo "   Expected: $expected, Found: $count"
        FAILED=$((FAILED + 1))
    fi
}

# Function to check file exists
check_file() {
    local description=$1
    local filepath=$2

    if [ -f "$filepath" ]; then
        size=$(du -h "$filepath" | cut -f1)
        echo "✅ PASS: $description"
        echo "   Found: $filepath ($size)"
        PASSED=$((PASSED + 1))
    else
        echo "❌ FAIL: $description"
        echo "   Missing: $filepath"
        FAILED=$((FAILED + 1))
    fi
}

# Function to check directory exists
check_dir() {
    local description=$1
    local dirpath=$2

    if [ -d "$dirpath" ]; then
        file_count=$(find "$dirpath" -type f | wc -l)
        echo "✅ PASS: $description"
        echo "   Found: $dirpath ($file_count files)"
        PASSED=$((PASSED + 1))
    else
        echo "❌ FAIL: $description"
        echo "   Missing: $dirpath"
        FAILED=$((FAILED + 1))
    fi
}

echo "================================================================"
echo "SUBJECT-LEVEL OUTPUTS"
echo "================================================================"
echo ""

echo "Local Measures:"
check_count "fALFF maps" "$DERIVATIVE_ROOT/subject-level/local_measures/*_fALFF.nii.gz" 48 40
check_count "ReHo maps" "$DERIVATIVE_ROOT/subject-level/local_measures/*_ReHo.nii.gz" 48 40
check_file "Local measures summary CSV" "$DERIVATIVE_ROOT/subject-level/local_measures/local_measures_summary.csv"
echo ""

echo "Seed-Based Connectivity (16 seeds):"
SEEDS=(
    "anterior_insula" "dacc" "insula_dacc_combined"
    "hippocampus" "hippocampus_anterior" "hippocampus_posterior"
    "cerebellar_cognitive_l" "cerebellar_cognitive_r" "cerebellar_cognitive_bilateral"
    "cerebellar_motor" "motor_cortex"
    "default_mode" "frontoparietal_control"
    "dlpfc_coarse" "dlpfc_dorsal" "dlpfc_ventral"
)

for seed in "${SEEDS[@]}"; do
    check_count "  $seed z-maps" "$DERIVATIVE_ROOT/subject-level/seed_based/$seed/*_zmap.nii.gz" 48 40
done
echo ""

echo "Timeseries:"
check_file "DiFuMo 256 timeseries HDF5" "$DERIVATIVE_ROOT/subject-level/timeseries_difumo256.h5"
echo ""

echo "================================================================"
echo "GROUP-LEVEL OUTPUTS"
echo "================================================================"
echo ""

echo "Local Measures Group Analysis:"
for measure in fALFF ReHo; do
    output_dir="$DERIVATIVE_ROOT/group-level/local_measures/$measure"
    echo "  $measure:"
    check_file "    T-statistic map" "$output_dir/interaction_tstat_map.nii.gz"
    check_file "    P-value map" "$output_dir/interaction_pval_map.nii.gz"
    check_file "    Model info JSON" "$output_dir/model_info.json"
done
echo ""

echo "Seed-Based Group Analysis (13 seeds):"
GROUP_SEEDS=(
    "anterior_insula" "dacc" "insula_dacc_combined"
    "hippocampus" "hippocampus_anterior" "hippocampus_posterior"
    "cerebellar_cognitive_l" "cerebellar_cognitive_r" "cerebellar_cognitive_bilateral"
    "cerebellar_motor" "motor_cortex"
    "default_mode" "frontoparietal_control"
)

for seed in "${GROUP_SEEDS[@]}"; do
    output_dir="$DERIVATIVE_ROOT/group-level/seed_based/$seed"
    echo "  $seed:"
    check_file "    T-statistic map" "$output_dir/interaction_tstat_map.nii.gz"
done
echo ""

echo "Network Connectivity Analysis:"

echo "  Within-Network (10 networks):"
NETWORKS=(
    "SalienceVentralAttention" "FrontoParietal" "DefaultMode"
    "DorsalAttention" "Somatomotor" "Visual" "Limbic"
    "Cerebellar_Motor" "Cerebellar_Cognitive" "Subcortical"
)

for net in "${NETWORKS[@]}"; do
    output_dir="$DERIVATIVE_ROOT/group-level/network/within_$net"
    check_file "    $net ANOVA results" "$output_dir/connectivity_anova_results.csv"
done
echo ""

echo "  Between-Network (5 pairs):"
NETWORK_PAIRS=(
    "FrontoParietal_Cerebellar_Cognitive"
    "SalienceVentralAttention_DefaultMode"
    "Somatomotor_Cerebellar_Motor"
    "FrontoParietal_DefaultMode"
    "Limbic_Cerebellar_Cognitive"
)

for pair in "${NETWORK_PAIRS[@]}"; do
    output_dir="$DERIVATIVE_ROOT/group-level/network/between_$pair"
    check_file "    $pair ANOVA results" "$output_dir/connectivity_anova_results.csv"
done
echo ""

echo "================================================================"
echo "FINAL REPORTS"
echo "================================================================"
echo ""

check_file "Comprehensive connectivity report" "$DERIVATIVE_ROOT/group-level/comprehensive_connectivity_report.html"
check_file "DLPFC group analysis report (existing)" "$DERIVATIVE_ROOT/group-level/dlpfc_group_analysis_report.html"
echo ""

echo "================================================================"
echo "VALIDATION SUMMARY"
echo "================================================================"
echo ""
echo "✅ PASSED:   $PASSED checks"
echo "⚠️  WARNINGS: $WARNINGS checks"
echo "❌ FAILED:   $FAILED checks"
echo ""

if [ "$FAILED" -eq 0 ]; then
    echo "🎉 SUCCESS: All critical outputs validated!"
    echo ""
    echo "Pipeline completion status:"
    echo "  - Subject-level analyses: Complete"
    echo "  - Group-level analyses: Complete"
    echo "  - Reports: Ready for review"
    echo ""
    echo "Next steps:"
    echo "  1. Review comprehensive_connectivity_report.html"
    echo "  2. Inspect significant findings"
    echo "  3. Prepare publication figures"
    exit 0
elif [ "$FAILED" -le 5 ] && [ "$WARNINGS" -gt 0 ]; then
    echo "⚠️  PARTIAL SUCCESS: Most outputs present, but some missing"
    echo ""
    echo "Review failed checks above and determine if:"
    echo "  - Jobs are still running (check squeue)"
    echo "  - Jobs failed (check sacct and error logs)"
    echo "  - Some subjects were intentionally excluded"
    exit 0
else
    echo "❌ VALIDATION FAILED: Multiple critical outputs missing"
    echo ""
    echo "Troubleshooting steps:"
    echo "  1. Check HPC job status: squeue -u \$USER"
    echo "  2. Check completed jobs: sacct --format=JobID,JobName,State,ExitCode"
    echo "  3. Review error logs in logs/ directory"
    echo "  4. Re-run failed stages with hpc_full_connectivity_pipeline.sh --stage N"
    exit 1
fi
