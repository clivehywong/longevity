"""Simple test to verify app components work."""

import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

st.title("NeuConn Test App")

# Test config loading
try:
    from utils.config import load_config
    config_path = Path.home() / "neuconn_projects" / "longevity.yaml"
    config = load_config(str(config_path))
    st.success(f"✅ Config loaded: {config['project']['name']}")
    st.write(f"BIDS dir: {config['paths']['bids_dir']}")
except Exception as e:
    st.error(f"❌ Config error: {e}")

# Test BIDS scan
try:
    from utils.bids import scan_bids_directory
    bids_dir = Path("/home/clivewong/proj/longevity/bids")

    with st.spinner("Scanning BIDS..."):
        result = scan_bids_directory(bids_dir)

    st.success(f"✅ BIDS scanned: {len(result['subjects'])} subjects")
    st.json(result)
except Exception as e:
    st.error(f"❌ BIDS scan error: {e}")
    import traceback
    st.code(traceback.format_exc())
