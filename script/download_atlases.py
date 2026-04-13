#!/usr/bin/env python3
"""
Download atlases for CONN connectivity analysis.

Downloads and prepares the following atlases in CONN-compatible format:
- Schaefer 400 ROIs (Yeo 7-networks)
- Schaefer 200 ROIs (Yeo 7-networks)
- DiFuMo 256 components

Output: NIfTI files + label text files in /Volumes/Work/Work/long/atlases/
"""

import os
import numpy as np
from nilearn import datasets
import nibabel as nib

# Output directory
ATLAS_DIR = '/Volumes/Work/Work/long/atlases'
os.makedirs(ATLAS_DIR, exist_ok=True)

def save_labels(labels, output_path):
    """Save ROI labels to text file (CONN format: one label per line)."""
    with open(output_path, 'w') as f:
        for label in labels:
            f.write(f"{label}\n")
    print(f"  Labels saved: {output_path}")

def download_schaefer(n_rois, networks=7):
    """Download Schaefer atlas and save in CONN format."""
    print(f"\nDownloading Schaefer {n_rois} ({networks} networks)...")

    atlas = datasets.fetch_atlas_schaefer_2018(
        n_rois=n_rois,
        yeo_networks=networks,
        resolution_mm=2,
        data_dir=ATLAS_DIR
    )

    # Output names
    suffix = f"schaefer{n_rois}_{networks}net"
    nii_out = os.path.join(ATLAS_DIR, f"{suffix}.nii")
    labels_out = os.path.join(ATLAS_DIR, f"{suffix}.txt")

    # Load and convert to integer labels
    img = nib.load(atlas.maps)
    data = img.get_fdata()

    # Convert to int16 (CONN compatible)
    data_int = data.astype(np.int16)

    # Create new image with integer type
    img_int = nib.Nifti1Image(data_int, img.affine, img.header)
    img_int.header.set_data_dtype(np.int16)
    nib.save(img_int, nii_out)
    print(f"  Atlas saved: {nii_out}")
    print(f"  Labels: {len(np.unique(data_int)) - 1} ROIs (excluding background)")

    # Save labels (clean up network prefixes for readability)
    labels = [label.decode() if isinstance(label, bytes) else label
              for label in atlas.labels]
    # Remove '7Networks_' or '17Networks_' prefix if present
    labels = [l.replace(f'{networks}Networks_', '') for l in labels]
    save_labels(labels, labels_out)

    return nii_out, labels_out

def download_difumo(n_components):
    """Download DiFuMo atlas and save in CONN format."""
    print(f"\nDownloading DiFuMo {n_components}...")

    atlas = datasets.fetch_atlas_difumo(
        dimension=n_components,
        resolution_mm=2,
        data_dir=ATLAS_DIR
    )

    # Output names
    suffix = f"difumo{n_components}"
    nii_out = os.path.join(ATLAS_DIR, f"{suffix}.nii")
    nii_4d_out = os.path.join(ATLAS_DIR, f"{suffix}_4D.nii")
    labels_out = os.path.join(ATLAS_DIR, f"{suffix}.txt")

    # DiFuMo provides probabilistic maps (4D)
    # Load the 4D probabilistic atlas
    img = nib.load(atlas.maps)
    data = img.get_fdata()

    print(f"  Converting 4D probabilistic maps to 3D label volume...")
    print(f"  Input shape: {data.shape}")
    print(f"  Data range: {data.min():.6f} to {data.max():.6f}")

    # OPTION 1: Save 4D probabilistic maps (CONN can use these directly)
    nib.save(img, nii_4d_out)
    print(f"  4D probabilistic maps saved: {nii_4d_out}")

    # OPTION 2: Create hard parcellation (3D integer labels)
    # DiFuMo values are very small (~0.002 max), so use minimal threshold
    threshold = 0.0001  # Very low threshold
    max_prob = np.max(data, axis=3)
    label_data = np.argmax(data, axis=3) + 1  # 1-indexed labels
    label_data[max_prob < threshold] = 0  # Background

    n_labels = len(np.unique(label_data)) - 1
    n_assigned = np.sum(label_data > 0)
    pct_assigned = 100 * n_assigned / label_data.size

    print(f"  Unique labels: {n_labels} (excluding background)")
    print(f"  Voxels assigned: {n_assigned} / {label_data.size} ({pct_assigned:.1f}%)")

    # Save as integer labels
    label_img = nib.Nifti1Image(label_data.astype(np.int16), img.affine, img.header)
    label_img.header.set_data_dtype(np.int16)
    nib.save(label_img, nii_out)
    print(f"  3D label atlas saved: {nii_out}")

    # Save labels
    labels = atlas.labels
    save_labels(labels, labels_out)

    print(f"\n  NOTE: DiFuMo works best with 4D probabilistic maps in CONN")
    print(f"        Use {nii_4d_out} in CONN batch script")

    return nii_4d_out, labels_out  # Return 4D version

def main():
    print("=" * 60)
    print("CONN Atlas Downloader")
    print("=" * 60)
    print(f"Output directory: {ATLAS_DIR}")

    # Download all atlases
    atlases = {}

    # Schaefer 400 (7 networks) - PRIMARY
    atlases['schaefer400_7net'] = download_schaefer(400, 7)

    # Schaefer 200 (7 networks)
    atlases['schaefer200_7net'] = download_schaefer(200, 7)

    # DiFuMo 256
    atlases['difumo256'] = download_difumo(256)

    print("\n" + "=" * 60)
    print("Download complete!")
    print("=" * 60)
    print("\nAtlas files created:")
    for name, (nii, labels) in atlases.items():
        print(f"  {name}:")
        print(f"    NIfTI:  {nii}")
        print(f"    Labels: {labels}")

    print("\nFor CONN batch script, use these paths in Setup.rois.files")

if __name__ == '__main__':
    main()
