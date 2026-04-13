#!/usr/bin/env python3
"""
Seed Region Visualization Script

Generates PNG visualizations of seed masks overlaid on MNI template for all seeds
defined in the seed definition JSON file.

Usage:
    python visualize_seeds.py \
        --seeds atlases/motor_cerebellar_seeds.json \
        --output atlases/seed_visualizations/

    # Specific seeds only
    python visualize_seeds.py \
        --seeds atlases/motor_cerebellar_seeds.json \
        --output atlases/seed_visualizations/ \
        --seed-names DLPFC_L DLPFC_R

Dependencies:
    pip install nibabel nilearn matplotlib numpy
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from nilearn import datasets, plotting


def load_seed_definitions(seeds_file):
    """Load seed definitions from JSON file."""
    with open(seeds_file, 'r') as f:
        data = json.load(f)
    return data.get('seeds', {})


def load_difumo_atlas():
    """Load DiFuMo 256 atlas and return image data and affine."""
    print("Loading DiFuMo 256 atlas...")
    atlas = datasets.fetch_atlas_difumo(dimension=256, resolution_mm=2)
    maps_img = nib.load(atlas.maps)
    maps_data = maps_img.get_fdata()
    maps_affine = maps_img.affine
    print(f"  Atlas shape: {maps_data.shape}")
    return maps_data, maps_affine


def create_seed_mask(seed_def, maps_data, maps_affine, default_threshold=0.0002):
    """
    Create binary seed mask from DiFuMo atlas components.

    Parameters
    ----------
    seed_def : dict
        Seed definition with 'difumo_indices' and optional 'probability_threshold'
    maps_data : ndarray
        4D atlas probability maps (x, y, z, n_components)
    maps_affine : ndarray
        Affine transformation matrix
    default_threshold : float
        Default probability threshold if not specified in seed_def (default: 0.0002 for DiFuMo atlas)

    Returns
    -------
    seed_mask_img : Nifti1Image
        Binary seed mask with probability threshold applied
    n_voxels : int
        Number of non-zero voxels in mask
    """
    roi_indices = seed_def['difumo_indices']

    # Get probability threshold from seed definition or use default
    prob_threshold = seed_def.get('probability_threshold', default_threshold)

    # Sum probability maps for selected components
    seed_mask = np.sum(maps_data[:, :, :, roi_indices], axis=3)

    # Apply probability threshold (eliminates spillover)
    seed_mask = (seed_mask >= prob_threshold).astype(float)

    n_voxels = int(np.sum(seed_mask > 0))

    return nib.Nifti1Image(seed_mask, maps_affine), n_voxels


def get_mask_center_of_mass(mask_img):
    """Get center of mass coordinates in MNI space."""
    data = mask_img.get_fdata()
    affine = mask_img.affine

    # Get indices of non-zero voxels
    coords = np.where(data > 0)
    if len(coords[0]) == 0:
        return None

    # Compute center of mass in voxel space
    com_voxel = [np.mean(c) for c in coords]

    # Convert to MNI coordinates
    com_mni = nib.affines.apply_affine(affine, com_voxel)
    return tuple(np.round(com_mni, 1))


def get_lateralization_info(mask_img):
    """
    Check lateralization of mask (left vs right hemisphere voxels).

    In MNI space, X < 0 is left hemisphere, X > 0 is right hemisphere.
    """
    data = mask_img.get_fdata()
    affine = mask_img.affine

    coords = np.where(data > 0)
    if len(coords[0]) == 0:
        return {'left': 0, 'right': 0, 'midline': 0, 'dominant': 'none'}

    # Convert voxel coordinates to MNI
    x_coords = []
    for i in range(len(coords[0])):
        voxel = [coords[0][i], coords[1][i], coords[2][i]]
        mni = nib.affines.apply_affine(affine, voxel)
        x_coords.append(mni[0])

    x_coords = np.array(x_coords)

    left = int(np.sum(x_coords < -2))    # X < -2 (left hemisphere)
    right = int(np.sum(x_coords > 2))    # X > 2 (right hemisphere)
    midline = int(np.sum(np.abs(x_coords) <= 2))  # -2 <= X <= 2 (midline)

    total = left + right + midline
    if left > right * 1.5:
        dominant = 'left'
    elif right > left * 1.5:
        dominant = 'right'
    else:
        dominant = 'bilateral'

    return {
        'left': left,
        'right': right,
        'midline': midline,
        'left_pct': round(100 * left / total, 1) if total > 0 else 0,
        'right_pct': round(100 * right / total, 1) if total > 0 else 0,
        'dominant': dominant
    }


def visualize_seed(seed_name, seed_def, seed_mask_img, output_dir, n_voxels, mni_template):
    """
    Generate visualization images for a seed region.

    Generates:
    - Orthogonal view (axial/coronal/sagittal cuts)
    - Glass brain view (shows lateralization clearly)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get center of mass for display position
    com = get_mask_center_of_mass(seed_mask_img)
    lat_info = get_lateralization_info(seed_mask_img)

    # Build title with metadata
    deprecated = seed_def.get('deprecated', False)
    title_suffix = " [DEPRECATED]" if deprecated else ""
    description = seed_def.get('description', '')[:60]

    # Orthogonal view
    fig_ortho = plt.figure(figsize=(12, 4))

    display = plotting.plot_roi(
        seed_mask_img,
        bg_img=mni_template,
        title=f'{seed_name}{title_suffix}\n{description}',
        display_mode='ortho',
        cut_coords=com if com else None,
        cmap='Reds',
        alpha=0.7,
        annotate=True,
        draw_cross=True,
        figure=fig_ortho
    )

    # Add voxel count annotation
    fig_ortho.text(0.02, 0.02, f'Voxels: {n_voxels} | Laterality: {lat_info["dominant"]} (L:{lat_info["left_pct"]}% R:{lat_info["right_pct"]}%)',
                   fontsize=9, transform=fig_ortho.transFigure)

    ortho_path = output_dir / f'{seed_name}_ortho.png'
    fig_ortho.savefig(ortho_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig_ortho)

    # Glass brain view (better for lateralization)
    fig_glass = plt.figure(figsize=(12, 4))

    display = plotting.plot_glass_brain(
        seed_mask_img,
        title=f'{seed_name}{title_suffix}',
        display_mode='lyrz',
        colorbar=False,
        cmap='Reds',
        alpha=0.8,
        figure=fig_glass
    )

    fig_glass.text(0.02, 0.02, f'Voxels: {n_voxels} | L: {lat_info["left"]} | R: {lat_info["right"]} | Midline: {lat_info["midline"]}',
                   fontsize=9, transform=fig_glass.transFigure)

    glass_path = output_dir / f'{seed_name}_glass.png'
    fig_glass.savefig(glass_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig_glass)

    return {
        'seed': seed_name,
        'n_voxels': n_voxels,
        'center_of_mass': com,
        'lateralization': lat_info,
        'ortho_path': str(ortho_path),
        'glass_path': str(glass_path),
        'deprecated': deprecated
    }


