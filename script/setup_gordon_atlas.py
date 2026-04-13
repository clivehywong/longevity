#!/usr/bin/env python3
"""
Download and prepare Gordon 333 parcel atlas for nilearn.
Reference: Gordon et al. (2016) Cerebral Cortex
"""

import urllib.request
import numpy as np
from pathlib import Path
from nilearn import image
import nibabel as nib


def download_gordon_atlas(output_dir=None):
    """
    Download Gordon 333 parcel atlas.

    The Gordon atlas is a functional parcellation based on resting-state fMRI
    with 333 parcels covering cortical and subcortical regions.
    """

    if output_dir is None:
        output_dir = Path.home() / 'nilearn_data' / 'gordon_2016'
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Gordon atlas URLs (MNI space, 2mm)
    urls = {
        'atlas': 'https://github.com/ThomasYeoLab/CBIG/raw/master/stable_projects/brain_parcellation/Kong2019_MSHBM/lib/group_priors/Parcellations/Parcels_MNI/Gordon/Gordon333_MNI_2mm.nii.gz',
        'labels': 'https://github.com/ThomasYeoLab/CBIG/raw/master/stable_projects/brain_parcellation/Kong2019_MSHBM/lib/group_priors/Parcellations/Parcels_MNI/Gordon/Gordon333_MNI_LUT.txt',
    }

    files = {}

    print("Downloading Gordon 333 atlas...")

    # Download atlas image
    atlas_file = output_dir / 'Gordon333_MNI_2mm.nii.gz'
    if not atlas_file.exists():
        try:
            print(f"  Downloading atlas image...")
            urllib.request.urlretrieve(urls['atlas'], atlas_file)
            print(f"  Saved to: {atlas_file}")
        except Exception as e:
            print(f"  Error downloading from GitHub: {e}")
            print("\n  Please manually download Gordon atlas:")
            print("  1. Visit: https://sites.wustl.edu/petersenschlaggarlab/resources/")
            print("  2. Download 'Gordon333_MNI_2mm.nii.gz'")
            print(f"  3. Save to: {atlas_file}")
            return None

    files['maps'] = str(atlas_file)

    # Download labels
    labels_file = output_dir / 'Gordon333_labels.txt'
    if not labels_file.exists():
        try:
            print(f"  Downloading labels...")
            urllib.request.urlretrieve(urls['labels'], labels_file)
        except:
            # Create default labels if download fails
            print("  Creating default labels...")
            labels = [f"Gordon_{i:03d}" for i in range(1, 334)]
            with open(labels_file, 'w') as f:
                for i, label in enumerate(labels, 1):
                    f.write(f"{i}\t{label}\n")

    # Load labels
    labels = []
    with open(labels_file, 'r') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                labels.append(parts[1])
            else:
                labels.append(parts[0])

    files['labels'] = labels[:333]  # Ensure exactly 333 labels

    print(f"\nGordon atlas setup complete!")
    print(f"  Atlas: {files['maps']}")
    print(f"  Labels: {len(files['labels'])}")

    return files


def load_gordon_atlas():
    """Load Gordon atlas for use with extract_timeseries.py"""

    atlas_dir = Path.home() / 'nilearn_data' / 'gordon_2016'
    atlas_file = atlas_dir / 'Gordon333_MNI_2mm.nii.gz'

    if not atlas_file.exists():
        print("Gordon atlas not found. Downloading...")
        result = download_gordon_atlas()
        if result is None:
            raise FileNotFoundError("Failed to download Gordon atlas")

    # Create atlas object compatible with nilearn
    class GordonAtlas:
        def __init__(self):
            self.maps = str(atlas_file)
            labels_file = atlas_dir / 'Gordon333_labels.txt'
            self.labels = []
            with open(labels_file, 'r') as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) >= 2:
                        self.labels.append(parts[1])
                    else:
                        self.labels.append(parts[0])
            self.labels = self.labels[:333]

    return GordonAtlas()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Download Gordon 333 parcel atlas')
    parser.add_argument('--output-dir', help='Output directory (default: ~/nilearn_data/gordon_2016)')
    args = parser.parse_args()

    download_gordon_atlas(args.output_dir)
