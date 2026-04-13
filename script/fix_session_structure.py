#!/usr/bin/env python3
"""
Fix BIDS directory structure for subjects without session folders.

For subjects that have modality folders directly under sub-XXX/ instead of
under sub-XXX/ses-01/, this script:
1. Creates the ses-01 folder
2. Moves all modality folders into ses-01/
3. Ensures all files are properly named with ses-01

Usage:
    python fix_session_structure.py bids/ --dry-run
    python fix_session_structure.py bids/ --execute
"""

import argparse
import shutil
import sys
from pathlib import Path


def fix_subject_structure(subject_dir: Path, dry_run: bool = True) -> dict:
    """
    Fix directory structure for a single subject.

    Args:
        subject_dir: Path to subject directory (e.g., bids/sub-066)
        dry_run: If True, only preview changes

    Returns:
        dict with operation results
    """
    subject_id = subject_dir.name
    results = {'moved_dirs': [], 'renamed_files': [], 'errors': []}

    # Check if ses-01 already exists
    ses_01_dir = subject_dir / 'ses-01'
    if ses_01_dir.exists():
        print(f"  {subject_id}: ses-01 already exists, skipping")
        return results

    # Find direct modality folders
    modality_dirs = [d for d in subject_dir.iterdir()
                     if d.is_dir() and d.name in ['anat', 'func', 'dwi', 'fmap', 'mrs', 'perf']]

    if not modality_dirs:
        print(f"  {subject_id}: No modality folders found directly under subject")
        return results

    print(f"\n{subject_id}:")
    print(f"  Found {len(modality_dirs)} modality folders: {[d.name for d in modality_dirs]}")

    # Create ses-01 directory
    if dry_run:
        print(f"  WOULD CREATE: {ses_01_dir.relative_to(subject_dir.parent.parent)}")
    else:
        ses_01_dir.mkdir(exist_ok=True)
        print(f"  CREATED: ses-01/")

    # Move each modality folder
    for mod_dir in modality_dirs:
        new_mod_dir = ses_01_dir / mod_dir.name

        if dry_run:
            print(f"  WOULD MOVE: {mod_dir.name}/ -> ses-01/{mod_dir.name}/")
            # Check files that would need renaming
            for file_path in mod_dir.rglob('*'):
                if file_path.is_file() and not file_path.name.startswith('.'):
                    # Check for issues in filename
                    if file_path.name.startswith('_'):
                        print(f"    - Would fix leading underscore: {file_path.name}")
                    if '_ses01_' in file_path.name:
                        print(f"    - Would fix ses01 -> ses-01: {file_path.name}")
        else:
            try:
                shutil.move(str(mod_dir), str(new_mod_dir))
                print(f"  MOVED: {mod_dir.name}/ -> ses-01/{mod_dir.name}/")
                results['moved_dirs'].append(mod_dir.name)
            except Exception as e:
                msg = f"Failed to move {mod_dir}: {e}"
                print(f"  ERROR: {msg}")
                results['errors'].append(msg)

    # Fix file naming issues within ses-01
    if not dry_run and ses_01_dir.exists():
        fix_file_names(ses_01_dir, subject_id, dry_run=False, results=results)

    return results


