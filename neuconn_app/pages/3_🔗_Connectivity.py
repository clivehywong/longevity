"""
fMRI Connectivity Analysis Pipeline

Multi-stage connectivity pipeline:

1. Local Measures (👤):
   - fALFF/ReHo: Browse visualization and results

2. Seed-Based Connectivity (👤):
   - Seed-to-voxel connectivity maps
   - ROI-to-ROI connectivity matrices

3. Group-Level (👥):
   - Voxelwise statistics on connectivity
   - Network analysis and graph theory
   - Multi-measure comparisons
"""

import streamlit as st

st.title("🔗 fMRI Connectivity Analysis")

st.markdown("""
### Functional Connectivity Pipeline

Navigate through the connectivity analysis stages using the sidebar:

- **�� Local Measures**: fALFF, ALFF, ReHo visualization
- **🌍 Seed Connectivity**: Seed-based and ROI-based connectivity
- **👥 Group Analysis**: Statistical maps, network metrics, comparisons
""")

st.info("🚧 Select a connectivity analysis stage from the sidebar to continue.")
