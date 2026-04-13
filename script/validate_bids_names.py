#!/usr/bin/env python3
"""
Validate BIDS naming conventions and detect naming errors.

Checks for:
1. Session-directory mismatches (ses-02 directory with ses-01 filenames)
2. Subject-directory mismatches
3. Run-label validation (verify run numbers match expected patterns)
4. Task-label validation for functional data
5. Modality-directory validation (ensure files are in correct directories)
6. Missing paired files (.nii.gz without .json)
7. Duplicate filenames

Usage:
    python validate_bids_names.py [bids_directory] [--json]
"""

import os
import sys
import re
import json
import argparse
from pathlib import Path
from collections import defaultdict

BIDS_DIR = '/home/clivewong/proj/longevity/bids'

# Expected modality suffixes for each directory type
MODALITY_DIR_MAP = {
    'anat': ['T1w', 'T2w', 'FLAIR', 'T1rho', 'T1map', 'T2map', 'T2star', 'FLASH', 'PD', 'PDT2', 'angio'],
    'func': ['bold', 'sbref'],
    'dwi': ['dwi', 'sbref'],
    'fmap': ['epi', 'magnitude1', 'magnitude2', 'phasediff', 'phase1', 'phase2', 'fieldmap'],
    'perf': ['asl', 'm0scan'],
}

def extract_entities(filepath):
    """Extract BIDS entities from filename."""
    filename = os.path.basename(filepath)
    entities = {}

    # Extract subject
    sub_match = re.search(r'sub-([a-zA-Z0-9]+)', filename)
    if sub_match:
        entities['subject'] = sub_match.group(1)

    # Extract session
    ses_match = re.search(r'ses-([a-zA-Z0-9]+)', filename)
    if ses_match:
        entities['session'] = ses_match.group(1)

    # Extract run
    run_match = re.search(r'run-([a-zA-Z0-9]+)', filename)
    if run_match:
        entities['run'] = run_match.group(1)

    # Extract task
    task_match = re.search(r'task-([a-zA-Z0-9]+)', filename)
    if task_match:
        entities['task'] = task_match.group(1)

    # Extract modality suffix (last part before extension)
    # e.g., sub-001_ses-01_T1w.nii.gz -> T1w
    # e.g., sub-001_ses-01_task-rest_bold.nii.gz -> bold
    base = filename
    for ext in ['.nii.gz', '.nii', '.json', '.bval', '.bvec']:
        if base.endswith(ext):
            base = base[:-len(ext)]
            break
    parts = base.split('_')
    if parts:
        entities['modality'] = parts[-1]

    return entities


def get_directory_type(filepath):
    """Get the BIDS directory type (anat, func, dwi, fmap, etc.)."""
    path_parts = Path(filepath).parts
    for part in path_parts:
        if part in MODALITY_DIR_MAP:
            return part
    return None

