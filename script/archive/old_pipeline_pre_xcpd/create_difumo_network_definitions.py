#!/usr/bin/env python3
"""
Create network definitions JSON from DiFuMo atlas labels.

DiFuMo advantages:
- Covers WHOLE BRAIN including cerebellum (critical for motor analyses)
- ICA-based functional parcellation
- Detailed anatomical labels

Usage:
    python create_difumo_network_definitions.py

Output:
    difumo256_network_definitions.json
"""

import json
import pandas as pd
import os
from collections import defaultdict


def load_difumo_labels():
    """Load DiFuMo labels from CSV."""

    label_file = '/Volumes/Work/Work/long/atlases/difumo_atlases/256/labels_256_dictionary.csv'

    if not os.path.exists(label_file):
        print(f"Error: DiFuMo label file not found: {label_file}")
        return None

    print(f"Loading DiFuMo labels: {label_file}")
    df = pd.read_csv(label_file)

    print(f"  Found {len(df)} components")

    return df


def parse_difumo_networks(df):
    """Parse DiFuMo labels and extract network assignments."""

    # Network mapping (Yeo 7 networks)
    network_mapping = {
        'VisCent': 'Visual',  # Visual Central
        'VisPeri': 'Visual',  # Visual Peripheral
        'SomMotA': 'Somatomotor',
        'SomMotB': 'Somatomotor',
        'DorsAttnA': 'DorsalAttention',
        'DorsAttnB': 'DorsalAttention',
        'SalVentAttnA': 'SalienceVentralAttention',
        'SalVentAttnB': 'SalienceVentralAttention',
        'LimbicA': 'Limbic',
        'LimbicB': 'Limbic',
        'ContA': 'FrontoParietal',  # Control = FPCN
        'ContB': 'FrontoParietal',
        'ContC': 'FrontoParietal',
        'DefaultA': 'DefaultMode',
        'DefaultB': 'DefaultMode',
        'DefaultC': 'DefaultMode',
        'No network found': 'Subcortical'  # Includes cerebellum, thalamus, etc.
    }

    # Create component info
    components = []
    networks = defaultdict(list)
    anatomical_regions = defaultdict(list)

    # Special categories
    cerebellar = []
    motor_related = []
    csf_related = []

    for idx, row in df.iterrows():
        comp_num = row['Component']
        name = row['Difumo_names']
        yeo7 = row['Yeo_networks7']

        # Map to consolidated network
        network = network_mapping.get(yeo7, 'Unknown')

        # Identify special regions
        is_cerebellar = 'cerebell' in name.lower()
        is_csf = 'cerebrospinal fluid' in name.lower() or 'ventricle' in name.lower()
        is_motor = any(kw in name.lower() for kw in ['motor', 'precentral', 'postcentral', 'cerebellum'])

        # Tissue type (GM-dominant vs WM-dominant vs CSF)
        gm_pct = row['GM']
        wm_pct = row['WM']
        csf_pct = row['CSF']

        tissue_type = 'GM'
        if csf_pct > 0.35:
            tissue_type = 'CSF'
        elif wm_pct > 0.5:
            tissue_type = 'WM'

        comp_entry = {
            'component': int(comp_num),
            'index': idx,  # 0-based index
            'name': name,
            'yeo_network7': yeo7,
            'network': network,
            'tissue_composition': {
                'GM': float(gm_pct),
                'WM': float(wm_pct),
                'CSF': float(csf_pct),
                'dominant': tissue_type
            },
            'is_cerebellar': is_cerebellar,
            'is_motor_related': is_motor,
            'is_csf': is_csf
        }

        components.append(comp_entry)

        # Add to network dictionary (only GM-dominant components)
        if tissue_type == 'GM':
            networks[network].append(idx)

        # Special collections
        if is_cerebellar:
            cerebellar.append(idx)
        if is_motor and tissue_type == 'GM':
            motor_related.append(idx)
        if is_csf:
            csf_related.append(idx)

        # Extract anatomical region (first part of name)
        region = name.split()[0] if ' ' in name else name
        anatomical_regions[region].append(idx)

    print(f"  Parsed {len(components)} components")
    print(f"  Networks: {len(networks)}")
    print(f"  Cerebellar components: {len(cerebellar)}")
    print(f"  Motor-related components: {len(motor_related)}")

    return {
        'components': components,
        'networks': dict(networks),
        'cerebellar': cerebellar,
        'motor_related': motor_related,
        'csf_related': csf_related,
        'anatomical_regions': dict(anatomical_regions)
    }


