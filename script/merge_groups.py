#!/usr/bin/env python3

import pandas as pd
import sys

def merge_group_and_completion(group_file, prepost_file, output_file='completed_subjects_with_groups.csv'):
    """
    Merge group information with pre/post completion status
    """
    
    # Read the files
    print(f"Reading {group_file}...")
    groups_df = pd.read_csv(group_file)
    
    print(f"Reading {prepost_file}...")
    prepost_df = pd.read_csv(prepost_file)
    
    # Filter only completed subjects (those with both pre and post)
    completed_df = prepost_df[prepost_df['Status'] == 'COMPLETE'].copy()
    
    # Rename Subject column to subject_id for merging
    if 'Subject' in completed_df.columns:
        completed_df.rename(columns={'Subject': 'subject_id'}, inplace=True)
    
    # Merge with group information
    result_df = completed_df.merge(groups_df, on='subject_id', how='left')
    
    # Reorder columns
    cols = ['subject_id', 'group', 'Has_Pre', 'Has_Post', 'Pre_Files', 'Post_Files', 'Status']
    
    # Only keep columns that exist
    cols = [col for col in cols if col in result_df.columns]
    result_df = result_df[cols]
    
    # Sort by group and subject_id
    result_df = result_df.sort_values(['group', 'subject_id']).reset_index(drop=True)
    
    # Save to CSV
    result_df.to_csv(output_file, index=False)
    
    # Print summary
    print("\n" + "="*60)
    print("Summary of Completed Subjects:")
    print("="*60)
    print(f"Total completed subjects: {len(result_df)}")
    print(f"\nBy group:")
    print(result_df['group'].value_counts().to_string())
    print("="*60)
    
    print(f"\nResults saved to: {output_file}")
    print("\nCompleted subjects:")
    print(result_df.to_string(index=False))
    
    return result_df

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python merge_groups.py <group_csv> <prepost_csv> [output_csv]")
        print("\nExample:")
        print("  python merge_groups.py subject_groups.csv pre_post_check_20260106.csv")
        sys.exit(1)
    
    group_file = sys.argv[1]
    prepost_file = sys.argv[2]
    output_file = sys.argv[3] if len(sys.argv) > 3 else 'completed_subjects_with_groups.csv'
    
    merge_group_and_completion(group_file, prepost_file, output_file)
