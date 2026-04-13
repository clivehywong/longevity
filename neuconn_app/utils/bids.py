"""
BIDS Directory Utilities

Functions for scanning and parsing BIDS directories:
- scan_bids_directory(): Detect subjects, sessions, modalities
- detect_acquisition_params(): Extract TR, volumes from JSON
- validate_bids_structure(): Check BIDS compliance
- move_to_excluded(): Move bad scans to bids_excluded/
- restore_from_excluded(): Restore previously excluded files
- load_exclusion_manifest(): Read exclusion log

Implementation: Phase 1 (partial), Phase 2 (complete)
"""

from pathlib import Path
from typing import Dict, List, Optional
import json
import nibabel as nib
import shutil
from datetime import datetime


def scan_bids_directory(bids_dir: Path) -> Dict:
    """
    Scan BIDS directory and return summary of available data.
    Optimized for speed - only counts directories, not all files.

    Returns:
        dict with keys: subjects, sessions, modalities, file_counts
    """
    bids_dir = Path(bids_dir)

    if not bids_dir.exists():
        return {'error': f"BIDS directory not found: {bids_dir}"}

    results = {
        'subjects': [],
        'sessions': set(),
        'modalities': {},
    }

    # Scan for subjects (fast - just list directories)
    subject_dirs = sorted([d for d in bids_dir.iterdir()
                          if d.is_dir() and d.name.startswith('sub-')])

    results['subjects'] = [d.name for d in subject_dirs]

    # Quick scan: Just check first subject for modality structure
    # Then assume same structure for all (BIDS compliance)
    modality_counts = {}

    for sub_dir in subject_dirs:
        session_dirs = sorted([d for d in sub_dir.iterdir()
                              if d.is_dir() and d.name.startswith('ses-')])

        if not session_dirs:
            continue

        for ses_dir in session_dirs:
            results['sessions'].add(ses_dir.name)

            # Check modalities (anat, func, dwi, fmap) - just directory existence
            for modality in ['anat', 'func', 'dwi', 'fmap']:
                mod_dir = ses_dir / modality

                if mod_dir.exists():
                    if modality not in modality_counts:
                        modality_counts[modality] = {
                            'subjects': set(),
                            'sessions': set(),
                            'files': 0
                        }

                    modality_counts[modality]['subjects'].add(sub_dir.name)
                    modality_counts[modality]['sessions'].add(f"{sub_dir.name}/{ses_dir.name}")

                    # Quick count: just count nii.gz files
                    modality_counts[modality]['files'] += len(list(mod_dir.glob("*.nii.gz")))

    # Convert to output format
    for modality, counts in modality_counts.items():
        results['modalities'][modality] = {
            'subject_count': len(counts['subjects']),
            'session_count': len(counts['sessions']),
            'file_count': counts['files'],
            'sample_subjects': sorted(list(counts['subjects']))[:5]
        }

    results['sessions'] = sorted(list(results['sessions']))

    return results


def detect_acquisition_params(bids_dir: Path) -> Dict:
    """
    Extract acquisition parameters from BIDS JSON sidecars.

    Returns:
        dict with TR, volumes, voxel_size, etc.
    """
    bids_dir = Path(bids_dir)

    params = {
        'tr': None,
        'volumes': [],
        'voxel_sizes': {},
        'inconsistencies': []
    }

    # Scan functional JSON files for TR
    func_jsons = list(bids_dir.rglob("**/func/*_bold.json"))

    for json_file in func_jsons[:10]:  # Sample first 10
        try:
            with open(json_file, 'r') as f:
                metadata = json.load(f)

            if 'RepetitionTime' in metadata:
                tr = metadata['RepetitionTime']
                if params['tr'] is None:
                    params['tr'] = tr
                elif abs(params['tr'] - tr) > 0.001:  # Different TR
                    params['inconsistencies'].append(
                        f"TR mismatch: {json_file.name} has TR={tr}, expected {params['tr']}"
                    )
        except Exception as e:
            params['inconsistencies'].append(f"Error reading {json_file.name}: {e}")

    # Scan NIfTI files for volumes
    func_niftis = list(bids_dir.rglob("**/func/*_bold.nii.gz"))

    for nifti_file in func_niftis[:10]:  # Sample first 10
        try:
            img = nib.load(nifti_file)
            shape = img.shape
            n_vols = shape[3] if len(shape) == 4 else 1

            params['volumes'].append({
                'file': nifti_file.name,
                'volumes': n_vols
            })
        except Exception as e:
            params['inconsistencies'].append(f"Error reading {nifti_file.name}: {e}")

    return params