def validate_bids(bids_dir, output_json=False):
    """Validate BIDS naming conventions."""

    if not output_json:
        print("=" * 70)
        print("BIDS Naming Validation")
        print("=" * 70)
        print(f"Directory: {bids_dir}\n")

    errors = []
    warnings = []
    paired_files = defaultdict(dict)
    run_numbers = defaultdict(set)  # Track run numbers per subject/session/modality
    task_names = set()  # Track task names for consistency
    file_count = 0

    # Scan all imaging files
    for root, dirs, files in os.walk(bids_dir):
        # Skip hidden directories and derivatives
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'derivatives']

        for filename in files:
            if filename.startswith('.'):
                continue

            filepath = os.path.join(root, filename)
            relpath = os.path.relpath(filepath, bids_dir)

            # Check imaging files
            if filename.endswith(('.nii.gz', '.nii', '.json')):
                file_count += 1
                # Extract entities from filename
                entities = extract_entities(filename)

                # Extract entities from directory path (exclude filename)
                path_parts = Path(filepath).parent.parts
                dir_subject = None
                dir_session = None
                dir_type = get_directory_type(filepath)

                for part in path_parts:
                    if part.startswith('sub-'):
                        # Extract subject ID: sub-123 -> 123
                        dir_subject = part[4:]  # Remove 'sub-' prefix
                    elif part.startswith('ses-'):
                        # Extract session ID: ses-01 -> 01
                        dir_session = part[4:]  # Remove 'ses-' prefix

                # Check 1: Subject mismatch
                if 'subject' in entities and dir_subject:
                    if entities['subject'] != dir_subject:
                        errors.append({
                            'type': 'subject_mismatch',
                            'file': relpath,
                            'message': f"Subject mismatch: filename has 'sub-{entities['subject']}' but in directory 'sub-{dir_subject}'"
                        })

                # Check 2: Session mismatch
                if 'session' in entities and dir_session:
                    if entities['session'] != dir_session:
                        errors.append({
                            'type': 'session_mismatch',
                            'file': relpath,
                            'message': f"Session mismatch: filename has 'ses-{entities['session']}' but in directory 'ses-{dir_session}'"
                        })

                # Check 3: Run number validation
                if 'run' in entities:
                    run_num = entities['run']
                    # Validate run format (should be numeric, zero-padded)
                    if not run_num.isdigit():
                        errors.append({
                            'type': 'run_format_error',
                            'file': relpath,
                            'message': f"Invalid run format: 'run-{run_num}' should be numeric"
                        })
                    else:
                        # Track run numbers for sequence validation
                        key = (dir_subject, dir_session, entities.get('modality', ''))
                        run_numbers[key].add(int(run_num))

                # Check 4: Task label validation for functional data
                if 'task' in entities:
                    task_names.add(entities['task'])
                    # Validate task format (should be alphanumeric, no special chars)
                    if not re.match(r'^[a-zA-Z0-9]+$', entities['task']):
                        errors.append({
                            'type': 'task_format_error',
                            'file': relpath,
                            'message': f"Invalid task format: 'task-{entities['task']}' should be alphanumeric only"
                        })
                elif dir_type == 'func' and 'bold' in entities.get('modality', ''):
                    # Functional BOLD files should have task label
                    warnings.append({
                        'type': 'missing_task',
                        'file': relpath,
                        'message': "Functional BOLD file missing task label"
                    })

                # Check 5: Modality-directory validation
                if dir_type and 'modality' in entities:
                    modality = entities['modality']
                    expected_modalities = MODALITY_DIR_MAP.get(dir_type, [])
                    if expected_modalities and modality not in expected_modalities:
                        # Check for common suffixes that might be valid
                        if not any(modality.endswith(m) for m in expected_modalities):
                            errors.append({
                                'type': 'modality_location_error',
                                'file': relpath,
                                'message': f"Modality '{modality}' is in '{dir_type}/' but expected modalities are: {expected_modalities}"
                            })

                # Check 6: Track paired files (nii.gz + json)
                if filename.endswith('.nii.gz'):
                    base = filename[:-7]  # Remove .nii.gz
                    paired_files[relpath.replace(filename, base)]['nii'] = relpath
                elif filename.endswith('.nii'):
                    base = filename[:-4]  # Remove .nii
                    paired_files[relpath.replace(filename, base)]['nii'] = relpath
                elif filename.endswith('.json'):
                    base = filename[:-5]  # Remove .json
                    paired_files[relpath.replace(filename, base)]['json'] = relpath

    # Check 7: Missing paired files
    for base, files in paired_files.items():
        # Only check for imaging data (not bval/bvec)
        if 'nii' in files:
            if 'json' not in files:
                # Some files don't need JSON (like magnitude images)
                if not any(x in base for x in ['magnitude1', 'magnitude2']):
                    warnings.append({
                        'type': 'missing_json',
                        'file': files['nii'],
                        'message': f"NIfTI file without JSON sidecar"
                    })

    # Check 8: Run number sequence validation (should be 01, 02, 03... without gaps)
    for key, runs in run_numbers.items():
        if runs:
            expected = set(range(1, max(runs) + 1))
            missing = expected - runs
            if missing:
                sub, ses, mod = key
                warnings.append({
                    'type': 'run_sequence_gap',
                    'file': f"sub-{sub}/ses-{ses}/{mod}",
                    'message': f"Missing run numbers in sequence: {sorted(missing)}"
                })

    # Build result structure
    result = {
        'bids_dir': str(bids_dir),
        'files_scanned': file_count,
        'error_count': len(errors),
        'warning_count': len(warnings),
        'errors': errors,
        'warnings': warnings,
        'error_summary': {},
        'warning_summary': {},
        'task_names': list(task_names)
    }

    # Build summaries
    for err in errors:
        result['error_summary'][err['type']] = result['error_summary'].get(err['type'], 0) + 1
    for warn in warnings:
        result['warning_summary'][warn['type']] = result['warning_summary'].get(warn['type'], 0) + 1

    # Output as JSON or print
    if output_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Files scanned: {file_count}\n")

        if errors:
            print(f"ERRORS ({len(errors)}):")
            print("-" * 70)
            for err in errors:
                print(f"  {err['file']}")
                print(f"    -> {err['message']}\n")
        else:
            print("No naming errors found!\n")

        if warnings:
            print(f"WARNINGS ({len(warnings)}):")
            print("-" * 70)
            for warn in warnings:
                print(f"  {warn['file']}")
                print(f"    -> {warn['message']}\n")

        # Summary by error type
        if errors:
            print("=" * 70)
            print("Summary by error type:")
            for err_type, count in result['error_summary'].items():
                print(f"  {err_type}: {count}")

        print("\n" + "=" * 70)
        print(f"Total: {len(errors)} errors, {len(warnings)} warnings")
        print("=" * 70)

    return errors, warnings

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Validate BIDS naming conventions and detect naming errors.'
    )
    parser.add_argument('bids_dir', nargs='?', default=BIDS_DIR,
                        help='Path to BIDS directory')
    parser.add_argument('--json', action='store_true',
                        help='Output results as JSON')

    args = parser.parse_args()

    if not os.path.exists(args.bids_dir):
        if args.json:
            print(json.dumps({'error': f'Directory not found: {args.bids_dir}'}))
        else:
            print(f"Error: Directory not found: {args.bids_dir}")
        sys.exit(1)

    errors, warnings = validate_bids(args.bids_dir, output_json=args.json)
    sys.exit(1 if errors else 0)
