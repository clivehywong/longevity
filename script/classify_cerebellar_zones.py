#!/usr/bin/env python3
"""
Classify cerebellar components into Motor vs Cognitive zones.

Based on established cerebellar functional parcellation:
- Motor zones: Lobules I-VI, VIII (primary motor, sensorimotor)
- Cognitive zones: Crus I, Crus II, Lobule VII (executive, working memory, language)
- Vestibular/Limbic: Lobule IX, X (vestibular, emotion)

References:
- Buckner et al. (2011) J Neurophysiol - Cerebellar functional organization
- Stoodley & Schmahmann (2009) Neuroimage - Functional topography
- King et al. (2019) Nat Rev Neurosci - Cerebellar networks
"""

import json
import pandas as pd
import re


def classify_cerebellar_lobule(component_name):
    """
    Classify cerebellar component into functional zone.

    Returns: ('Motor', 'Cognitive', 'Vestibular', or 'CSF')
    """

    name = component_name.lower()

    # Skip CSF/fluid components
    if 'fluid' in name or 'csf' in name:
        return 'CSF', 'Cerebrospinal fluid'

    # Motor zones (Lobules I-VI, VIII)
    motor_patterns = [
        r'lobule [i]{1,3}\b',  # I, II, III
        r'cerebellum [iv]+\b',  # IV, V, VI
        r'cerebellum viii',  # VIII
    ]

    for pattern in motor_patterns:
        if re.search(pattern, name):
            return 'Motor', 'Primary motor control and sensorimotor coordination'

    # Cognitive zones (Crus I, Crus II, Lobule VII)
    cognitive_patterns = [
        r'crus [i]+',  # Crus I, Crus II
        r'cerebellum vii',  # VII (excluding VIIIb which is motor)
    ]

    for pattern in cognitive_patterns:
        if re.search(pattern, name):
            return 'Cognitive', 'Executive functions, working memory, language'

    # Vestibular/Limbic zones (Lobules IX, X)
    vestibular_patterns = [
        r'cerebellum [ix]+\b',  # IX, X
    ]

    for pattern in vestibular_patterns:
        if re.search(pattern, name):
            return 'Vestibular', 'Vestibular processing and spatial orientation'

    # Default (should not reach here)
    return 'Unknown', 'Unclassified cerebellar region'


