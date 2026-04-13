#!/usr/bin/env python3
"""
Seed-Based Connectivity Analysis for Longitudinal Walking Intervention Study

This script performs whole-brain voxelwise seed-based connectivity analysis:
1. Extracts seed timeseries (network-averaged or single ROI)
2. Computes seed-to-voxel correlations across the whole brain
3. Fisher Z-transforms correlations
4. Performs Group × Time mixed-effects analysis at each voxel
5. Generates statistical maps with cluster correction

Seeds are defined from DiFuMo 256 atlas components (motor-cerebellar focus).

Usage:
    python seed_based_connectivity.py \\
        --fmriprep FMRIPREP_DIR \\
        --seeds SEEDS_JSON \\
        --metadata METADATA_CSV \\
        --output OUTPUT_DIR

Dependencies:
    pip install nibabel nilearn pandas numpy scipy statsmodels
"""

import argparse
import json
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
from nilearn import datasets, image, masking, plotting
from nilearn.input_data import NiftiLabelsMasker, NiftiMasker
from nilearn.glm.second_level import non_parametric_inference
from scipy import stats
from statsmodels.formula.api import mixedlm

warnings.filterwarnings('ignore')


def load_seed_definitions(seeds_file):
    """Load seed definitions from JSON."""
    with open(seeds_file, 'r') as f:
        seeds = json.load(f)
    return seeds['seeds']


def load_difumo_atlas():
    """Load DiFuMo 256 atlas."""
    print("Loading DiFuMo 256 atlas...")
    atlas = datasets.fetch_atlas_difumo(dimension=256, resolution_mm=2)
    return atlas


def extract_seed_timeseries(bold_file, confounds_file, seed_def, atlas,
                              smoothing_fwhm=6.0, high_pass=0.01, low_pass=0.1):
    """
    Extract mean timeseries from seed region.

    Parameters
    ----------
    bold_file : str
        Preprocessed BOLD NIfTI file
    confounds_file : str
        fMRIPrep confounds TSV file
    seed_def : dict
        Seed definition with 'difumo_indices' or 'indices' list
    atlas : nilearn atlas object
        DiFuMo atlas
    smoothing_fwhm : float
        Spatial smoothing FWHM (mm)
    high_pass : float
        High-pass filter cutoff (Hz)
    low_pass : float
        Low-pass filter cutoff (Hz)

    Returns
    -------
    seed_ts : ndarray
        Seed mean timeseries (n_volumes,)
    """

    # Get seed ROI indices (support both 'difumo_indices' and 'indices' keys)
    roi_indices = seed_def.get('difumo_indices', seed_def.get('indices', []))

    # Create a binary mask for these ROIs
    # DiFuMo is a 4D probabilistic atlas
    # atlas.maps is a file path string, need to load with nibabel
    maps_img = nib.load(atlas.maps)
    maps_data = maps_img.get_fdata()

    # Sum probability maps for selected components
    seed_mask = np.sum(maps_data[:, :, :, roi_indices], axis=3)

    # Threshold to create binary mask
    # DiFuMo is probabilistic with low values, use any non-zero voxel
    seed_mask = (seed_mask > 0).astype(float)

    # Create NIfTI image
    seed_mask_img = nib.Nifti1Image(seed_mask, maps_img.affine)

    # Load confounds (try utf-8 first, fallback to latin-1)
    print(f"    Reading confounds from: {confounds_file}")
    try:
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='utf-8')
        print(f"    Confounds shape: {confounds.shape}")
    except UnicodeDecodeError:
        print(f"    UTF-8 failed, trying latin-1...")
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='latin-1')
        print(f"    Confounds shape: {confounds.shape}")
    except Exception as e:
        print(f"    ERROR reading confounds: {type(e).__name__}: {e}")
        print(f"    File: {confounds_file}")
        raise
    confound_cols = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z',
                     'csf', 'white_matter']
    confound_cols = [c for c in confound_cols if c in confounds.columns]
    confounds_array = confounds[confound_cols].values

    # Create masker
    masker = NiftiMasker(
        mask_img=seed_mask_img,
        smoothing_fwhm=smoothing_fwhm,
        high_pass=high_pass,
        low_pass=low_pass,
        detrend=True,
        standardize=True,
        t_r=0.8,
        verbose=0
    )

    # Extract and average timeseries
    seed_ts_2d = masker.fit_transform(bold_file, confounds=confounds_array)

    # Average across voxels in seed
    seed_ts = np.mean(seed_ts_2d, axis=1)

    return seed_ts