def fix_file_names(ses_dir: Path, subject_id: str, dry_run: bool = True, results: dict = None) -> None:
    """
    Fix file naming issues within a session directory.

    - Remove leading underscores
    - Fix ses01 -> ses-01
    - Fix other common naming issues
    """
    if results is None:
        results = {'renamed_files': [], 'errors': []}

    for file_path in ses_dir.rglob('*'):
        if not file_path.is_file() or file_path.name.startswith('.'):
            continue

        old_name = file_path.name
        new_name = old_name

        # Fix leading underscore
        if new_name.startswith('_'):
            new_name = new_name[1:]

        # Fix ses01 -> ses-01
        new_name = new_name.replace('_ses01_', '_ses-01_')
        new_name = new_name.replace('ses01_', 'ses-01_')

        # Fix trun-01 -> run-01 (typo in sub-082)
        new_name = new_name.replace('_trun-', '_run-')

        if new_name != old_name:
            new_path = file_path.parent / new_name

            if dry_run:
                print(f"  WOULD RENAME: {old_name}")
                print(f"            TO: {new_name}")
            else:
                try:
                    file_path.rename(new_path)
                    print(f"    Renamed: {old_name} -> {new_name}")
                    results['renamed_files'].append((old_name, new_name))
                except Exception as e:
                    msg = f"Failed to rename {file_path}: {e}"
                    print(f"    ERROR: {msg}")
                    results['errors'].append(msg)


def main():
    parser = argparse.ArgumentParser(
        description='Fix BIDS directory structure for subjects without session folders'
    )
    parser.add_argument('bids_dir', help='Path to BIDS directory')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Preview changes without executing (default: True)')
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute the fixes (disables dry-run)')
    parser.add_argument('--subjects', nargs='+',
                        help='Specific subjects to fix (e.g., sub-066 sub-069)')

    args = parser.parse_args()
    bids_dir = Path(args.bids_dir).resolve()
    dry_run = not args.execute

    print("=" * 70)
    print("BIDS Session Structure Fixer")
    print("=" * 70)
    print(f"BIDS directory: {bids_dir}")
    print(f"Mode: {'DRY RUN (preview only)' if dry_run else 'EXECUTE (will modify files)'}")
    print("=" * 70)

    if not bids_dir.exists():
        print(f"Error: Directory not found: {bids_dir}")
        sys.exit(1)

    if not dry_run:
        print("\n" + "!" * 70)
        print("WARNING: This will MODIFY your BIDS directory structure!")
        print("Make sure you have a backup before proceeding.")
        print("!" * 70)
        response = input("\nType 'yes' to proceed: ")
        if response.lower() != 'yes':
            print("Aborted.")
            sys.exit(0)

    # Find subjects to fix
    if args.subjects:
        subjects_to_fix = [bids_dir / sub for sub in args.subjects]
    else:
        # Auto-detect subjects without session folders
        subjects_to_fix = []
        for sub_dir in sorted(bids_dir.glob('sub-*')):
            sessions = list(sub_dir.glob('ses-*'))
            direct_modalities = [d for d in sub_dir.iterdir()
                                if d.is_dir() and d.name in ['anat', 'func', 'dwi', 'fmap', 'mrs']]
            if direct_modalities and len(sessions) == 0:
                subjects_to_fix.append(sub_dir)

    if not subjects_to_fix:
        print("\nNo subjects found that need fixing.")
        sys.exit(0)

    print(f"\nFound {len(subjects_to_fix)} subjects to fix:")
    for sub_dir in subjects_to_fix:
        print(f"  - {sub_dir.name}")

    if dry_run:
        print("\nWARNING: Running in DRY RUN mode. No files will be modified.")
        print("Use --execute to actually apply fixes.\n")

    # Process each subject
    all_results = {}
    for sub_dir in subjects_to_fix:
        results = fix_subject_structure(sub_dir, dry_run=dry_run)
        all_results[sub_dir.name] = results

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_moved = sum(len(r['moved_dirs']) for r in all_results.values())
    total_renamed = sum(len(r['renamed_files']) for r in all_results.values())
    total_errors = sum(len(r['errors']) for r in all_results.values())

    print(f"Subjects processed: {len(all_results)}")
    print(f"Directories moved: {total_moved}")
    print(f"Files renamed: {total_renamed}")
    print(f"Errors: {total_errors}")

    if dry_run:
        print("\nTo apply these changes, run with --execute")
    else:
        print("\nChanges have been applied.")
        print("Run validation to verify: python script/validate_bids_names.py bids/")


if __name__ == '__main__':
    main()
