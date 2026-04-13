#!/bin/bash

# Check subjects with pre (ses-01) and post (ses-02) functional data
# Usage: ./check_pre_post.sh /path/to/bids/folder

BIDS_DIR="${1:-/Volumes/Work/Work/long/bids}"
OUTPUT_FILE="pre_post_check_$(date +%Y%m%d_%H%M%S).csv"

echo "Checking pre/post functional data in: $BIDS_DIR"
echo "Pre = ses-01, Post = ses-02"
echo "Output file: $OUTPUT_FILE"
echo ""

# Create CSV header
echo "Subject,Has_Pre,Has_Post,Pre_Files,Post_Files,Status" > "$OUTPUT_FILE"

# Initialize counters
total_subjects=0
both_timepoints=0
only_pre=0
only_post=0
no_func=0

# Find all subject directories
for sub_dir in "$BIDS_DIR"/sub-*; do
    if [ ! -d "$sub_dir" ]; then
        continue
    fi
    
    ((total_subjects++))
    subject=$(basename "$sub_dir")
    
    # Check for pre and post sessions
    has_pre=0
    has_post=0
    pre_count=0
    post_count=0
    
    # Check ses-01 (pre)
    if [ -d "$sub_dir/ses-01/func" ]; then
        pre_count=$(find "$sub_dir/ses-01/func" -name "*.nii*" 2>/dev/null | wc -l)
        if [ $pre_count -gt 0 ]; then
            has_pre=1
        fi
    fi
    
    # Check ses-02 (post)
    if [ -d "$sub_dir/ses-02/func" ]; then
        post_count=$(find "$sub_dir/ses-02/func" -name "*.nii*" 2>/dev/null | wc -l)
        if [ $post_count -gt 0 ]; then
            has_post=1
        fi
    fi
    
    # Determine status
    if [ $has_pre -eq 1 ] && [ $has_post -eq 1 ]; then
        status="COMPLETE"
        ((both_timepoints++))
    elif [ $has_pre -eq 1 ]; then
        status="PRE_ONLY"
        ((only_pre++))
    elif [ $has_post -eq 1 ]; then
        status="POST_ONLY"
        ((only_post++))
    else
        status="NO_FUNC"
        ((no_func++))
    fi
    
    # Write to CSV
    echo "$subject,$has_pre,$has_post,$pre_count,$post_count,$status" >> "$OUTPUT_FILE"
    
    # Print to console
    printf "%-15s Pre: %-3s Post: %-3s (Pre files: %-3d, Post files: %-3d) [%s]\n" \
           "$subject" "$has_pre" "$has_post" "$pre_count" "$post_count" "$status"
done

# Summary
echo ""
echo "=========================================="
echo "Summary:"
echo "Total subjects: $total_subjects"
echo "Both timepoints: $both_timepoints"
echo "Pre only: $only_pre"
echo "Post only: $only_post"
echo "No func data: $no_func"
echo "=========================================="
echo ""
echo "Results saved to: $OUTPUT_FILE"

# Also append summary to CSV
echo "" >> "$OUTPUT_FILE"
echo "SUMMARY" >> "$OUTPUT_FILE"
echo "Total subjects,$total_subjects" >> "$OUTPUT_FILE"
echo "Both timepoints,$both_timepoints" >> "$OUTPUT_FILE"
echo "Pre only,$only_pre" >> "$OUTPUT_FILE"
echo "Post only,$only_post" >> "$OUTPUT_FILE"
echo "No func data,$no_func" >> "$OUTPUT_FILE"
