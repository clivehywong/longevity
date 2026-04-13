"""
dMRI Analysis Pipeline

Three-stage pipeline for diffusion MRI analysis:

1. Preprocessing (🔧):
   - HPC Submit: Submit QSIPrep/QSIRecon jobs to HPC
   - QC Reports: View QSIPrep QC reports

2. Subject-Level (👤):
   - Diffusion Metrics: FA, MD, RD, AD maps
   - Tractography: Streamline visualization
   - Structural Connectivity: Connectivity matrices from tractography

3. Group-Level (👥):
   - TBSS: Tract-Based Spatial Statistics
   - Network Analysis: Graph theory on structural connectivity
   - Multimodal: Compare structural vs functional connectivity
"""

import streamlit as st

st.title("🔗 dMRI Analysis Pipeline")

st.markdown("""
### Diffusion MRI Analysis

Navigate through the three pipeline stages using the sidebar:

- **🔧 Preprocessing**: QSIPrep preprocessing, QSIRecon reconstruction
- **👤 Subject-Level**: Diffusion metrics, tractography, connectivity
- **👥 Group-Level**: TBSS, network analysis, multimodal integration
""")

st.info("🚧 Select a pipeline stage from the sidebar to continue.")
