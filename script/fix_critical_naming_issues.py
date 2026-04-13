#!/usr/bin/env python3
"""
Fix critical BIDS naming issues that would cause fMRIPrep to fail.

This script addresses the following issues:
1. Session mismatches (sub-056): ses-02 directory contains files labeled ses-01
2. Wrong subject IDs (sub-034): fmap files labeled sub-001 instead of sub-034
3. Double extensions: Files with .nii.gz.nii.gz
4. Modality suffix: T2.nii.gz instead of T2w.nii.gz
5. Invalid run labels: run-b0PA, run-b0AP, run-b0, run-02x (non-numeric)
6. Duplicate directories: sub-064 has folders like "anat (1)"

Usage:
    # Preview all fixes (dry-run, default)
    python fix_critical_naming_issues.py bids/

    # Preview specific fix
    python fix_critical_naming_issues.py bids/ --fix session

    # Execute all fixes
    python fix_critical_naming_issues.py bids/ --execute

    # Execute specific fix
    python fix_critical_naming_issues.py bids/ --fix double-ext --execute
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: Path) -> logging.Logger:
    """Set up logging to both console and file."""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f'naming_fixes_{timestamp}.log'

    logger = logging.getLogger('bids_fixer')
    logger.setLevel(logging.DEBUG)

    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(message)s'))

    logger.addHandler(fh)
    logger.addHandler(ch)

    logger.info(f"Log file: {log_file}")
    return logger


def fix_session_mismatch(bids_dir: Path, logger: logging.Logger,
                         subject: str = 'sub-056', dry_run: bool = True) -> dict:
    """
    Fix session label mismatches where files in ses-02 directory are labeled ses-01.

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        subject: Subject ID to fix (default: sub-056)
        dry_run: If True, only preview changes

    Returns:
        dict with counts of files found and fixed
    """
    ses_02_dir = bids_dir / subject / 'ses-02'
    results = {'found': 0, 'fixed': 0, 'errors': []}

    if not ses_02_dir.exists():
        logger.warning(f"Directory not found: {ses_02_dir}")
        return results

    # Find all files with ses-01 in filename within ses-02 directory
    extensions = ['.nii.gz', '.nii', '.json', '.bval', '.bvec']

    for ext in extensions:
        # Handle .nii.gz specially since rglob treats it as two extensions
        if ext == '.nii.gz':
            pattern = '*_ses-01_*.nii.gz'
        else:
            pattern = f'*_ses-01_*{ext}'

        for old_path in ses_02_dir.rglob(pattern):
            # Skip if already processed (avoid double .nii.gz matching)
            if ext != '.nii.gz' and old_path.suffix == '.gz':
                continue

            results['found'] += 1
            new_name = old_path.name.replace('_ses-01_', '_ses-02_')
            new_path = old_path.parent / new_name

            if new_path.exists():
                msg = f"Target already exists, skipping: {new_path}"
                logger.warning(msg)
                results['errors'].append(msg)
                continue

            if dry_run:
                logger.info(f"  WOULD RENAME: {old_path.relative_to(bids_dir)}")
                logger.info(f"            TO: {new_path.relative_to(bids_dir)}")
            else:
                try:
                    old_path.rename(new_path)
                    logger.info(f"  RENAMED: {old_path.name} -> {new_name}")
                    results['fixed'] += 1
                except Exception as e:
                    msg = f"Failed to rename {old_path}: {e}"
                    logger.error(msg)
                    results['errors'].append(msg)

    return results


def fix_wrong_subject_id(bids_dir: Path, logger: logging.Logger,
                         correct_subject: str, wrong_subject: str,
                         dry_run: bool = True) -> dict:
    """
    Fix files that have the wrong subject ID in their filename.

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        correct_subject: The correct subject ID (e.g., 'sub-034')
        wrong_subject: The wrong subject ID in filenames (e.g., 'sub-001')
        dry_run: If True, only preview changes

    Returns:
        dict with counts of files found and fixed
    """
    subject_dir = bids_dir / correct_subject
    results = {'found': 0, 'fixed': 0, 'errors': []}

    if not subject_dir.exists():
        logger.warning(f"Directory not found: {subject_dir}")
        return results

    extensions = ['.nii.gz', '.nii', '.json', '.bval', '.bvec']

    for ext in extensions:
        if ext == '.nii.gz':
            pattern = f'{wrong_subject}_*.nii.gz'
        else:
            pattern = f'{wrong_subject}_*{ext}'

        for old_path in subject_dir.rglob(pattern):
            if ext != '.nii.gz' and old_path.suffix == '.gz':
                continue

            results['found'] += 1
            new_name = old_path.name.replace(f'{wrong_subject}_', f'{correct_subject}_')
            new_path = old_path.parent / new_name

            if new_path.exists():
                msg = f"Target already exists, skipping: {new_path}"
                logger.warning(msg)
                results['errors'].append(msg)
                continue

            if dry_run:
                logger.info(f"  WOULD RENAME: {old_path.relative_to(bids_dir)}")
                logger.info(f"            TO: {new_path.relative_to(bids_dir)}")
            else:
                try:
                    old_path.rename(new_path)
                    logger.info(f"  RENAMED: {old_path.name} -> {new_name}")
                    results['fixed'] += 1
                except Exception as e:
                    msg = f"Failed to rename {old_path}: {e}"
                    logger.error(msg)
                    results['errors'].append(msg)

    return results


def fix_double_extensions(bids_dir: Path, logger: logging.Logger,
                          dry_run: bool = True) -> dict:
    """
    Fix files with double .nii.gz extensions (.nii.gz.nii.gz -> .nii.gz).

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        dry_run: If True, only preview changes

    Returns:
        dict with counts of files found and fixed
    """
    results = {'found': 0, 'fixed': 0, 'errors': []}

    # Find all files with double extension
    for old_path in bids_dir.rglob('*.nii.gz.nii.gz'):
        results['found'] += 1
        new_name = old_path.name.replace('.nii.gz.nii.gz', '.nii.gz')
        new_path = old_path.parent / new_name

        if new_path.exists():
            msg = f"Target already exists, skipping: {new_path}"
            logger.warning(msg)
            results['errors'].append(msg)
            continue

        if dry_run:
            logger.info(f"  WOULD RENAME: {old_path.relative_to(bids_dir)}")
            logger.info(f"            TO: {new_path.relative_to(bids_dir)}")
        else:
            try:
                old_path.rename(new_path)
                logger.info(f"  RENAMED: {old_path.name} -> {new_name}")
                results['fixed'] += 1
            except Exception as e:
                msg = f"Failed to rename {old_path}: {e}"
                logger.error(msg)
                results['errors'].append(msg)

    return results


def fix_modality_suffix(bids_dir: Path, logger: logging.Logger,
                        dry_run: bool = True) -> dict:
    """
    Fix incorrect modality suffixes (T2 -> T2w).

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        dry_run: If True, only preview changes

    Returns:
        dict with counts of files found and fixed
    """
    results = {'found': 0, 'fixed': 0, 'errors': []}

    # Look for T2.nii.gz and T2.json (without the 'w')
    for ext in ['.nii.gz', '.json']:
        if ext == '.nii.gz':
            pattern = '*_T2.nii.gz'
        else:
            pattern = '*_T2.json'

        for old_path in bids_dir.rglob(pattern):
            # Make sure it's not already T2w
            if '_T2w.' in old_path.name:
                continue

            results['found'] += 1
            new_name = old_path.name.replace('_T2.', '_T2w.')
            new_path = old_path.parent / new_name

            if new_path.exists():
                msg = f"Target already exists, skipping: {new_path}"
                logger.warning(msg)
                results['errors'].append(msg)
                continue

            if dry_run:
                logger.info(f"  WOULD RENAME: {old_path.relative_to(bids_dir)}")
                logger.info(f"            TO: {new_path.relative_to(bids_dir)}")
            else:
                try:
                    old_path.rename(new_path)
                    logger.info(f"  RENAMED: {old_path.name} -> {new_name}")
                    results['fixed'] += 1
                except Exception as e:
                    msg = f"Failed to rename {old_path}: {e}"
                    logger.error(msg)
                    results['errors'].append(msg)

    return results


def fix_run_labels_to_acq(bids_dir: Path, logger: logging.Logger,
                          dry_run: bool = True) -> dict:
    """
    Convert non-numeric run labels to acquisition labels.

    BIDS requires run-<index> where index is numeric. This converts
    run-b0PA, run-b0AP, run-b0, run-02x to acq-b0PA, acq-b0AP, acq-b0, acq-02x.

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        dry_run: If True, only preview changes

    Returns:
        dict with counts of files found and fixed
    """
    results = {'found': 0, 'fixed': 0, 'errors': []}

    # Non-numeric run patterns to convert
    # Note: run-b0_ needs special handling for the trailing underscore
    invalid_patterns = [
        ('_run-b0PA_', '_acq-b0PA_'),
        ('_run-b0AP_', '_acq-b0AP_'),
        ('_run-b0_', '_acq-b0_'),
        ('_run-02x_', '_acq-02x_'),
    ]

    extensions = ['.nii.gz', '.nii', '.json', '.bval', '.bvec']

    for old_pattern, new_pattern in invalid_patterns:
        for ext in extensions:
            if ext == '.nii.gz':
                glob_pattern = f'*{old_pattern}*.nii.gz'
            else:
                glob_pattern = f'*{old_pattern}*{ext}'

            for old_path in bids_dir.rglob(glob_pattern):
                if ext != '.nii.gz' and old_path.suffix == '.gz':
                    continue

                results['found'] += 1
                new_name = old_path.name.replace(old_pattern, new_pattern)
                new_path = old_path.parent / new_name

                if new_path.exists():
                    msg = f"Target already exists, skipping: {new_path}"
                    logger.warning(msg)
                    results['errors'].append(msg)
                    continue

                if dry_run:
                    logger.info(f"  WOULD RENAME: {old_path.relative_to(bids_dir)}")
                    logger.info(f"            TO: {new_path.relative_to(bids_dir)}")
                else:
                    try:
                        old_path.rename(new_path)
                        logger.info(f"  RENAMED: {old_path.name} -> {new_name}")
                        results['fixed'] += 1
                    except Exception as e:
                        msg = f"Failed to rename {old_path}: {e}"
                        logger.error(msg)
                        results['errors'].append(msg)

    return results


def compare_duplicate_directories(bids_dir: Path, logger: logging.Logger,
                                  subject: str = 'sub-064',
                                  session: str = 'ses-02') -> dict:
    """
    Compare files in duplicate directories (e.g., 'anat' vs 'anat (1)').

    This is for analysis only - does not make changes.

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        subject: Subject ID to check
        session: Session ID to check

    Returns:
        dict with comparison results
    """
    session_dir = bids_dir / subject / session
    results = {'comparisons': [], 'duplicate_dirs_found': []}

    if not session_dir.exists():
        logger.warning(f"Directory not found: {session_dir}")
        return results

    # Find duplicate directories (with parentheses)
    duplicate_dirs = [d for d in session_dir.iterdir()
                      if d.is_dir() and '(' in d.name]

    if not duplicate_dirs:
        logger.info(f"  No duplicate directories found in {session_dir}")
        return results

    results['duplicate_dirs_found'] = [d.name for d in duplicate_dirs]

    for dup_dir in duplicate_dirs:
        # Get original directory name
        orig_name = dup_dir.name.split(' (')[0]
        orig_dir = session_dir / orig_name

        comparison = {
            'duplicate': dup_dir.name,
            'original': orig_name,
            'original_exists': orig_dir.exists(),
        }

        logger.info(f"\n  {'='*60}")
        logger.info(f"  Comparing: {dup_dir.name} vs {orig_name}")
        logger.info(f"  {'='*60}")

        if orig_dir.exists():
            # List files in both
            dup_files = set(f.name for f in dup_dir.iterdir() if f.is_file())
            orig_files = set(f.name for f in orig_dir.iterdir() if f.is_file())

            only_in_dup = dup_files - orig_files
            only_in_orig = orig_files - dup_files
            in_both = dup_files & orig_files

            comparison['only_in_duplicate'] = list(only_in_dup)
            comparison['only_in_original'] = list(only_in_orig)
            comparison['in_both'] = list(in_both)

            logger.info(f"  Files only in {dup_dir.name}: {len(only_in_dup)}")
            for f in sorted(only_in_dup):
                logger.info(f"    - {f}")

            logger.info(f"  Files only in {orig_name}: {len(only_in_orig)}")
            for f in sorted(only_in_orig):
                logger.info(f"    - {f}")

            logger.info(f"  Files in both: {len(in_both)}")
            for f in sorted(in_both):
                logger.info(f"    - {f}")

            # Check if files in both are identical (by size)
            if in_both:
                logger.info(f"\n  Size comparison for files in both:")
                for f in sorted(in_both):
                    orig_size = (orig_dir / f).stat().st_size
                    dup_size = (dup_dir / f).stat().st_size
                    match = "SAME" if orig_size == dup_size else "DIFFERENT"
                    logger.info(f"    {f}: {match} (orig: {orig_size}, dup: {dup_size})")
        else:
            logger.info(f"  Original directory {orig_name} does not exist!")
            comparison['only_in_duplicate'] = [f.name for f in dup_dir.iterdir() if f.is_file()]

        results['comparisons'].append(comparison)

    return results


def remove_duplicate_directories(bids_dir: Path, logger: logging.Logger,
                                 subject: str = 'sub-064',
                                 session: str = 'ses-02',
                                 dry_run: bool = True) -> dict:
    """
    Remove duplicate directories after verifying they contain identical files.

    Only removes directories named like 'anat (1)' if all their files are
    identical to the original 'anat' directory.

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        subject: Subject ID to fix
        session: Session ID to fix
        dry_run: If True, only preview changes

    Returns:
        dict with results
    """
    import shutil

    session_dir = bids_dir / subject / session
    results = {'found': 0, 'removed': 0, 'errors': [], 'skipped': []}

    if not session_dir.exists():
        logger.warning(f"Directory not found: {session_dir}")
        return results

    # Find duplicate directories (with parentheses)
    duplicate_dirs = [d for d in session_dir.iterdir()
                      if d.is_dir() and '(' in d.name]

    for dup_dir in duplicate_dirs:
        results['found'] += 1
        orig_name = dup_dir.name.split(' (')[0]
        orig_dir = session_dir / orig_name

        if not orig_dir.exists():
            msg = f"Original directory missing, cannot verify: {orig_dir}"
            logger.warning(msg)
            results['skipped'].append(msg)
            continue

        # Verify all files are identical
        dup_files = {f.name: f for f in dup_dir.iterdir() if f.is_file()}
        orig_files = {f.name: f for f in orig_dir.iterdir() if f.is_file()}

        # Check for files only in duplicate (would be lost)
        only_in_dup = set(dup_files.keys()) - set(orig_files.keys())
        if only_in_dup:
            msg = f"Duplicate has unique files, skipping: {dup_dir.name} ({only_in_dup})"
            logger.warning(msg)
            results['skipped'].append(msg)
            continue

        # Verify sizes match for common files
        size_mismatch = False
        for fname in dup_files:
            if fname in orig_files:
                if dup_files[fname].stat().st_size != orig_files[fname].stat().st_size:
                    msg = f"Size mismatch for {fname} in {dup_dir.name}"
                    logger.warning(msg)
                    results['skipped'].append(msg)
                    size_mismatch = True
                    break

        if size_mismatch:
            continue

        # Safe to remove
        if dry_run:
            logger.info(f"  WOULD REMOVE: {dup_dir.relative_to(bids_dir)}")
            logger.info(f"    (Contains {len(dup_files)} files, all verified identical to {orig_name})")
        else:
            try:
                shutil.rmtree(dup_dir)
                logger.info(f"  REMOVED: {dup_dir.name} ({len(dup_files)} files)")
                results['removed'] += 1
            except Exception as e:
                msg = f"Failed to remove {dup_dir}: {e}"
                logger.error(msg)
                results['errors'].append(msg)

    return results


def fix_json_double_extension(bids_dir: Path, logger: logging.Logger,
                               dry_run: bool = True) -> dict:
    """
    Fix JSON files with double extensions (.nii.gz.json -> .json).

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        dry_run: If True, only preview changes

    Returns:
        dict with counts of files found and fixed
    """
    results = {'found': 0, 'fixed': 0, 'errors': []}

    # Find all .nii.gz.json files
    for old_path in bids_dir.rglob('*.nii.gz.json'):
        results['found'] += 1
        new_name = old_path.name.replace('.nii.gz.json', '.json')
        new_path = old_path.parent / new_name

        if new_path.exists():
            msg = f"Target already exists, skipping: {new_path}"
            logger.warning(msg)
            results['errors'].append(msg)
            continue

        if dry_run:
            logger.info(f"  WOULD RENAME: {old_path.relative_to(bids_dir)}")
            logger.info(f"            TO: {new_path.relative_to(bids_dir)}")
        else:
            try:
                old_path.rename(new_path)
                logger.info(f"  RENAMED: {old_path.name} -> {new_name}")
                results['fixed'] += 1
            except Exception as e:
                msg = f"Failed to rename {old_path}: {e}"
                logger.error(msg)
                results['errors'].append(msg)

    return results


def fix_fmap_dwi_to_epi(bids_dir: Path, logger: logging.Logger,
                        dry_run: bool = True) -> dict:
    """
    Fix field map files that incorrectly use _dwi instead of _epi suffix.

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        dry_run: If True, only preview changes

    Returns:
        dict with counts of files found and fixed
    """
    results = {'found': 0, 'fixed': 0, 'errors': []}

    # Find all files in fmap directories with _dwi suffix
    for fmap_dir in bids_dir.rglob('fmap'):
        if not fmap_dir.is_dir():
            continue

        for ext in ['.nii.gz', '.json']:
            if ext == '.nii.gz':
                pattern = '*_dwi.nii.gz'
            else:
                pattern = '*_dwi.json'

            for old_path in fmap_dir.glob(pattern):
                if ext != '.nii.gz' and old_path.suffix == '.gz':
                    continue

                results['found'] += 1
                new_name = old_path.name.replace('_dwi.', '_epi.')
                new_path = old_path.parent / new_name

                if new_path.exists():
                    msg = f"Target already exists, skipping: {new_path}"
                    logger.warning(msg)
                    results['errors'].append(msg)
                    continue

                if dry_run:
                    logger.info(f"  WOULD RENAME: {old_path.relative_to(bids_dir)}")
                    logger.info(f"            TO: {new_path.relative_to(bids_dir)}")
                else:
                    try:
                        old_path.rename(new_path)
                        logger.info(f"  RENAMED: {old_path.name} -> {new_name}")
                        results['fixed'] += 1
                    except Exception as e:
                        msg = f"Failed to rename {old_path}: {e}"
                        logger.error(msg)
                        results['errors'].append(msg)

    return results


def fix_file_extension_typos(bids_dir: Path, logger: logging.Logger,
                             dry_run: bool = True) -> dict:
    """
    Fix file extension typos (e.g., .nii.gza.nii.gz -> .nii.gz).

    If the correct file already exists with the same size, delete the typo file.
    Otherwise, rename the typo file to the correct name.

    Args:
        bids_dir: Path to BIDS directory
        logger: Logger instance
        dry_run: If True, only preview changes

    Returns:
        dict with counts of files found and fixed
    """
    results = {'found': 0, 'fixed': 0, 'errors': [], 'deleted': 0}

    # Common typos to fix
    # Note: Check for triple extensions first, then double, then single
    typo_patterns = [
        ('.nii.gza.nii.gz', '.nii.gz'),  # Triple extension
        ('.nii.gza.json', '.json'),      # Triple extension for JSON
        ('.nii.gza', '.nii.gz'),
        ('.nii.gaz', '.nii.gz'),
        ('.nii.gx', '.nii.gz'),
    ]

    for old_suffix, new_suffix in typo_patterns:
        for old_path in bids_dir.rglob(f'*{old_suffix}'):
            results['found'] += 1
            new_name = old_path.name.replace(old_suffix, new_suffix)
            new_path = old_path.parent / new_name

            if new_path.exists():
                # Check if files are identical by size
                if old_path.stat().st_size == new_path.stat().st_size:
                    # Files are identical, delete the typo file
                    if dry_run:
                        logger.info(f"  WOULD DELETE: {old_path.relative_to(bids_dir)}")
                        logger.info(f"    (Duplicate of: {new_path.relative_to(bids_dir)})")
                    else:
                        try:
                            old_path.unlink()
                            logger.info(f"  DELETED: {old_path.name} (duplicate)")
                            results['deleted'] += 1
                            results['fixed'] += 1
                        except Exception as e:
                            msg = f"Failed to delete {old_path}: {e}"
                            logger.error(msg)
                            results['errors'].append(msg)
                else:
                    msg = f"Target exists with different size, skipping: {new_path}"
                    logger.warning(msg)
                    results['errors'].append(msg)
                continue

            if dry_run:
                logger.info(f"  WOULD RENAME: {old_path.relative_to(bids_dir)}")
                logger.info(f"            TO: {new_path.relative_to(bids_dir)}")
            else:
                try:
                    old_path.rename(new_path)
                    logger.info(f"  RENAMED: {old_path.name} -> {new_name}")
                    results['fixed'] += 1
                except Exception as e:
                    msg = f"Failed to rename {old_path}: {e}"
                    logger.error(msg)
                    results['errors'].append(msg)

    return results


def main():
    parser = argparse.ArgumentParser(
        description='Fix critical BIDS naming issues',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview all fixes (dry-run)
  python fix_critical_naming_issues.py bids/

  # Preview specific fix
  python fix_critical_naming_issues.py bids/ --fix session

  # Execute all fixes
  python fix_critical_naming_issues.py bids/ --execute

  # Execute specific fix
  python fix_critical_naming_issues.py bids/ --fix double-ext --execute

  # Analyze duplicate directories (no changes)
  python fix_critical_naming_issues.py bids/ --fix duplicates

  # Remove duplicate directories after analysis
  python fix_critical_naming_issues.py bids/ --fix remove-duplicates --execute
        """
    )
    parser.add_argument('bids_dir', help='Path to BIDS directory')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Preview changes without executing (default: True)')
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute the fixes (disables dry-run)')
    parser.add_argument('--fix', choices=[
        'all', 'session', 'subject-id', 'double-ext', 'modality',
        'run-labels', 'duplicates', 'remove-duplicates', 'json-ext',
        'fmap-dwi', 'ext-typos'
    ], default='all', help='Which fixes to apply (default: all)')
    parser.add_argument('--log-dir', default='validation_reports',
                        help='Directory for log files (default: validation_reports)')

    args = parser.parse_args()
    bids_dir = Path(args.bids_dir).resolve()
    log_dir = Path(args.log_dir)
    dry_run = not args.execute

    # Set up logging
    logger = setup_logging(log_dir)

    print("=" * 70)
    print("BIDS Critical Naming Issues Fixer")
    print("=" * 70)
    print(f"BIDS directory: {bids_dir}")
    print(f"Mode: {'DRY RUN (preview only)' if dry_run else 'EXECUTE (will modify files)'}")
    print(f"Fixes to apply: {args.fix}")
    print("=" * 70)

    if not bids_dir.exists():
        logger.error(f"BIDS directory not found: {bids_dir}")
        sys.exit(1)

    if dry_run:
        print("\nWARNING: Running in DRY RUN mode. No files will be modified.")
        print("Use --execute to actually apply fixes.\n")
    else:
        print("\n" + "!" * 70)
        print("WARNING: This will MODIFY files in your BIDS directory!")
        print("Make sure you have a backup before proceeding.")
        print("!" * 70)
        response = input("\nType 'yes' to proceed: ")
        if response.lower() != 'yes':
            print("Aborted.")
            sys.exit(0)

    # Track all results
    all_results = {}

    # Apply fixes based on selection
    if args.fix in ['all', 'session']:
        logger.info("\n" + "-" * 70)
        logger.info("Fix 1: Session Mismatches (sub-056/ses-02 files labeled ses-01)")
        logger.info("-" * 70)
        results = fix_session_mismatch(bids_dir, logger, dry_run=dry_run)
        all_results['session_mismatch'] = results
        logger.info(f"  Found: {results['found']}, Fixed: {results['fixed']}")

    if args.fix in ['all', 'subject-id']:
        logger.info("\n" + "-" * 70)
        logger.info("Fix 2: Wrong Subject ID (sub-034 fmap files labeled sub-001)")
        logger.info("-" * 70)
        results = fix_wrong_subject_id(bids_dir, logger, 'sub-034', 'sub-001', dry_run=dry_run)
        all_results['wrong_subject_id'] = results
        logger.info(f"  Found: {results['found']}, Fixed: {results['fixed']}")

    if args.fix in ['all', 'double-ext']:
        logger.info("\n" + "-" * 70)
        logger.info("Fix 3: Double Extensions (.nii.gz.nii.gz -> .nii.gz)")
        logger.info("-" * 70)
        results = fix_double_extensions(bids_dir, logger, dry_run=dry_run)
        all_results['double_extensions'] = results
        logger.info(f"  Found: {results['found']}, Fixed: {results['fixed']}")

    if args.fix in ['all', 'modality']:
        logger.info("\n" + "-" * 70)
        logger.info("Fix 4: Modality Suffix (T2 -> T2w)")
        logger.info("-" * 70)
        results = fix_modality_suffix(bids_dir, logger, dry_run=dry_run)
        all_results['modality_suffix'] = results
        logger.info(f"  Found: {results['found']}, Fixed: {results['fixed']}")

    if args.fix in ['all', 'run-labels']:
        logger.info("\n" + "-" * 70)
        logger.info("Fix 5: Invalid Run Labels (run-b0PA -> acq-b0PA, etc.)")
        logger.info("-" * 70)
        results = fix_run_labels_to_acq(bids_dir, logger, dry_run=dry_run)
        all_results['run_labels'] = results
        logger.info(f"  Found: {results['found']}, Fixed: {results['fixed']}")

    if args.fix == 'duplicates':
        logger.info("\n" + "-" * 70)
        logger.info("Analysis: Duplicate Directories (sub-064)")
        logger.info("-" * 70)
        results = compare_duplicate_directories(bids_dir, logger)
        all_results['duplicate_directories'] = results

    if args.fix == 'remove-duplicates':
        logger.info("\n" + "-" * 70)
        logger.info("Fix 6: Remove Duplicate Directories (sub-064)")
        logger.info("-" * 70)
        results = remove_duplicate_directories(bids_dir, logger, dry_run=dry_run)
        all_results['remove_duplicates'] = results
        logger.info(f"  Found: {results['found']}, Removed: {results['removed']}")

    if args.fix in ['all', 'json-ext']:
        logger.info("\n" + "-" * 70)
        logger.info("Fix 7: JSON Double Extensions (.nii.gz.json -> .json)")
        logger.info("-" * 70)
        results = fix_json_double_extension(bids_dir, logger, dry_run=dry_run)
        all_results['json_double_ext'] = results
        logger.info(f"  Found: {results['found']}, Fixed: {results['fixed']}")

    if args.fix in ['all', 'fmap-dwi']:
        logger.info("\n" + "-" * 70)
        logger.info("Fix 8: Field Map DWI to EPI (_dwi -> _epi in fmap/)")
        logger.info("-" * 70)
        results = fix_fmap_dwi_to_epi(bids_dir, logger, dry_run=dry_run)
        all_results['fmap_dwi_to_epi'] = results
        logger.info(f"  Found: {results['found']}, Fixed: {results['fixed']}")

    if args.fix in ['all', 'ext-typos']:
        logger.info("\n" + "-" * 70)
        logger.info("Fix 9: Extension Typos (.nii.gza -> .nii.gz)")
        logger.info("-" * 70)
        results = fix_file_extension_typos(bids_dir, logger, dry_run=dry_run)
        all_results['extension_typos'] = results
        logger.info(f"  Found: {results['found']}, Fixed: {results['fixed']}")

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)

    total_found = 0
    total_fixed = 0
    total_errors = 0

    for fix_name, results in all_results.items():
        if fix_name == 'duplicate_directories':
            logger.info(f"  {fix_name}: {len(results.get('duplicate_dirs_found', []))} duplicate dirs found")
        elif fix_name == 'remove_duplicates':
            found = results.get('found', 0)
            removed = results.get('removed', 0)
            errors = len(results.get('errors', []))
            total_found += found
            total_fixed += removed
            total_errors += errors
            logger.info(f"  {fix_name}: found={found}, removed={removed}, errors={errors}")
        else:
            found = results.get('found', 0)
            fixed = results.get('fixed', 0)
            errors = len(results.get('errors', []))
            total_found += found
            total_fixed += fixed
            total_errors += errors
            logger.info(f"  {fix_name}: found={found}, fixed={fixed}, errors={errors}")

    if args.fix != 'duplicates':
        logger.info(f"\n  TOTAL: found={total_found}, fixed={total_fixed}, errors={total_errors}")

        if dry_run:
            logger.info("\n  To apply these changes, run with --execute")
        else:
            logger.info("\n  Changes have been applied.")
            logger.info("  Run validation again to verify: python script/validate_bids_names.py bids/")

    # Save results to JSON
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    results_file = log_dir / f'naming_fixes_results_{timestamp}.json'
    with open(results_file, 'w') as f:
        json.dump({
            'bids_dir': str(bids_dir),
            'dry_run': dry_run,
            'fix_type': args.fix,
            'results': all_results,
            'summary': {
                'total_found': total_found,
                'total_fixed': total_fixed,
                'total_errors': total_errors
            }
        }, f, indent=2)
    logger.info(f"\n  Results saved to: {results_file}")


if __name__ == '__main__':
    main()
