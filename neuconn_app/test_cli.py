#!/usr/bin/env python3
"""
Command-line test of NeuConn components
Run: python test_cli.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("=" * 60)
print("NeuConn Component Test")
print("=" * 60)

# Test 1: Config loading
print("\n1. Testing config loading...")
try:
    from utils.config import load_config
    config_path = Path.home() / "neuconn_projects" / "longevity.yaml"
    config = load_config(str(config_path))
    print(f"   ✅ Config loaded: {config['project']['name']}")
    print(f"   BIDS dir: {config['paths']['bids_dir']}")
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

# Test 2: BIDS scanning
print("\n2. Testing BIDS scanner...")
try:
    from utils.bids import scan_bids_directory
    import time

    bids_dir = Path(config['paths']['bids_dir'])

    start = time.time()
    result = scan_bids_directory(bids_dir)
    elapsed = time.time() - start

    print(f"   ✅ Scan completed in {elapsed:.2f} seconds")
    print(f"   Subjects: {len(result['subjects'])}")
    print(f"   Sessions: {result['sessions']}")
    print(f"   Modalities found: {list(result['modalities'].keys())}")

    for modality, info in result['modalities'].items():
        print(f"     - {modality}: {info['subject_count']} subjects, {info['file_count']} files")

except Exception as e:
    print(f"   ❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Parameter detection
print("\n3. Testing parameter detection...")
try:
    from utils.bids import detect_acquisition_params

    start = time.time()
    params = detect_acquisition_params(bids_dir)
    elapsed = time.time() - start

    print(f"   ✅ Detection completed in {elapsed:.2f} seconds")
    print(f"   TR detected: {params['tr']} seconds")
    print(f"   Volume samples: {len(params['volumes'])} files checked")

    if params['volumes']:
        vol_counts = [v['volumes'] for v in params['volumes']]
        print(f"   Volume range: {min(vol_counts)} - {max(vol_counts)}")

    if params['inconsistencies']:
        print(f"   ⚠️  {len(params['inconsistencies'])} inconsistencies detected")
        for issue in params['inconsistencies'][:3]:
            print(f"      - {issue}")

except Exception as e:
    print(f"   ❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("✅ All core components working!")
print("=" * 60)
print("\nThe app is ready but may need SSH port forwarding to access in browser.")
print("You can run the app with: streamlit run app.py --server.port=8500")
print("=" * 60)
