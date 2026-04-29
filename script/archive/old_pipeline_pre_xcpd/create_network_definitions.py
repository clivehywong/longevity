#!/usr/bin/env python3
"""
Create network definitions JSON from Schaefer atlas labels.

This script parses Schaefer parcellation label files and creates a JSON
file mapping ROIs to the 7 Yeo networks, which can be used across all
analysis platforms (MATLAB, Python, Julia).

Usage:
    python create_network_definitions.py /path/to/schaefer400_7net.txt

Output:
    network_definitions.json - Portable network definitions
"""

import json
import sys
import os
import re
from collections import defaultdict


def parse_schaefer_labels(label_file):
    """Parse Schaefer atlas labels and extract network assignments."""

    if not os.path.exists(label_file):
        print(f"Error: Label file not found: {label_file}")
        sys.exit(1)

    print(f"Parsing label file: {label_file}")

    # Read labels
    with open(label_file, 'r') as f:
        labels = [line.strip() for line in f if line.strip()]

    # Determine atlas size from filename
    match = re.search(r'schaefer(\d+)_7net', label_file)
    n_parcels = int(match.group(1)) if match else None

    print(f"  Found {len(labels)} labels")
    if n_parcels:
        print(f"  Expected {n_parcels} parcels (+ background)")

    # Network definitions
    network_mapping = {
        'Vis': 'Visual',
        'SomMot': 'Somatomotor',
        'DorsAttn': 'DorsalAttention',
        'SalVentAttn': 'SalienceVentralAttention',
        'Limbic': 'Limbic',
        'Cont': 'FrontoParietal',  # FPCN
        'Default': 'DefaultMode'    # DMN
    }

    # Parse labels
    roi_info = []
    networks = defaultdict(list)

    for idx, label in enumerate(labels):
        # Skip background (first label)
        if label.lower() == 'background':
            continue

        # Parse label format: "LH_Vis_1" or "LH_DorsAttn_Post_1" or "RH_SomMot_23"
        # Pattern matches: Hemisphere_Network_[Subregion_]Number
        match = re.match(r'([LR]H)_(\w+)_(.+?)_(\d+)$', label)

        # Also try simpler format without subregion: "LH_Vis_1"
        if not match:
            match = re.match(r'([LR]H)_(\w+)_(\d+)$', label)
            if match:
                hemisphere = match.group(1)
                network_abbrev = match.group(2)
                subregion = None
                roi_num = int(match.group(3))
            else:
                # Skip if no match
                print(f"  Warning: Could not parse label: {label}")
                continue
        else:
            hemisphere = match.group(1)
            network_abbrev = match.group(2)
            subregion = match.group(3)
            roi_num = int(match.group(4))

        # Map to full network name
        network_full = network_mapping.get(network_abbrev, 'Unknown')

        # Create ROI entry
        roi_entry = {
            'index': idx,  # 0-based index (matches atlas volume)
            'label': label,
            'hemisphere': hemisphere,
            'network_abbrev': network_abbrev,
            'network': network_full,
            'roi_number': roi_num
        }

        if subregion:
            roi_entry['subregion'] = subregion

        roi_info.append(roi_entry)

        # Add to network dictionary
        networks[network_full].append(idx)

    print(f"  Parsed {len(roi_info)} ROIs across {len(networks)} networks")

    return {
        'atlas_name': os.path.basename(label_file).replace('.txt', ''),
        'n_rois': len(roi_info),
        'networks': dict(networks),  # Convert defaultdict to dict
        'network_names': list(networks.keys()),
        'rois': roi_info,
        'network_mapping': network_mapping
    }


def create_hypothesis_driven_pairs(network_defs):
    """Define hypothesis-driven network pairs for connectivity analysis."""

    networks = network_defs['networks']

    # Define network pairs of interest
    pairs = {
        'Motor_Salience': {
            'description': 'Motor-Salience network connectivity (walking intervention effect)',
            'network_a': 'Somatomotor',
            'network_b': 'SalienceVentralAttention',
            'rois_a': networks.get('Somatomotor', []),
            'rois_b': networks.get('SalienceVentralAttention', [])
        },
        'Salience_FPCN': {
            'description': 'Salience - Frontoparietal network connectivity',
            'network_a': 'SalienceVentralAttention',
            'network_b': 'FrontoParietal',
            'rois_a': networks.get('SalienceVentralAttention', []),
            'rois_b': networks.get('FrontoParietal', [])
        },
        'DMN_FPCN': {
            'description': 'Default Mode - Frontoparietal balance',
            'network_a': 'DefaultMode',
            'network_b': 'FrontoParietal',
            'rois_a': networks.get('DefaultMode', []),
            'rois_b': networks.get('FrontoParietal', [])
        }
    }

    return pairs


def save_network_definitions(network_defs, output_file):
    """Save network definitions to JSON file."""

    print(f"\nSaving network definitions to: {output_file}")

    # Add hypothesis-driven pairs
    network_defs['hypothesis_driven_pairs'] = create_hypothesis_driven_pairs(network_defs)

    # Write JSON with pretty formatting
    with open(output_file, 'w') as f:
        json.dump(network_defs, f, indent=2)

    print(f"  Saved {network_defs['n_rois']} ROIs")
    print(f"  Networks: {', '.join(network_defs['network_names'])}")
    print(f"  Hypothesis-driven pairs: {len(network_defs['hypothesis_driven_pairs'])}")


def print_summary(network_defs):
    """Print summary of network definitions."""

    print("\n" + "="*60)
    print("Network Definitions Summary")
    print("="*60)

    print(f"\nAtlas: {network_defs['atlas_name']}")
    print(f"Total ROIs: {network_defs['n_rois']}")
    print(f"\nROIs per network:")

    for network_name in sorted(network_defs['network_names']):
        n_rois = len(network_defs['networks'][network_name])
        print(f"  {network_name:30s}: {n_rois:3d} ROIs")

    print(f"\nHypothesis-driven network pairs:")
    for pair_name, pair_info in network_defs['hypothesis_driven_pairs'].items():
        n_a = len(pair_info['rois_a'])
        n_b = len(pair_info['rois_b'])
        print(f"  {pair_name:20s}: {pair_info['network_a']} ({n_a} ROIs) <-> "
              f"{pair_info['network_b']} ({n_b} ROIs)")
        print(f"    {pair_info['description']}")


if __name__ == '__main__':

    # Default to Schaefer 400
    if len(sys.argv) < 2:
        label_file = '/Volumes/Work/Work/long/atlases/schaefer400_7net.txt'
        print(f"No label file specified, using default: {label_file}")
    else:
        label_file = sys.argv[1]

    # Parse labels
    network_defs = parse_schaefer_labels(label_file)

    # Output JSON file (same directory as input)
    output_dir = os.path.dirname(label_file) if os.path.dirname(label_file) else '.'
    atlas_name = network_defs['atlas_name']
    output_file = os.path.join(output_dir, f'{atlas_name}_network_definitions.json')

    # Save
    save_network_definitions(network_defs, output_file)

    # Print summary
    print_summary(network_defs)

    print(f"\n✓ Network definitions created successfully!")
    print(f"\nTo use in Python:")
    print(f"  import json")
    print(f"  with open('{output_file}', 'r') as f:")
    print(f"      networks = json.load(f)")
    print(f"  motor_rois = networks['networks']['Somatomotor']")