def save_seed_mask(seed_name, seed_mask_img, output_dir):
    """Save the seed mask as NIfTI file."""
    output_dir = Path(output_dir)
    mask_path = output_dir / f'{seed_name}_mask.nii.gz'
    nib.save(seed_mask_img, mask_path)
    return str(mask_path)


def main():
    parser = argparse.ArgumentParser(
        description='Generate PNG visualizations of seed masks on MNI template'
    )
    parser.add_argument('--seeds', required=True,
                        help='Path to seed definitions JSON file')
    parser.add_argument('--output', required=True,
                        help='Output directory for visualizations')
    parser.add_argument('--seed-names', nargs='+', default=None,
                        help='Specific seeds to visualize (default: all)')
    parser.add_argument('--save-masks', action='store_true',
                        help='Also save seed masks as NIfTI files')
    parser.add_argument('--skip-deprecated', action='store_true',
                        help='Skip seeds marked as deprecated')

    args = parser.parse_args()

    # Load seed definitions
    seeds_file = Path(args.seeds)
    if not seeds_file.exists():
        print(f"Error: Seeds file not found: {seeds_file}")
        sys.exit(1)

    seeds = load_seed_definitions(seeds_file)
    print(f"Loaded {len(seeds)} seed definitions from {seeds_file}")

    # Filter seeds if specific names provided
    if args.seed_names:
        seeds = {k: v for k, v in seeds.items() if k in args.seed_names}
        print(f"Filtering to {len(seeds)} specified seeds")

        # Check for missing seeds
        missing = set(args.seed_names) - set(seeds.keys())
        if missing:
            print(f"Warning: Seeds not found: {missing}")

    if args.skip_deprecated:
        original_count = len(seeds)
        seeds = {k: v for k, v in seeds.items() if not v.get('deprecated', False)}
        skipped = original_count - len(seeds)
        if skipped > 0:
            print(f"Skipping {skipped} deprecated seeds")

    if len(seeds) == 0:
        print("No seeds to visualize!")
        sys.exit(1)

    # Load atlas
    maps_data, maps_affine = load_difumo_atlas()

    # Load MNI template
    print("Loading MNI152 template...")
    mni_template = datasets.load_mni152_template(resolution=2)

    # Create output directory
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process each seed
    results = []
    for seed_name, seed_def in seeds.items():
        print(f"\nProcessing: {seed_name}")

        if 'difumo_indices' not in seed_def:
            print(f"  Warning: No difumo_indices, skipping")
            continue

        # Create mask
        seed_mask_img, n_voxels = create_seed_mask(seed_def, maps_data, maps_affine)
        print(f"  Voxels: {n_voxels}")

        if n_voxels == 0:
            print(f"  Warning: Empty mask!")
            continue

        # Generate visualizations
        result = visualize_seed(seed_name, seed_def, seed_mask_img, output_dir,
                               n_voxels, mni_template)

        # Optionally save mask
        if args.save_masks:
            mask_path = save_seed_mask(seed_name, seed_mask_img, output_dir)
            result['mask_path'] = mask_path
            print(f"  Saved mask: {mask_path}")

        results.append(result)
        print(f"  Saved: {result['ortho_path']}")
        print(f"  Saved: {result['glass_path']}")

    # Save summary
    summary_path = output_dir / 'visualization_summary.json'
    with open(summary_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSummary saved: {summary_path}")

    # Print summary table
    print("\n" + "="*80)
    print("SEED VISUALIZATION SUMMARY")
    print("="*80)
    print(f"{'Seed':<35} {'Voxels':>8} {'Laterality':>12} {'Status':<12}")
    print("-"*80)
    for r in results:
        status = 'DEPRECATED' if r['deprecated'] else 'OK'
        print(f"{r['seed']:<35} {r['n_voxels']:>8} {r['lateralization']['dominant']:>12} {status:<12}")
    print("="*80)
    print(f"Total seeds visualized: {len(results)}")
    print(f"Output directory: {output_dir}")


if __name__ == '__main__':
    main()
