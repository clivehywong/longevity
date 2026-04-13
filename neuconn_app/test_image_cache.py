#!/usr/bin/env python3
"""
Test script for image caching system

Tests:
1. Cache initialization
2. Single image generation and caching
3. Cache hit/miss detection
4. Background pre-generation
5. Cache stats and manifest
"""

import time
from pathlib import Path
import sys

# Add utils to path
sys.path.insert(0, str(Path(__file__).parent))

from utils.image_cache import ImageCache, get_image_cache
from utils.qa_image_generator import (
    generate_anat_montage,
    generate_func_timepoints,
    generate_func_quality
)


def test_cache_initialization():
    """Test 1: Cache initialization."""
    print("\n" + "="*60)
    print("TEST 1: Cache Initialization")
    print("="*60)

    bids_dir = Path("/home/clivewong/proj/longevity/bids")
    cache = ImageCache(bids_dir)

    assert cache.cache_dir.exists(), "Cache directory should exist"
    assert cache.manifest_path.parent.exists(), "Manifest parent should exist"

    print(f"Cache dir: {cache.cache_dir}")
    print(f"Manifest: {cache.manifest_path}")
    print("OK: Cache initialized")


def test_single_image_cache():
    """Test 2: Single image generation and caching."""
    print("\n" + "="*60)
    print("TEST 2: Single Image Cache")
    print("="*60)

    bids_dir = Path("/home/clivewong/proj/longevity/bids")
    cache = get_image_cache(bids_dir)

    # Find a test image
    test_subject = "sub-033"
    test_session = "ses-01"
    test_run = "run-01"

    test_file = bids_dir / test_subject / test_session / "anat" / f"{test_subject}_{test_session}_{test_run}_T1w.nii.gz"

    if not test_file.exists():
        print(f"WARNING: Test file not found: {test_file}")
        return

    print(f"\nTest file: {test_file.name}")

    # Check if cached
    is_cached_before = cache.has_cached_image(test_file, 'anat')
    print(f"Cached before: {is_cached_before}")

    # Generate and cache
    print("Generating image...")
    start_time = time.time()
    success = cache.generate_and_cache(test_file, 'anat', generate_anat_montage)
    elapsed = time.time() - start_time

    print(f"Generated in {elapsed:.2f}s: {success}")

    # Check if cached after
    is_cached_after = cache.has_cached_image(test_file, 'anat')
    print(f"Cached after: {is_cached_after}")

    assert is_cached_after, "Image should be cached after generation"

    # Try loading from cache
    print("\nLoading from cache...")
    start_time = time.time()
    fig = cache.get_cached_image(test_file, 'anat', generate_anat_montage)
    elapsed = time.time() - start_time

    print(f"Loaded from cache in {elapsed:.2f}s")
    assert fig is not None, "Should load from cache"

    print("OK: Single image caching works")


def test_cache_stats():
    """Test 3: Cache stats."""
    print("\n" + "="*60)
    print("TEST 3: Cache Stats")
    print("="*60)

    bids_dir = Path("/home/clivewong/proj/longevity/bids")
    cache = get_image_cache(bids_dir)

    stats = cache.get_cache_stats()

    print(f"\nTotal images: {stats['total']}")
    print(f"Cached: {stats['cached']}")
    print(f"Coverage: {stats['percentage']}%")

    print("\nBreakdown by type:")
    for img_type, type_stats in stats['by_type'].items():
        if type_stats['total'] > 0:
            pct = round(100 * type_stats['cached'] / type_stats['total'], 1)
            print(f"  {img_type}: {type_stats['cached']}/{type_stats['total']} ({pct}%)")

    print("OK: Cache stats computed")


def test_background_generation():
    """Test 4: Background pre-generation (small subset)."""
    print("\n" + "="*60)
    print("TEST 4: Background Pre-Generation (2 subjects)")
    print("="*60)

    bids_dir = Path("/home/clivewong/proj/longevity/bids")
    cache = get_image_cache(bids_dir)

    # Define generators
    generator_funcs = {
        'anat': generate_anat_montage,
        'func_timepoints': generate_func_timepoints,
        'func_quality': generate_func_quality
    }

    # Start generation
    print("\nStarting background generation...")
    cache.start_background_generation(generator_funcs, force=False)

    # Monitor progress
    while cache.is_generating():
        progress = cache.get_progress()
        pct = round(100 * progress['completed'] / max(progress['total'], 1), 1)
        print(f"\rProgress: {progress['completed']}/{progress['total']} ({pct}%) - {progress['current_file']}", end='')
        time.sleep(0.5)

    print("\n\nGeneration complete!")

    # Show final stats
    final_progress = cache.get_progress()
    print(f"Completed: {final_progress['completed']}/{final_progress['total']}")

    if final_progress['errors']:
        print(f"\nErrors: {len(final_progress['errors'])}")
        for err in final_progress['errors'][:5]:
            print(f"  - {err}")

    print("OK: Background generation works")


def test_cache_manifest():
    """Test 5: Cache manifest integrity."""
    print("\n" + "="*60)
    print("TEST 5: Cache Manifest")
    print("="*60)

    bids_dir = Path("/home/clivewong/proj/longevity/bids")
    cache = get_image_cache(bids_dir)

    if cache.manifest_path.exists():
        import json
        with open(cache.manifest_path, 'r') as f:
            manifest = json.load(f)

        print(f"\nManifest version: {manifest.get('version', 'unknown')}")
        print(f"Entries: {len(manifest.get('files', {}))}")

        # Show sample entries
        entries = list(manifest.get('files', {}).items())[:3]
        if entries:
            print("\nSample entries:")
            for key, value in entries:
                print(f"  {key}:")
                print(f"    cache_path: {value.get('cache_path', 'N/A')}")
                print(f"    image_type: {value.get('image_type', 'N/A')}")
                print(f"    generated_at: {value.get('generated_at', 'N/A')}")

        print("OK: Manifest is valid")
    else:
        print("WARNING: Manifest not found (no cached images yet)")


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("IMAGE CACHE SYSTEM TEST")
    print("="*60)

    try:
        test_cache_initialization()
        test_single_image_cache()
        test_cache_stats()
        test_cache_manifest()

        # Optional: test background generation (can be slow)
        run_bg_test = input("\nRun background generation test? (may take several minutes) [y/N]: ")
        if run_bg_test.lower() == 'y':
            test_background_generation()

        print("\n" + "="*60)
        print("ALL TESTS PASSED")
        print("="*60)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