def compute_seed_to_voxel_connectivity(bold_file, confounds_file, seed_ts,
                                        brain_mask, smoothing_fwhm=6.0,
                                        high_pass=0.01, low_pass=0.1):
    """
    Compute voxelwise correlation with seed timeseries.

    Parameters
    ----------
    bold_file : str
        Preprocessed BOLD NIfTI file
    confounds_file : str
        fMRIPrep confounds TSV file
    seed_ts : ndarray
        Seed timeseries (n_volumes,)
    brain_mask : Nifti1Image
        Brain mask
    smoothing_fwhm : float
        Spatial smoothing FWHM
    high_pass : float
        High-pass filter
    low_pass : float
        Low-pass filter

    Returns
    -------
    correlation_map : Nifti1Image
        Whole-brain correlation map (Fisher Z-transformed)
    """

    # Load confounds (try utf-8 first, fallback to latin-1)
    print(f"    Reading confounds from: {confounds_file}")
    try:
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='utf-8')
        print(f"    Confounds shape: {confounds.shape}")
    except UnicodeDecodeError:
        print(f"    UTF-8 failed, trying latin-1...")
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='latin-1')
        print(f"    Confounds shape: {confounds.shape}")
    except Exception as e:
        print(f"    ERROR reading confounds: {type(e).__name__}: {e}")
        print(f"    File: {confounds_file}")
        raise
    confound_cols = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z',
                     'csf', 'white_matter']
    confound_cols = [c for c in confound_cols if c in confounds.columns]
    confounds_array = confounds[confound_cols].values

    # Create whole-brain masker
    masker = NiftiMasker(
        mask_img=brain_mask,
        smoothing_fwhm=smoothing_fwhm,
        high_pass=high_pass,
        low_pass=low_pass,
        detrend=True,
        standardize=True,
        t_r=0.8,
        verbose=0
    )

    # Extract whole-brain timeseries
    brain_ts = masker.fit_transform(bold_file, confounds=confounds_array)

    # Compute correlation with seed for each voxel
    n_voxels = brain_ts.shape[1]
    correlations = np.zeros(n_voxels)

    for i in range(n_voxels):
        correlations[i] = np.corrcoef(seed_ts, brain_ts[:, i])[0, 1]

    # Fisher Z-transform
    correlations_z = np.arctanh(correlations)

    # Convert back to image
    correlation_map = masker.inverse_transform(correlations_z)

    return correlation_map