def create_cerebellar_classification():
    """Create detailed cerebellar classification with network definitions."""

    # Load DiFuMo network definitions
    network_file = '/Volumes/Work/Work/long/atlases/difumo256_network_definitions.json'

    with open(network_file, 'r') as f:
        difumo = json.load(f)

    # Get cerebellar components
    cerebellar_indices = difumo['special_regions']['cerebellar']

    # Classify each component
    motor_cereb = []
    cognitive_cereb = []
    vestibular_cereb = []
    csf_cereb = []

    cerebellar_details = []

    for idx in cerebellar_indices:
        comp = difumo['components'][idx]
        comp_num = comp['component']
        name = comp['name']

        # Classify
        zone, function = classify_cerebellar_lobule(name)

        # Add to appropriate list
        if zone == 'Motor':
            motor_cereb.append(idx)
        elif zone == 'Cognitive':
            cognitive_cereb.append(idx)
        elif zone == 'Vestibular':
            vestibular_cereb.append(idx)
        elif zone == 'CSF':
            csf_cereb.append(idx)

        # Detailed entry
        cerebellar_details.append({
            'index': idx,
            'component': comp_num,
            'name': name,
            'functional_zone': zone,
            'function_description': function
        })

    print(f"Cerebellar Classification Summary")
    print(f"="*60)
    print(f"Total cerebellar components: {len(cerebellar_indices)}")
    print(f"  Motor zones        : {len(motor_cereb):2d} (Lobules I-VI, VIII)")
    print(f"  Cognitive zones    : {len(cognitive_cereb):2d} (Crus I, Crus II, VII)")
    print(f"  Vestibular zones   : {len(vestibular_cereb):2d} (Lobules IX, X)")
    print(f"  CSF/Fluid          : {len(csf_cereb):2d} (excluded)")

    # Update network definitions
    difumo['special_regions']['cerebellar_motor'] = motor_cereb
    difumo['special_regions']['cerebellar_cognitive'] = cognitive_cereb
    difumo['special_regions']['cerebellar_vestibular'] = vestibular_cereb
    difumo['special_regions']['cerebellar_details'] = cerebellar_details

    # Add to networks dictionary for easy access
    difumo['networks']['Cerebellar_Motor'] = motor_cereb
    difumo['networks']['Cerebellar_Cognitive'] = cognitive_cereb
    difumo['networks']['Cerebellar_Vestibular'] = vestibular_cereb

    # Update network names
    difumo['network_names'] = list(difumo['networks'].keys())

    # Create refined hypothesis-driven pairs
    somatomotor = difumo['networks']['Somatomotor']
    fpcn = difumo['networks']['FrontoParietal']
    dmn = difumo['networks']['DefaultMode']

    refined_pairs = {
        'Motor_Cerebellar_Motor': {
            'description': 'Motor cortex - Motor cerebellum (primary sensorimotor loop)',
            'network_a': 'Somatomotor',
            'network_b': 'Cerebellar_Motor',
            'rois_a': somatomotor,
            'rois_b': motor_cereb,
            'n_connections': len(somatomotor) * len(motor_cereb),
            'hypothesis': 'Walking intervention strengthens sensorimotor integration'
        },
        'Motor_Cerebellar_Cognitive': {
            'description': 'Motor cortex - Cognitive cerebellum (motor learning, planning)',
            'network_a': 'Somatomotor',
            'network_b': 'Cerebellar_Cognitive',
            'rois_a': somatomotor,
            'rois_b': cognitive_cereb,
            'n_connections': len(somatomotor) * len(cognitive_cereb),
            'hypothesis': 'Walking training engages cerebellar learning systems'
        },
        'FPCN_Cerebellar_Cognitive': {
            'description': 'Frontoparietal - Cognitive cerebellum (executive-motor integration)',
            'network_a': 'FrontoParietal',
            'network_b': 'Cerebellar_Cognitive',
            'rois_a': fpcn,
            'rois_b': cognitive_cereb,
            'n_connections': len(fpcn) * len(cognitive_cereb),
            'hypothesis': 'Cognitive control of complex motor sequences'
        },
        'DMN_Cerebellar_Cognitive': {
            'description': 'Default mode - Cognitive cerebellum (internal models, prediction)',
            'network_a': 'DefaultMode',
            'network_b': 'Cerebellar_Cognitive',
            'rois_a': dmn,
            'rois_b': cognitive_cereb,
            'n_connections': len(dmn) * len(cognitive_cereb),
            'hypothesis': 'Cerebellar contributions to predictive processing'
        }
    }

    difumo['hypothesis_driven_pairs_refined'] = refined_pairs

    # Save updated definitions
    output_file = network_file  # Overwrite
    with open(output_file, 'w') as f:
        json.dump(difumo, f, indent=2)

    print(f"\n✓ Updated network definitions saved: {output_file}")

    return difumo, cerebellar_details


def print_cerebellar_details(cerebellar_details):
    """Print detailed cerebellar classification."""

    print(f"\n" + "="*80)
    print(f"Cerebellar Components - Functional Classification")
    print(f"="*80)

    # Group by zone
    zones = {}
    for comp in cerebellar_details:
        zone = comp['functional_zone']
        if zone not in zones:
            zones[zone] = []
        zones[zone].append(comp)

    # Print each zone
    for zone in ['Motor', 'Cognitive', 'Vestibular', 'CSF']:
        if zone not in zones:
            continue

        comps = zones[zone]
        print(f"\n{zone} Zone ({len(comps)} components)")
        print(f"-" * 80)

        for comp in comps:
            print(f"  Component {comp['component']:3d} (idx {comp['index']:3d}): {comp['name']}")

        if comps:
            print(f"  → {comps[0]['function_description']}")


