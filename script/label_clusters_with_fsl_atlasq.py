#!/usr/bin/env python3
"""
Label cluster centers with anatomical regions using FSL atlasq.

This script takes a CSV file with cluster coordinates (x, y, z in MNI space)
and queries FSL atlasq to obtain anatomical region labels and confidence scores
from multiple atlases. It produces an annotated CSV with region information.

Usage:
    python script/label_clusters_with_fsl_atlasq.py \\
        --cluster-table results/group_analysis/clusters.csv \\
        --output results/group_analysis/clusters_annotated.csv \\
        --atlases Talairach AAL3v1 harvardoxford-cortical

Example input CSV:
    x,y,z,t_stat,p_value,n_voxels
    -37,-22,58,3.2,0.001,145
    12,45,30,2.8,0.002,120

Example output CSV (with additional columns):
    x,y,z,t_stat,p_value,n_voxels,region_talairach,confidence_talairach,region_aal3v1,confidence_aal3v1,...
    -37,-22,58,3.2,0.001,145,Precentral Gyrus,0.43,Precentral_L,1.0,...
"""

import os
import sys
import csv
import json
import logging
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import pandas as pd


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def check_atlasq_available() -> bool:
    """
    Check if FSL atlasq is available in the system.

    Returns:
        True if atlasq is available, False otherwise
    """
    try:
        result = subprocess.run(
            ['atlasq', 'list'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def list_available_atlases() -> List[str]:
    """
    Query FSL atlasq to list available atlases.

    Returns:
        List of atlas IDs available in the system
    """
    try:
        result = subprocess.run(
            ['atlasq', 'list'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            logger.warning(f"Failed to list atlases: {result.stderr}")
            return []

        atlases = []
        for line in result.stdout.split('\n'):
            # Skip header lines and empty lines
            if not line.strip() or '|' not in line:
                continue
            if 'ID' in line or '-' * 5 in line:
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 2:
                atlas_id = parts[0].strip()
                if atlas_id and atlas_id != '-':
                    atlases.append(atlas_id)
        return atlases
    except Exception as e:
        logger.error(f"Error listing atlases: {e}")
        return []


def validate_atlases(atlas_names: List[str]) -> Tuple[List[str], List[str]]:
    """
    Validate that requested atlases are available.

    Args:
        atlas_names: List of atlas names to validate

    Returns:
        Tuple of (valid_atlases, invalid_atlases)
    """
    available = list_available_atlases()
    valid = []
    invalid = []

    for atlas in atlas_names:
        if atlas in available:
            valid.append(atlas)
        else:
            invalid.append(atlas)
            logger.warning(f"Atlas '{atlas}' not found in available atlases")

    return valid, invalid


def query_atlasq(
    x: float,
    y: float,
    z: float,
    atlas: str,
    resolution: int = 2
) -> Optional[Dict]:
    """
    Query FSL atlasq for a single coordinate in a specific atlas.

    Args:
        x, y, z: MNI coordinates
        atlas: Atlas ID to query
        resolution: Atlas resolution in mm (default 2mm)

    Returns:
        Dictionary with 'region', 'index', 'proportion' if successful,
        None if query fails
    """
    try:
        cmd = [
            'atlasq', 'query', atlas,
            '-c', str(x), str(y), str(z),
            '--resolution', str(resolution),
            '--short'
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            logger.debug(f"atlasq query failed for ({x}, {y}, {z}) in {atlas}")
            return None

        # Parse short format output: coordinate\t[coords]\t[region info]
        output = result.stdout.strip()
        if not output:
            return None

        # Split by tabs - format is: coordinate\t<x y z>\t<region hierarchy>
        parts = output.split('\t')
        if len(parts) < 3:
            return None

        region_str = parts[2].strip()
        if not region_str:
            return None

        # For short format, we get the full hierarchy
        # Try to extract primary region name (typically first meaningful part)
        # Remove leading "coordinate" if present
        if region_str.startswith('coordinate'):
            region_str = region_str[len('coordinate'):].strip()

        # Parse hierarchical structure (e.g., "Left Cerebrum.Frontal Lobe.Precentral Gyrus...")
        # Take the primary region (last dot-separated component before Gray/White Matter)
        hierarchy_parts = region_str.split('.')
        primary_region = None

        # Look for meaningful region names (skip anatomical markers)
        for i in range(len(hierarchy_parts) - 1, -1, -1):
            part = hierarchy_parts[i].strip()
            if part and not part.startswith('Brodmann'):
                if 'Gray Matter' not in part and 'White Matter' not in part:
                    primary_region = part
                    break

        if not primary_region:
            primary_region = region_str

        return {
            'region': primary_region,
            'full_hierarchy': region_str,
            'proportion': 100.0  # For label maps, proportion is 100%
        }

    except subprocess.TimeoutExpired:
        logger.warning(f"atlasq query timeout for ({x}, {y}, {z}) in {atlas}")
        return None
    except Exception as e:
        logger.debug(f"Error querying atlasq: {e}")
        return None


def query_atlasq_probabilistic(
    x: float,
    y: float,
    z: float,
    atlas: str,
    resolution: int = 2,
    top_n: int = 1
) -> Optional[List[Dict]]:
    """
    Query FSL atlasq for a probabilistic atlas and get top labels.

    Args:
        x, y, z: MNI coordinates
        atlas: Atlas ID to query
        resolution: Atlas resolution in mm
        top_n: Number of top results to return

    Returns:
        List of dicts with 'region', 'index', 'proportion', or None on failure
    """
    try:
        cmd = [
            'atlasq', 'query', atlas,
            '-c', str(x), str(y), str(z),
            '--resolution', str(resolution)
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            logger.debug(f"atlasq query failed for ({x}, {y}, {z}) in {atlas}")
            return None

        # Parse output which can be either table format or label format
        lines = result.stdout.strip().split('\n')
        results = []

        # Try parsing as table format (probabilistic atlases)
        in_table = False
        for line in lines:
            if not line.strip():
                continue

            # Skip separator lines
            if '---' in line or '|' not in line:
                continue

            # Skip header line
            if 'name' in line and 'index' in line:
                in_table = True
                continue

            if not in_table:
                continue

            # Parse table row
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 4:
                continue

            try:
                region = parts[0].strip()
                index = int(parts[1].strip())
                proportion = float(parts[3].strip())

                results.append({
                    'region': region,
                    'index': index,
                    'proportion': proportion / 100.0  # Convert percentage to proportion
                })
            except (ValueError, IndexError):
                continue

        if results:
            return results[:top_n]

        # Check for label-format output (e.g., AAL3v1). This must happen after
        # table parsing so a probabilistic table header ("name | index | ...")
        # is not mistaken for a label-format result named "index".
        region_name = None
        for line in lines:
            if line.strip().startswith('name'):
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 2 and parts[1].lower() != 'index':
                    region_name = parts[1].strip()
                    break

        if region_name:
            # Label format - single result with 100% confidence
            results.append({
                'region': region_name,
                'index': 1,
                'proportion': 1.0
            })
            return results[:top_n] if results else None

        return results[:top_n] if results else None

    except subprocess.TimeoutExpired:
        logger.warning(f"atlasq query timeout for ({x}, {y}, {z}) in {atlas}")
        return None
    except Exception as e:
        logger.debug(f"Error querying probabilistic atlas: {e}")
        return None


def label_clusters_with_atlasq(
    cluster_csv: str,
    atlases: Optional[List[str]] = None,
    output_csv: Optional[str] = None
) -> pd.DataFrame:
    """
    Label cluster centers using FSL atlasq.

    Args:
        cluster_csv: Path to input CSV with cluster coordinates
        atlases: List of atlas IDs to query. If None, uses defaults.
        output_csv: Path to save annotated CSV. If None, doesn't save.

    Returns:
        DataFrame with annotated cluster information
    """
    if atlases is None:
        atlases = ['talairach', 'aal3v1', 'harvardoxford-cortical']

    # Check if atlasq is available
    if not check_atlasq_available():
        logger.error("FSL atlasq is not available. Please install FSL.")
        logger.error("Continuing with coordinate-only output (no labels)")
        atlases = []

    # Validate requested atlases
    valid_atlases, invalid_atlases = validate_atlases(atlases)
    if invalid_atlases:
        logger.warning(f"Skipping unavailable atlases: {invalid_atlases}")
    atlases = valid_atlases

    # Load input CSV
    logger.info(f"Loading cluster table from {cluster_csv}")
    try:
        df = pd.read_csv(cluster_csv)
    except FileNotFoundError:
        logger.error(f"Cluster CSV not found: {cluster_csv}")
        raise
    except Exception as e:
        logger.error(f"Error reading cluster CSV: {e}")
        raise

    # Validate required columns
    required_cols = ['x', 'y', 'z']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        logger.error(f"Missing required columns: {missing_cols}")
        raise ValueError(f"CSV must contain columns: {required_cols}")

    logger.info(f"Found {len(df)} clusters to label")

    # Query each cluster for each atlas
    for atlas in atlases:
        region_col = f'region_{atlas}'
        confidence_col = f'confidence_{atlas}'
        hierarchy_col = f'hierarchy_{atlas}'

        logger.info(f"Querying {atlas} atlas for all clusters...")

        regions = []
        confidences = []
        hierarchies = []

        for idx, row in df.iterrows():
            x, y, z = row['x'], row['y'], row['z']

            # Try probabilistic atlas first
            result = query_atlasq_probabilistic(x, y, z, atlas)

            if result:
                # Take the top result
                top_result = result[0]
                regions.append(top_result['region'])
                confidences.append(top_result['proportion'])
                hierarchies.append(top_result['region'])
            else:
                # Fallback to label atlas
                result = query_atlasq(x, y, z, atlas)
                if result:
                    regions.append(result['region'])
                    confidences.append(result['proportion'] / 100.0)
                    hierarchies.append(result.get('full_hierarchy', result['region']))
                else:
                    regions.append('Unknown')
                    confidences.append(0.0)
                    hierarchies.append('Query failed')

            if (idx + 1) % 5 == 0:
                logger.info(f"  Labeled {idx + 1}/{len(df)} clusters")

        df[region_col] = regions
        df[confidence_col] = confidences
        df[hierarchy_col] = hierarchies
        logger.info(f"  {atlas}: Complete")

    # Save output if requested
    if output_csv:
        output_dir = os.path.dirname(output_csv)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        logger.info(f"Saving annotated clusters to {output_csv}")
        df.to_csv(output_csv, index=False)
        logger.info("Complete")

    return df


def main():
    """Command-line interface for cluster labeling."""
    parser = argparse.ArgumentParser(
        description='Label cluster centers using FSL atlasq',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Label clusters with default atlases
  python label_clusters_with_fsl_atlasq.py \\
    --cluster-table clusters.csv \\
    --output clusters_annotated.csv

  # Specify custom atlases
  python label_clusters_with_fsl_atlasq.py \\
    --cluster-table clusters.csv \\
    --output clusters_annotated.csv \\
    --atlases talairach aal3v1 harvardoxford-cortical

  # Just query, don't save
  python label_clusters_with_fsl_atlasq.py \\
    --cluster-table clusters.csv \\
    --atlases talairach
        """
    )

    parser.add_argument(
        '--cluster-table',
        help='Input CSV file with cluster coordinates (x, y, z columns required)'
    )
    parser.add_argument(
        '--output',
        help='Output CSV file with anatomical labels added'
    )
    parser.add_argument(
        '--atlases',
        nargs='+',
        default=['talairach', 'aal3v1', 'harvardoxford-cortical'],
        help='Atlas IDs to query (default: talairach aal3v1 harvardoxford-cortical)'
    )
    parser.add_argument(
        '--list-atlases',
        action='store_true',
        help='List available atlases and exit'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # List available atlases if requested
    if args.list_atlases:
        logger.info("Checking available atlases...")
        available = list_available_atlases()
        if available:
            logger.info(f"Found {len(available)} available atlases:")
            for atlas in sorted(available):
                print(f"  - {atlas}")
        else:
            logger.warning("No atlases found or atlasq not available")
        return 0

    # Require cluster-table if not listing atlases
    if not args.cluster_table:
        parser.error("--cluster-table is required (unless --list-atlases is used)")

    # Main workflow
    try:
        df = label_clusters_with_atlasq(
            cluster_csv=args.cluster_table,
            atlases=args.atlases,
            output_csv=args.output
        )
        logger.info(f"Successfully labeled {len(df)} clusters")
        if args.output:
            logger.info(f"Results saved to {args.output}")
        return 0

    except Exception as e:
        logger.error(f"Failed to label clusters: {e}", exc_info=args.verbose)
        return 1


if __name__ == '__main__':
    sys.exit(main())
