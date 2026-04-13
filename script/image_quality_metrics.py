#!/usr/bin/env python3
"""
Compute quantitative image quality metrics for neuroimaging data.

Metrics computed:
- SNR (Signal-to-Noise Ratio) for structural images
- tSNR (temporal SNR) for functional images
- Noise detection flags

Usage:
    python image_quality_metrics.py --bids bids/ --output qc_metrics/
"""

import os
import sys
import json
import argparse
import numpy as np
import nibabel as nib
from pathlib import Path
from datetime import datetime


def get_background_mask(data, percentile=5):
    """
    Create a background mask using corner voxels.

    Args:
        data: 3D numpy array
        percentile: Threshold percentile for background

    Returns:
        Boolean mask where True = background
    """
    # Use corner regions as background estimate
    corner_size = max(5, min(data.shape) // 10)
    corners = []

    # Sample from all 8 corners
    for x in [slice(0, corner_size), slice(-corner_size, None)]:
        for y in [slice(0, corner_size), slice(-corner_size, None)]:
            for z in [slice(0, corner_size), slice(-corner_size, None)]:
                corners.append(data[x, y, z].flatten())

    background_vals = np.concatenate(corners)
    threshold = np.percentile(data, percentile)

    return data <= threshold


def compute_snr(nifti_path):
    """
    Compute SNR using background noise estimation.

    For structural images: SNR = mean(signal) / std(background)

    Args:
        nifti_path: Path to NIfTI file

    Returns:
        dict: SNR value and related metrics
    """
    img = nib.load(str(nifti_path))
    data = img.get_fdata()

    # Handle 4D data by taking mean across time
    if len(data.shape) == 4:
        data = np.mean(data, axis=3)

    # Get background mask
    bg_mask = get_background_mask(data)
    fg_mask = ~bg_mask

    # Compute signal and noise
    if np.sum(fg_mask) == 0 or np.sum(bg_mask) == 0:
        return {'snr': 0, 'error': 'Could not segment foreground/background'}

    signal_mean = np.mean(data[fg_mask])
    noise_std = np.std(data[bg_mask])

    if noise_std == 0:
        snr = float('inf') if signal_mean > 0 else 0
    else:
        snr = signal_mean / noise_std

    return {
        'snr': float(snr),
        'signal_mean': float(signal_mean),
        'noise_std': float(noise_std),
        'foreground_voxels': int(np.sum(fg_mask)),
        'background_voxels': int(np.sum(bg_mask))
    }


def detect_pure_noise(nifti_path, snr_threshold=5.0):
    """
    Detect pure noise images (no anatomical signal).

    Criteria:
    - SNR < threshold
    - High histogram entropy
    - Low edge strength

    Args:
        nifti_path: Path to NIfTI file
        snr_threshold: SNR below which image is flagged

    Returns:
        dict: Detection results
    """
    img = nib.load(str(nifti_path))
    data = img.get_fdata()

    # Handle 4D data
    if len(data.shape) == 4:
        data = np.mean(data, axis=3)

    # Compute SNR
    snr_result = compute_snr(nifti_path)
    snr = snr_result.get('snr', 0)

    # Compute histogram entropy (noise has high entropy)
    hist, _ = np.histogram(data.flatten(), bins=256, density=True)
    hist = hist[hist > 0]  # Remove zeros for log
    entropy = -np.sum(hist * np.log2(hist))

    # Compute edge strength using simple gradient magnitude
    edge_strength = compute_edge_strength_simple(data)

    # Determine if pure noise
    is_noise = snr < snr_threshold
    confidence = 1.0 - min(snr / snr_threshold, 1.0)

    reasons = []
    if snr < snr_threshold:
        reasons.append(f'Low SNR: {snr:.2f} < {snr_threshold}')
    if entropy > 7.5:  # High entropy indicates noise-like distribution
        reasons.append(f'High histogram entropy: {entropy:.2f}')
        confidence = min(1.0, confidence + 0.2)
    if edge_strength < 50:  # Low edge strength
        reasons.append(f'Low edge strength: {edge_strength:.2f}')
        confidence = min(1.0, confidence + 0.2)

    return {
        'is_noise': is_noise,
        'confidence': float(confidence),
        'snr': float(snr),
        'histogram_entropy': float(entropy),
        'edge_strength': float(edge_strength),
        'reasons': reasons
    }


def compute_edge_strength_simple(data):
    """
    Compute edge strength using simple gradient magnitude.

    Args:
        data: 3D numpy array

    Returns:
        float: Mean edge strength
    """
    # Simple gradient computation (Sobel-like)
    gx = np.abs(np.diff(data, axis=0))
    gy = np.abs(np.diff(data, axis=1))
    gz = np.abs(np.diff(data, axis=2))

    # Mean gradient magnitude
    edge_strength = np.mean(gx) + np.mean(gy) + np.mean(gz)

    return float(edge_strength)


def compute_temporal_snr(func_path):
    """
    Compute tSNR for functional data.

    tSNR = mean / std across time

    Args:
        func_path: Path to 4D functional NIfTI file

    Returns:
        dict: tSNR metrics
    """
    img = nib.load(str(func_path))
    data = img.get_fdata()

    if len(data.shape) != 4:
        return {'error': 'Not a 4D file', 'tsnr_mean': 0}

    # Compute temporal mean and std
    with np.errstate(divide='ignore', invalid='ignore'):
        temporal_mean = np.mean(data, axis=3)
        temporal_std = np.std(data, axis=3)
        tsnr_map = np.where(temporal_std > 0, temporal_mean / temporal_std, 0)

    # Create brain mask (voxels with signal)
    brain_mask = temporal_mean > np.percentile(temporal_mean, 20)

    if np.sum(brain_mask) == 0:
        return {'error': 'No signal detected', 'tsnr_mean': 0}

    tsnr_brain = tsnr_map[brain_mask]

    return {
        'tsnr_mean': float(np.mean(tsnr_brain)),
        'tsnr_median': float(np.median(tsnr_brain)),
        'tsnr_std': float(np.std(tsnr_brain)),
        'tsnr_min': float(np.min(tsnr_brain)),
        'tsnr_max': float(np.max(tsnr_brain)),
        'num_volumes': int(data.shape[3]),
        'brain_voxels': int(np.sum(brain_mask))
    }


def classify_modality(filepath):
    """Classify file modality based on filename."""
    filename = os.path.basename(filepath).lower()

    if 't1w' in filename:
        return 'T1w'
    elif 't2w' in filename:
        return 'T2w'
    elif 'bold' in filename or 'func' in str(filepath):
        return 'func'
    elif 'dwi' in filename:
        return 'dwi'
    elif 'fmap' in str(filepath) or 'epi' in filename:
        return 'fmap'
    else:
        return 'unknown'


def process_bids_directory(bids_dir, output_dir, snr_threshold=5.0):
    """
    Process all NIfTI files in a BIDS directory.

    Args:
        bids_dir: Path to BIDS directory
        output_dir: Path to output directory for metrics
        snr_threshold: SNR threshold for noise detection
    """
    bids_path = Path(bids_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Find all NIfTI files
    nifti_files = list(bids_path.rglob("*.nii.gz")) + list(bids_path.rglob("*.nii"))

    print(f"Processing {len(nifti_files)} NIfTI files...")

    all_metrics = {}
    noise_flagged = []

    for i, nifti_file in enumerate(nifti_files, 1):
        rel_path = str(nifti_file.relative_to(bids_path))
        print(f"[{i}/{len(nifti_files)}] {rel_path}")

        try:
            modality = classify_modality(str(nifti_file))
            metrics = {
                'file': rel_path,
                'modality': modality,
                'timestamp': datetime.now().isoformat()
            }

            # Compute SNR for all files
            snr_result = compute_snr(nifti_file)
            metrics['snr'] = snr_result

            # Noise detection for structural images
            if modality in ['T1w', 'T2w']:
                noise_result = detect_pure_noise(nifti_file, snr_threshold)
                metrics['noise_detection'] = noise_result
                if noise_result['is_noise']:
                    noise_flagged.append({
                        'file': rel_path,
                        'snr': noise_result['snr'],
                        'confidence': noise_result['confidence'],
                        'reasons': noise_result['reasons']
                    })

            # tSNR for functional data
            if modality == 'func':
                tsnr_result = compute_temporal_snr(nifti_file)
                metrics['tsnr'] = tsnr_result

            all_metrics[rel_path] = metrics

        except Exception as e:
            print(f"  Error: {e}")
            all_metrics[rel_path] = {
                'file': rel_path,
                'error': str(e)
            }

    # Save all metrics
    metrics_file = output_path / 'quality_metrics.json'
    with open(metrics_file, 'w') as f:
        json.dump(all_metrics, f, indent=2)
    print(f"\nMetrics saved to: {metrics_file}")

    # Save noise-flagged images
    if noise_flagged:
        noise_file = output_path / 'noise_flagged.json'
        with open(noise_file, 'w') as f:
            json.dump(noise_flagged, f, indent=2)
        print(f"Noise-flagged images: {noise_file}")
        print(f"\nWARNING: {len(noise_flagged)} images flagged as potential noise:")
        for item in noise_flagged:
            print(f"  - {item['file']} (SNR={item['snr']:.2f})")

    # Summary statistics
    print("\n" + "="*60)
    print("Summary:")
    print(f"Total files processed: {len(all_metrics)}")
    print(f"Noise-flagged images: {len(noise_flagged)}")

    # Per-modality SNR summary
    by_modality = {}
    for path, m in all_metrics.items():
        if 'error' in m:
            continue
        mod = m.get('modality', 'unknown')
        if mod not in by_modality:
            by_modality[mod] = []
        if 'snr' in m and 'snr' in m['snr']:
            by_modality[mod].append(m['snr']['snr'])

    print("\nSNR by modality:")
    for mod, snrs in by_modality.items():
        if snrs:
            print(f"  {mod}: mean={np.mean(snrs):.2f}, min={np.min(snrs):.2f}, max={np.max(snrs):.2f}")

    return all_metrics, noise_flagged


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Compute image quality metrics for BIDS neuroimaging data.'
    )
    parser.add_argument('--bids', required=True,
                        help='Path to BIDS directory')
    parser.add_argument('--output', required=True,
                        help='Path to output directory for metrics')
    parser.add_argument('--snr-threshold', type=float, default=5.0,
                        help='SNR threshold for noise detection (default: 5.0)')

    args = parser.parse_args()

    if not os.path.exists(args.bids):
        print(f"Error: BIDS directory not found: {args.bids}")
        sys.exit(1)

    metrics, noise_flagged = process_bids_directory(
        args.bids,
        args.output,
        args.snr_threshold
    )

    sys.exit(1 if noise_flagged else 0)