def move_to_excluded(bids_dir: Path, excluded_dir: Path,
                     subject: str, session: str, file_path: Path,
                     reason: str, dry_run: bool = False) -> Dict:
    """
    Move file to bids_excluded/ maintaining BIDS structure.

    Args:
        bids_dir: Source BIDS directory
        excluded_dir: Exclusion directory
        subject: Subject ID (e.g., 'sub-033')
        session: Session ID (e.g., 'ses-01')
        file_path: Full path to file to exclude
        reason: Exclusion reason
        dry_run: If True, don't actually move files

    Returns:
        dict with status and destination path
    """
    import shutil
    from datetime import datetime

    file_path = Path(file_path)

    if not file_path.exists():
        return {'status': 'error', 'message': 'File not found'}

    # Construct relative path
    try:
        rel_path = file_path.relative_to(bids_dir)
    except ValueError:
        return {'status': 'error', 'message': 'File not in BIDS directory'}

    # Destination path
    dest_path = excluded_dir / rel_path
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if not dry_run:
        # Move NIfTI file
        shutil.move(str(file_path), str(dest_path))

        # Move JSON sidecar if exists
        json_path = file_path.with_suffix('.json')
        if json_path.exists():
            dest_json = dest_path.with_suffix('.json')
            shutil.move(str(json_path), str(dest_json))

        # Update exclusion manifest
        manifest = load_exclusion_manifest(excluded_dir)
        manifest.append({
            'file': str(rel_path),
            'subject': subject,
            'session': session,
            'reason': reason,
            'excluded_by': 'user',
            'timestamp': datetime.now().isoformat()
        })
        save_exclusion_manifest(excluded_dir, manifest)

    return {'status': 'success', 'dest': str(dest_path)}


def restore_from_excluded(bids_dir: Path, excluded_dir: Path,
                          file_path: Path) -> Dict:
    """
    Restore excluded file back to BIDS directory.

    Args:
        bids_dir: Destination BIDS directory
        excluded_dir: Source exclusion directory
        file_path: Path to file in exclusion directory

    Returns:
        dict with status
    """
    import shutil

    file_path = Path(file_path)

    if not file_path.exists():
        return {'status': 'error', 'message': 'File not found in exclusion directory'}

    # Construct relative path
    try:
        rel_path = file_path.relative_to(excluded_dir)
    except ValueError:
        return {'status': 'error', 'message': 'File not in exclusion directory'}

    # Destination path in BIDS
    dest_path = bids_dir / rel_path
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Move NIfTI back
    shutil.move(str(file_path), str(dest_path))

    # Move JSON sidecar if exists
    json_path = file_path.with_suffix('.json')
    if json_path.exists():
        dest_json = dest_path.with_suffix('.json')
        shutil.move(str(json_path), str(dest_json))

    # Update manifest
    manifest = load_exclusion_manifest(excluded_dir)
    manifest = [entry for entry in manifest if entry['file'] != str(rel_path)]
    save_exclusion_manifest(excluded_dir, manifest)

    return {'status': 'success', 'restored': str(dest_path)}


def load_exclusion_manifest(excluded_dir: Path) -> list:
    """Load exclusion manifest JSON."""
    manifest_path = excluded_dir / "exclusion_manifest.json"

    if manifest_path.exists():
        with open(manifest_path, 'r') as f:
            return json.load(f)
    return []


def save_exclusion_manifest(excluded_dir: Path, manifest: list):
    """Save exclusion manifest JSON."""
    excluded_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = excluded_dir / "exclusion_manifest.json"

    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