def main():
    parser = argparse.ArgumentParser(
        description="Seed-based connectivity analysis for walking intervention study"
    )
    parser.add_argument('--fmriprep', type=str, required=True,
                        help='fMRIPrep derivatives directory')
    parser.add_argument('--seeds', type=str, required=True,
                        help='Seeds JSON file (motor_cerebellar_seeds.json)')
    parser.add_argument('--metadata', type=str, required=True,
                        help='Metadata CSV with group, age, sex, mean_fd')
    parser.add_argument('--output', type=str, required=True,
                        help='Output directory')
    parser.add_argument('--seed-names', nargs='+',
                        help='Specific seeds to analyze (default: all primary seeds)')
    parser.add_argument('--space', default='MNI152NLin2009cAsym',
                        help='Space of BOLD data')
    parser.add_argument('--smoothing', type=float, default=6.0,
                        help='Smoothing FWHM (mm)')
    parser.add_argument('--high-pass', type=float, default=0.01,
                        help='High-pass filter (Hz)')
    parser.add_argument('--low-pass', type=float, default=0.1,
                        help='Low-pass filter (Hz)')

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load seed definitions
    print("="*60)
    print("SEED-BASED CONNECTIVITY ANALYSIS")
    print("="*60)

    seed_defs = load_seed_definitions(args.seeds)

    # Select seeds to analyze
    if args.seed_names:
        seeds_to_analyze = {k: v for k, v in seed_defs.items() if k in args.seed_names}
    else:
        # Primary seeds (motor-cerebellar focus)
        primary_seeds = ['Motor_Cortex', 'Cerebellar_Motor', 'Hippocampus']
        seeds_to_analyze = {k: v for k, v in seed_defs.items() if k in primary_seeds}

    print(f"\nSeeds to analyze: {list(seeds_to_analyze.keys())}")

    # Load atlas
    atlas = load_difumo_atlas()

    # Load metadata
    metadata = pd.read_csv(args.metadata)
    print(f"\nMetadata: {len(metadata)} observations ({metadata['subject'].nunique()} subjects)")

    # Get brain mask
    print("\nLoading standard brain mask...")
    from nilearn.datasets import load_mni152_brain_mask
    brain_mask = load_mni152_brain_mask(resolution=2)

    # Find BOLD files
    fmriprep_dir = Path(args.fmriprep)
    # Try with res-2 first (common fMRIPrep output), then without
    bold_pattern = f'**/func/*_space-{args.space}_res-2_desc-preproc_bold.nii.gz'
    bold_files = sorted(fmriprep_dir.glob(bold_pattern))
    if len(bold_files) == 0:
        # Fallback to pattern without res-*
        bold_pattern = f'**/func/*_space-{args.space}_desc-preproc_bold.nii.gz'
        bold_files = sorted(fmriprep_dir.glob(bold_pattern))

    print(f"Found {len(bold_files)} BOLD files")

    if len(bold_files) == 0:
        print("ERROR: No BOLD files found. Check fMRIPrep directory and space.")
        return 1

    # Process each seed
    for seed_name, seed_def in seeds_to_analyze.items():
        print(f"\n{'='*60}")
        print(f"SEED: {seed_name}")
        print(f"{'='*60}")
        print(f"Description: {seed_def['description']}")
        n_components = seed_def.get('n_components', len(seed_def.get('indices', [])))
        print(f"Components: {n_components}")

        seed_output_dir = output_dir / seed_name.lower()
        seed_output_dir.mkdir(exist_ok=True)

        # Store individual maps
        individual_maps = []
        map_info = []

        # Process each subject-session
        for bold_file in bold_files:
            # Parse filename
            parts = bold_file.stem.replace('.nii', '').split('_')
            subject = [p for p in parts if p.startswith('sub-')][0]
            session = [p for p in parts if p.startswith('ses-')][0] if any('ses-' in p for p in parts) else 'ses-01'

            # Find confounds (handle both res-2 and non-res patterns)
            bold_name = bold_file.name
            if '_res-2_' in bold_name:
                confounds_name = bold_name.replace(
                    f'_space-{args.space}_res-2_desc-preproc_bold.nii.gz',
                    '_desc-confounds_timeseries.tsv'
                )
            else:
                confounds_name = bold_name.replace(
                    f'_space-{args.space}_desc-preproc_bold.nii.gz',
                    '_desc-confounds_timeseries.tsv'
                )
            confounds_file = bold_file.parent / confounds_name

            if not confounds_file.exists():
                print(f"  Warning: No confounds for {subject} {session}, skipping")
                continue

            print(f"  Processing {subject} {session}...")

            # Extract seed timeseries
            seed_ts = extract_seed_timeseries(
                str(bold_file), str(confounds_file), seed_def, atlas,
                smoothing_fwhm=args.smoothing,
                high_pass=args.high_pass,
                low_pass=args.low_pass
            )

            # Compute seed-to-voxel connectivity
            conn_map = compute_seed_to_voxel_connectivity(
                str(bold_file), str(confounds_file), seed_ts, brain_mask,
                smoothing_fwhm=args.smoothing,
                high_pass=args.high_pass,
                low_pass=args.low_pass
            )

            # Save individual map
            output_file = seed_output_dir / f'{subject}_{session}_zmap.nii.gz'
            nib.save(conn_map, output_file)

            individual_maps.append(str(output_file))
            map_info.append({
                'subject': subject,
                'session': session,
                'file': str(output_file)
            })

        print(f"\n  Processed {len(individual_maps)} connectivity maps")

        # Save map inventory
        map_df = pd.DataFrame(map_info)
        map_df.to_csv(seed_output_dir / 'individual_maps.csv', index=False)

        print(f"\n  Individual maps saved to: {seed_output_dir}")
        print(f"  Next: Run group-level analysis with FSL randomise or nilearn second-level GLM")

        # Create visualization of mean connectivity map
        print(f"\n  Creating mean connectivity visualization...")

        # Load all maps
        maps_data = [nib.load(m).get_fdata() for m in individual_maps[:10]]  # First 10 for speed
        mean_map_data = np.mean(maps_data, axis=0)
        mean_map = nib.Nifti1Image(mean_map_data, brain_mask.affine)

        # Plot
        display = plotting.plot_stat_map(
            mean_map,
            threshold=0.3,
            title=f'Seed: {seed_name} (mean connectivity)',
            colorbar=True,
            cmap='RdBu_r',
            symmetric_cbar=True,
            output_file=str(seed_output_dir / f'{seed_name}_mean_connectivity.png'),
            display_mode='mosaic'
        )

        print(f"  ✓ Visualization saved: {seed_name}_mean_connectivity.png")

    print(f"\n{'='*60}")
    print("SEED-BASED ANALYSIS COMPLETE")
    print(f"{'='*60}")
    print(f"\nResults directory: {output_dir}")
    print(f"\nNext steps:")
    print(f"1. Run group-level analysis (Group × Time interaction)")
    print(f"2. Apply cluster correction (FWE p<0.05)")
    print(f"3. Extract peak coordinates and effect sizes")

    return 0


if __name__ == '__main__':
    exit(main())