def create_hypothesis_driven_pairs(parsed_data):
    """Define hypothesis-driven network pairs for connectivity analysis."""

    networks = parsed_data['networks']
    cerebellar = parsed_data['cerebellar']
    motor_related = parsed_data['motor_related']

    # Get motor network components (cortical somatomotor)
    motor_cortical = networks.get('Somatomotor', [])

    pairs = {
        'Motor_Cerebellar': {
            'description': 'Motor-Cerebellar connectivity (sensorimotor integration, critical for walking)',
            'network_a': 'Somatomotor',
            'network_b': 'Cerebellum',
            'rois_a': motor_cortical,
            'rois_b': cerebellar,
            'n_connections': len(motor_cortical) * len(cerebellar)
        },
        'Motor_Salience': {
            'description': 'Motor-Salience network connectivity (walking intervention effect)',
            'network_a': 'Somatomotor',
            'network_b': 'SalienceVentralAttention',
            'rois_a': motor_cortical,
            'rois_b': networks.get('SalienceVentralAttention', []),
            'n_connections': len(motor_cortical) * len(networks.get('SalienceVentralAttention', []))
        },
        'Salience_FPCN': {
            'description': 'Salience - Frontoparietal network connectivity',
            'network_a': 'SalienceVentralAttention',
            'network_b': 'FrontoParietal',
            'rois_a': networks.get('SalienceVentralAttention', []),
            'rois_b': networks.get('FrontoParietal', []),
            'n_connections': len(networks.get('SalienceVentralAttention', [])) * len(networks.get('FrontoParietal', []))
        },
        'DMN_FPCN': {
            'description': 'Default Mode - Frontoparietal balance',
            'network_a': 'DefaultMode',
            'network_b': 'FrontoParietal',
            'rois_a': networks.get('DefaultMode', []),
            'rois_b': networks.get('FrontoParietal', []),
            'n_connections': len(networks.get('DefaultMode', [])) * len(networks.get('FrontoParietal', []))
        },
        'Cerebellar_FPCN': {
            'description': 'Cerebellar - Frontoparietal connectivity (cognitive-motor integration)',
            'network_a': 'Cerebellum',
            'network_b': 'FrontoParietal',
            'rois_a': cerebellar,
            'rois_b': networks.get('FrontoParietal', []),
            'n_connections': len(cerebellar) * len(networks.get('FrontoParietal', []))
        }
    }

    return pairs


def save_network_definitions(parsed_data, hypothesis_pairs, output_file):
    """Save network definitions to JSON."""

    print(f"\nCreating network definitions...")

    network_defs = {
        'atlas_name': 'difumo256',
        'atlas_type': 'ICA-based functional parcellation',
        'n_components': len(parsed_data['components']),
        'coverage': 'Whole brain including cerebellum, subcortical structures',
        'networks': parsed_data['networks'],
        'network_names': list(parsed_data['networks'].keys()),
        'components': parsed_data['components'],
        'special_regions': {
            'cerebellar': parsed_data['cerebellar'],
            'motor_related': parsed_data['motor_related'],
            'csf_related': parsed_data['csf_related']
        },
        'hypothesis_driven_pairs': hypothesis_pairs
    }

    print(f"Saving network definitions to: {output_file}")
    with open(output_file, 'w') as f:
        json.dump(network_defs, f, indent=2)

    print(f"  Saved {len(parsed_data['components'])} components")
    print(f"  Networks: {', '.join(network_defs['network_names'])}")
    print(f"  Hypothesis-driven pairs: {len(hypothesis_pairs)}")


def print_summary(parsed_data, hypothesis_pairs):
    """Print summary of network definitions."""

    print("\n" + "="*60)
    print("DiFuMo 256 Network Definitions Summary")
    print("="*60)

    print(f"\nAtlas: DiFuMo 256 (ICA-based functional parcellation)")
    print(f"Total Components: {len(parsed_data['components'])}")
    print(f"Coverage: Whole brain + cerebellum + subcortical")

    print(f"\nComponents per network (GM-dominant only):")
    for network in sorted(parsed_data['networks'].keys()):
        n_comp = len(parsed_data['networks'][network])
        print(f"  {network:30s}: {n_comp:3d} components")

    print(f"\nSpecial regions:")
    print(f"  Cerebellar components     : {len(parsed_data['cerebellar']):3d}")
    print(f"  Motor-related components  : {len(parsed_data['motor_related']):3d}")
    print(f"  CSF-related components    : {len(parsed_data['csf_related']):3d}")

    print(f"\nHypothesis-driven network pairs:")
    for pair_name, pair_info in hypothesis_pairs.items():
        n_a = len(pair_info['rois_a'])
        n_b = len(pair_info['rois_b'])
        n_conn = pair_info['n_connections']
        print(f"  {pair_name:20s}: {pair_info['network_a']} ({n_a}) <-> "
              f"{pair_info['network_b']} ({n_b}) = {n_conn} connections")
        print(f"    {pair_info['description']}")

    # List cerebellar components
    print(f"\nCerebellar components (n={len(parsed_data['cerebellar'])}):")
    for idx in parsed_data['cerebellar'][:10]:  # Show first 10
        comp = parsed_data['components'][idx]
        print(f"  Component {comp['component']:3d}: {comp['name']}")
    if len(parsed_data['cerebellar']) > 10:
        print(f"  ... and {len(parsed_data['cerebellar']) - 10} more")


if __name__ == '__main__':

    print("="*60)
    print("Creating DiFuMo 256 Network Definitions")
    print("="*60)

    # Load labels
    df = load_difumo_labels()
    if df is None:
        exit(1)

    # Parse networks
    parsed_data = parse_difumo_networks(df)

    # Create hypothesis-driven pairs
    hypothesis_pairs = create_hypothesis_driven_pairs(parsed_data)

    # Output file
    output_dir = '/Volumes/Work/Work/long/atlases'
    output_file = os.path.join(output_dir, 'difumo256_network_definitions.json')

    # Save
    save_network_definitions(parsed_data, hypothesis_pairs, output_file)

    # Print summary
    print_summary(parsed_data, hypothesis_pairs)

    print(f"\n✓ DiFuMo 256 network definitions created successfully!")
    print(f"\nTo use in Python:")
    print(f"  import json")
    print(f"  with open('{output_file}', 'r') as f:")
    print(f"      networks = json.load(f)")
    print(f"  cerebellar_components = networks['special_regions']['cerebellar']")
    print(f"  motor_components = networks['networks']['Somatomotor']")