def print_refined_hypotheses(refined_pairs):
    """Print refined hypothesis-driven pairs."""

    print(f"\n" + "="*80)
    print(f"Refined Hypothesis-Driven Network Pairs (Cerebellar Subdivision)")
    print(f"="*80)

    for pair_name, pair_info in refined_pairs.items():
        n_a = len(pair_info['rois_a'])
        n_b = len(pair_info['rois_b'])
        n_conn = pair_info['n_connections']

        print(f"\n{pair_name}")
        print(f"  Networks: {pair_info['network_a']} ({n_a}) <-> {pair_info['network_b']} ({n_b})")
        print(f"  Connections: {n_conn}")
        print(f"  Description: {pair_info['description']}")
        print(f"  Hypothesis: {pair_info['hypothesis']}")


def create_cerebellar_summary_table():
    """Create CSV summary of cerebellar lobules and functions."""

    # Cerebellar functional summary (from literature)
    cerebellar_zones = [
        {
            'Zone': 'Motor',
            'Lobules': 'I, II, III, IV, V, VI, VIII',
            'Primary_Functions': 'Primary motor control, sensorimotor coordination, eye movements',
            'Cortical_Connections': 'Primary motor cortex, premotor cortex, somatosensory cortex',
            'Clinical_Relevance': 'Motor deficits (ataxia, dysmetria), gait impairment',
            'Walking_Study_Relevance': 'PRIMARY - Direct sensorimotor loop for walking coordination'
        },
        {
            'Zone': 'Cognitive',
            'Lobules': 'Crus I, Crus II, VII',
            'Primary_Functions': 'Executive functions, working memory, language, attention',
            'Cortical_Connections': 'Prefrontal cortex, parietal cortex, temporal cortex',
            'Clinical_Relevance': 'Cognitive deficits (planning, attention), cerebellar cognitive affective syndrome',
            'Walking_Study_Relevance': 'SECONDARY - Motor learning, gait planning, dual-task walking'
        },
        {
            'Zone': 'Vestibular',
            'Lobules': 'IX, X',
            'Primary_Functions': 'Vestibular processing, balance, spatial orientation',
            'Cortical_Connections': 'Vestibular nuclei, brainstem',
            'Clinical_Relevance': 'Balance deficits, vertigo, spatial disorientation',
            'Walking_Study_Relevance': 'TERTIARY - Balance control during walking'
        }
    ]

    df = pd.DataFrame(cerebellar_zones)
    output_file = '/Volumes/Work/Work/long/atlases/cerebellar_functional_zones_summary.csv'
    df.to_csv(output_file, index=False)

    print(f"\n✓ Cerebellar functional summary saved: {output_file}")

    return df


if __name__ == '__main__':

    print("="*80)
    print("Cerebellar Functional Zone Classification")
    print("="*80)

    # Classify cerebellar components
    difumo, cerebellar_details = create_cerebellar_classification()

    # Print details
    print_cerebellar_details(cerebellar_details)

    # Print refined hypotheses
    print_refined_hypotheses(difumo['hypothesis_driven_pairs_refined'])

    # Create summary table
    summary_df = create_cerebellar_summary_table()

    print(f"\n" + "="*80)
    print(f"Summary")
    print(f"="*80)
    print(summary_df.to_string(index=False))

    print(f"\n✓ Cerebellar classification complete!")
    print(f"\nUsage in Python:")
    print(f"  import json")
    print(f"  with open('atlases/difumo256_network_definitions.json') as f:")
    print(f"      networks = json.load(f)")
    print(f"  motor_cereb = networks['networks']['Cerebellar_Motor']")
    print(f"  cognitive_cereb = networks['networks']['Cerebellar_Cognitive']")
    print(f"  # Refined hypothesis pairs")
    print(f"  motor_motor = networks['hypothesis_driven_pairs_refined']['Motor_Cerebellar_Motor']")
