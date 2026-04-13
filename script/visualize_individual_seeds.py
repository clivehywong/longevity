#!/usr/bin/env python3
"""
Visualize Individual DiFuMo Component Seeds

Creates PNG visualizations of all 43 individual component seeds overlaid on
MNI152 template for visual inspection.

Usage:
    python visualize_individual_seeds.py
"""

import json
import numpy as np
import nibabel as nib
from nilearn import plotting, datasets, image
from pathlib import Path
import matplotlib.pyplot as plt

# Paths
ATLAS_FILE = Path("atlases/individual_component_seeds.json")
DIFUMO_ATLAS = Path("atlases/difumo256_4D.nii")
OUTPUT_DIR = Path("atlases/individual_seed_visualizations")

OUTPUT_DIR.mkdir(exist_ok=True)

print("=" * 80)
print("INDIVIDUAL DIFUMO COMPONENT SEED VISUALIZATIONS")
print("=" * 80)
print(f"Atlas: {DIFUMO_ATLAS}")
print(f"Output: {OUTPUT_DIR}")
print("")

# Load seed definitions
with open(ATLAS_FILE) as f:
    seed_data = json.load(f)

seeds = seed_data['seeds']

# Load MNI template
mni_template = datasets.load_mni152_template(resolution=2)

# Load DiFuMo atlas
difumo_atlas_img = nib.load(DIFUMO_ATLAS)
difumo_data = difumo_atlas_img.get_fdata()

print(f"Processing {len(seeds)} individual component seeds...")
print("")

# Process each seed
for i, (seed_name, seed_info) in enumerate(sorted(seeds.items()), 1):
    print(f"{i:2d}/{len(seeds)}: {seed_name}")

    indices = seed_info['indices']
    description = seed_info['description']
    network = seed_info.get('network', 'Unknown')

    # Create seed mask from DiFuMo components
    seed_mask = np.zeros_like(difumo_data[:, :, :, 0])

    for idx in indices:
        # DiFuMo components are 0-indexed in the 4D atlas
        component_map = difumo_data[:, :, :, idx]
        # Use component map as-is (probabilistic)
        seed_mask = np.maximum(seed_mask, component_map)

    # Create NIfTI image
    seed_img = nib.Nifti1Image(seed_mask, difumo_atlas_img.affine)

    # Create output filename
    output_file = OUTPUT_DIR / f"{seed_name.lower()}_visualization.png"

    # Create visualization
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))

    # Orthogonal view
    display = plotting.plot_stat_map(
        seed_img,
        bg_img=mni_template,
        threshold=0.1,
        cmap='autumn',
        colorbar=True,
        cut_coords=None,
        display_mode='ortho',
        axes=axes[0],
        title=f"{seed_name} - {network}\n{description}"
    )

    # Glass brain view
    display2 = plotting.plot_glass_brain(
        seed_img,
        threshold=0.1,
        cmap='autumn',
        colorbar=True,
        axes=axes[1],
        title=f"Glass brain view"
    )

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"   Saved: {output_file}")
    print(f"   Indices: {indices}")
    print(f"   Network: {network}")
    print("")

# Create summary visualization grid
print("\nCreating network-wise summary grids...")

# Group by network
network_seeds = {}
for seed_name, seed_info in seeds.items():
    network = seed_info.get('network', 'Unknown')
    if network not in network_seeds:
        network_seeds[network] = []
    network_seeds[network].append((seed_name, seed_info))

# Create grid for each network
for network, seed_list in network_seeds.items():
    print(f"\n{network}: {len(seed_list)} seeds")

    n_seeds = len(seed_list)
    n_cols = 5
    n_rows = (n_seeds + n_cols - 1) // n_cols

    fig, axes = plt.subplots(n_rows, n_cols, figsize=(20, 4*n_rows))
    axes = axes.flatten() if n_rows > 1 else [axes]

    for idx, (seed_name, seed_info) in enumerate(sorted(seed_list)):
        indices = seed_info['indices']

        # Create seed mask
        seed_mask = np.zeros_like(difumo_data[:, :, :, 0])
        for comp_idx in indices:
            component_map = difumo_data[:, :, :, comp_idx]
            seed_mask = np.maximum(seed_mask, component_map)

        seed_img = nib.Nifti1Image(seed_mask, difumo_atlas_img.affine)

        # Plot on glass brain
        ax = axes[idx]
        display = plotting.plot_glass_brain(
            seed_img,
            threshold=0.1,
            cmap='autumn',
            colorbar=False,
            axes=ax,
            title=f"{seed_name}\nComp {indices[0]}"
        )

    # Hide unused subplots
    for idx in range(n_seeds, len(axes)):
        axes[idx].axis('off')

    plt.suptitle(f"{network} Network - Individual Component Seeds ({n_seeds} total)",
                 fontsize=16, y=0.995)
    plt.tight_layout()

    grid_file = OUTPUT_DIR / f"{network}_grid.png"
    plt.savefig(grid_file, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"   Saved grid: {grid_file}")

print("\n" + "=" * 80)
print("VISUALIZATION COMPLETE")
print("=" * 80)
print(f"Individual seed images: {len(seeds)}")
print(f"Network grids: {len(network_seeds)}")
print(f"Output directory: {OUTPUT_DIR}")
print("\nView visualizations:")
for network in sorted(network_seeds.keys()):
    grid_file = OUTPUT_DIR / f"{network}_grid.png"
    if grid_file.exists():
        print(f"  {network}: {grid_file}")
