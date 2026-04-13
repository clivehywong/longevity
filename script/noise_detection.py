#!/usr/bin/env python3
"""
Advanced noise and artifact detection for neuroimaging data.

Detects:
- Pure noise images (no anatomical signal)
- Artifacts and quality issues
- Image quality classification

Criteria for noise detection:
1. SNR < threshold
2. Uniform histogram (high entropy)
3. Low edge detection response
4. High coefficient of variation

Usage:
    python noise_detection.py --bids bids/ --output noise_detection.csv
"""

import os
import sys
import csv
import json
import argparse
import numpy as np
import nibabel as nib
from pathlib import Path
from datetime import datetime


def compute_snr_simple(data):
    """
    Compute simple SNR estimate.

    Uses corner voxels as background noise estimate.

    Args:
        data: 3D numpy array

    Returns:
        float: SNR value
    """
    # Get corner regions for noise estimate
    corner_size = max(5, min(data.shape) // 10)
    corners = []

    for x in [slice(0, corner_size), slice(-corner_size, None)]:
        for y in [slice(0, corner_size), slice(-corner_size, None)]:
            for z in [slice(0, corner_size), slice(-corner_size, None)]:
                corners.append(data[x, y, z].flatten())

    background = np.concatenate(corners)
    noise_std = np.std(background)

    # Signal is the non-background region
    threshold = np.percentile(data, 10)
    signal_region = data[data > threshold]

    if len(signal_region) == 0 or noise_std == 0:
        return 0.0

    signal_mean = np.mean(signal_region)
    return float(signal_mean / noise_std)


def compute_histogram_entropy(data):
    """
    Compute histogram entropy.

    Noise images have high entropy (uniform distribution).
    Anatomical images have lower entropy (distinct peaks).

    Args:
        data: 3D numpy array

    Returns:
        float: Histogram entropy in bits
    """
    # Normalize to 0-1 range
    data_min, data_max = np.min(data), np.max(data)
    if data_max - data_min < 1e-10:
        return 0.0  # Constant image

    data_norm = (data - data_min) / (data_max - data_min)

    # Compute histogram
    hist, _ = np.histogram(data_norm.flatten(), bins=256, density=True)
    hist = hist[hist > 0]  # Remove zeros for log

    if len(hist) == 0:
        return 0.0

    # Shannon entropy
    entropy = -np.sum(hist * np.log2(hist + 1e-10))

    return float(entropy)


def compute_edge_strength(data):
    """
    Compute edge strength using gradient magnitude.

    Anatomical images have strong edges.
    Noise images have weak, uniform gradients.

    Args:
        data: 3D numpy array

    Returns:
        float: Mean edge strength (gradient magnitude)
    """
    # Compute gradients along each axis
    gx = np.diff(data, axis=0)
    gy = np.diff(data, axis=1)
    gz = np.diff(data, axis=2)

    # Mean absolute gradient
    edge_strength = np.mean(np.abs(gx)) + np.mean(np.abs(gy)) + np.mean(np.abs(gz))

    # Normalize by data range
    data_range = np.max(data) - np.min(data)
    if data_range > 0:
        edge_strength = edge_strength / data_range * 100

    return float(edge_strength)


def compute_foreground_fraction(data):
    """
    Compute fraction of voxels above background threshold.

    Args:
        data: 3D numpy array

    Returns:
        float: Fraction of foreground voxels (0-1)
    """
    # Otsu-like threshold estimation
    threshold = np.percentile(data, 10) + np.std(data)
    foreground = data > threshold
    return float(np.sum(foreground) / data.size)


def compute_coefficient_of_variation(data):
    """
    Compute coefficient of variation.

    CV = std / mean

    Args:
        data: 3D numpy array

    Returns:
        float: Coefficient of variation
    """
    mean_val = np.mean(data)
    if abs(mean_val) < 1e-10:
        return float('inf')

    return float(np.std(data) / abs(mean_val))


def detect_noise_only_image(nifti_path, snr_threshold=5.0, entropy_threshold=7.5,
                            edge_threshold=10.0, cv_threshold=2.0):
    """
    Multi-criteria noise detection.

    Criteria:
    1. SNR < snr_threshold
    2. High histogram entropy (> entropy_threshold)
    3. Low edge strength (< edge_threshold)
    4. High coefficient of variation (> cv_threshold)

    Args:
        nifti_path: Path to NIfTI file
        snr_threshold: SNR threshold
        entropy_threshold: Entropy threshold
        edge_threshold: Edge strength threshold
        cv_threshold: CV threshold

    Returns:
        dict: Detection results with metrics and classification
    """
    try:
        img = nib.load(str(nifti_path))
        data = img.get_fdata()

        # Handle 4D data
        if len(data.shape) == 4:
            data = np.mean(data, axis=3)

        # Compute all metrics
        snr = compute_snr_simple(data)
        entropy = compute_histogram_entropy(data)
        edge_strength = compute_edge_strength(data)
        cv = compute_coefficient_of_variation(data)
        fg_fraction = compute_foreground_fraction(data)

        # Collect reasons for noise classification
        reasons = []
        noise_score = 0

        if snr < snr_threshold:
            reasons.append(f'Low SNR: {snr:.2f} < {snr_threshold}')
            noise_score += 0.4

        if entropy > entropy_threshold:
            reasons.append(f'High entropy: {entropy:.2f} > {entropy_threshold}')
            noise_score += 0.2

        if edge_strength < edge_threshold:
            reasons.append(f'Low edge strength: {edge_strength:.2f} < {edge_threshold}')
            noise_score += 0.2

        if cv > cv_threshold:
            reasons.append(f'High CV: {cv:.2f} > {cv_threshold}')
            noise_score += 0.1

        if fg_fraction < 0.1:
            reasons.append(f'Low foreground fraction: {fg_fraction:.2f}')
            noise_score += 0.1

        # Determine if noise
        is_noise = noise_score >= 0.5
        confidence = min(1.0, noise_score)

        return {
            'is_noise': is_noise,
            'confidence': float(confidence),
            'noise_score': float(noise_score),
            'metrics': {
                'snr': float(snr),
                'histogram_entropy': float(entropy),
                'edge_strength': float(edge_strength),
                'coefficient_of_variation': float(cv),
                'foreground_fraction': float(fg_fraction)
            },
            'reasons': reasons,
            'error': None
        }

    except Exception as e:
        return {
            'is_noise': False,
            'confidence': 0.0,
            'noise_score': 0.0,
            'metrics': {},
            'reasons': [],
            'error': str(e)
        }


def classify_image_quality(nifti_path, modality='unknown'):
    """
    Classify image quality as: excellent/good/marginal/poor/noise.

    Args:
        nifti_path: Path to NIfTI file
        modality: Image modality for modality-specific thresholds

    Returns:
        dict: Quality classification
    """
    # Get noise detection results
    detection = detect_noise_only_image(nifti_path)

    if detection['error']:
        return {
            'quality': 'error',
            'reason': detection['error']
        }

    if detection['is_noise']:
        return {
            'quality': 'noise',
            'confidence': detection['confidence'],
            'reasons': detection['reasons']
        }

    metrics = detection['metrics']
    snr = metrics.get('snr', 0)
    edge_strength = metrics.get('edge_strength', 0)

    # Quality classification based on SNR
    # Thresholds vary by modality
    if modality in ['T1w', 'T2w']:
        snr_thresholds = {'excellent': 25, 'good': 15, 'marginal': 8, 'poor': 5}
    else:
        snr_thresholds = {'excellent': 20, 'good': 12, 'marginal': 6, 'poor': 3}

    if snr >= snr_thresholds['excellent']:
        quality = 'excellent'
    elif snr >= snr_thresholds['good']:
        quality = 'good'
    elif snr >= snr_thresholds['marginal']:
        quality = 'marginal'
    elif snr >= snr_thresholds['poor']:
        quality = 'poor'
    else:
        quality = 'very_poor'

    return {
        'quality': quality,
        'snr': snr,
        'metrics': metrics
    }


def classify_modality_from_path(filepath):
    """Classify modality from filepath."""
    filename = os.path.basename(filepath).lower()

    if 't1w' in filename:
        return 'T1w'
    elif 't2w' in filename:
        return 'T2w'
    elif 'bold' in filename:
        return 'func'
    elif 'dwi' in filename:
        return 'dwi'
    else:
        return 'unknown'


def process_bids_for_noise(bids_dir, output_path, modalities=None):
    """
    Process BIDS directory for noise detection.

    Args:
        bids_dir: Path to BIDS directory
        output_path: Path to output CSV file
        modalities: List of modalities to check (default: T1w, T2w)
    """
    bids_path = Path(bids_dir)

    if modalities is None:
        modalities = ['T1w', 'T2w']

    print("=" * 60)
    print("Noise Detection")
    print("=" * 60)
    print(f"BIDS directory: {bids_dir}")
    print(f"Target modalities: {modalities}\n")

    # Find relevant files
    nifti_files = []
    for f in bids_path.rglob("*.nii.gz"):
        mod = classify_modality_from_path(str(f))
        if mod in modalities:
            nifti_files.append((f, mod))
    for f in bids_path.rglob("*.nii"):
        mod = classify_modality_from_path(str(f))
        if mod in modalities:
            nifti_files.append((f, mod))

    print(f"Found {len(nifti_files)} files to check\n")

    results = []
    noise_flagged = []

    for i, (nifti_file, modality) in enumerate(nifti_files, 1):
        rel_path = str(nifti_file.relative_to(bids_path))
        print(f"[{i}/{len(nifti_files)}] {rel_path}")

        detection = detect_noise_only_image(nifti_file)
        quality = classify_image_quality(nifti_file, modality)

        result = {
            'file': rel_path,
            'modality': modality,
            'is_noise': detection['is_noise'],
            'noise_confidence': detection['confidence'],
            'quality': quality.get('quality', 'error'),
            'snr': detection['metrics'].get('snr', 0),
            'entropy': detection['metrics'].get('histogram_entropy', 0),
            'edge_strength': detection['metrics'].get('edge_strength', 0),
            'cv': detection['metrics'].get('coefficient_of_variation', 0),
            'fg_fraction': detection['metrics'].get('foreground_fraction', 0),
            'reasons': '; '.join(detection['reasons']),
            'error': detection['error'] or ''
        }

        results.append(result)

        if detection['is_noise']:
            noise_flagged.append(result)
            print(f"  NOISE DETECTED (confidence={detection['confidence']:.2f})")
            for reason in detection['reasons']:
                print(f"    - {reason}")
        else:
            print(f"  Quality: {quality.get('quality', 'unknown')} (SNR={detection['metrics'].get('snr', 0):.2f})")

    # Write CSV output
    with open(output_path, 'w', newline='') as f:
        fieldnames = ['file', 'modality', 'is_noise', 'noise_confidence', 'quality',
                     'snr', 'entropy', 'edge_strength', 'cv', 'fg_fraction',
                     'reasons', 'error']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResults saved to: {output_path}")

    # Summary
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Total files checked: {len(results)}")
    print(f"  Noise-flagged: {len(noise_flagged)}")

    # Quality distribution
    quality_counts = {}
    for r in results:
        q = r['quality']
        quality_counts[q] = quality_counts.get(q, 0) + 1

    print("\n  Quality distribution:")
    for q, count in sorted(quality_counts.items()):
        print(f"    {q}: {count}")

    print("=" * 60)

    if noise_flagged:
        print("\nNOISE-FLAGGED IMAGES:")
        for item in noise_flagged:
            print(f"  {item['file']}")
            print(f"    SNR={item['snr']:.2f}, Confidence={item['noise_confidence']:.2f}")

    # Save JSON with full details
    json_path = str(output_path).replace('.csv', '.json')
    with open(json_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'bids_dir': str(bids_dir),
            'results': results,
            'noise_flagged': noise_flagged,
            'summary': {
                'total': len(results),
                'noise_count': len(noise_flagged),
                'quality_distribution': quality_counts
            }
        }, f, indent=2)
    print(f"\nJSON details saved to: {json_path}")

    return results, noise_flagged


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Advanced noise and artifact detection for neuroimaging data.'
    )
    parser.add_argument('--bids', required=True,
                        help='Path to BIDS directory')
    parser.add_argument('--output', required=True,
                        help='Path to output CSV file')
    parser.add_argument('--modalities', nargs='+', default=['T1w', 'T2w'],
                        help='Modalities to check (default: T1w T2w)')
    parser.add_argument('--snr-threshold', type=float, default=5.0,
                        help='SNR threshold for noise detection (default: 5.0)')

    args = parser.parse_args()

    if not os.path.exists(args.bids):
        print(f"Error: BIDS directory not found: {args.bids}")
        sys.exit(1)

    results, noise_flagged = process_bids_for_noise(
        args.bids,
        args.output,
        args.modalities
    )

    sys.exit(1 if noise_flagged else 0)
