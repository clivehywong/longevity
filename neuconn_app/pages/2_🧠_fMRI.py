"""
fMRI Analysis Pipeline

Three-stage pipeline for functional MRI analysis:

1. Preprocessing (🔧):
   - HPC Submit: Submit fMRIPrep jobs to HPC
   - QC Reports: View fMRIPrep QC reports and summary table
   - FSL FIX: ICA-FIX denoising
   - fMRIPost-AROMA: ICA-AROMA denoising
   - Comparison: Compare denoising methods

2. Subject-Level (👤):
   - Local Measures: fALFF, ALFF, ReHo
   - Seed Connectivity: Seed-to-voxel, ROI-to-ROI
   - Effective Connectivity: Regression DCM, MVAR/Granger

3. Group-Level (👥):
   - Voxelwise Analysis: LME on local measures
   - ROI Analysis: Connection-wise statistics
   - Graph Theory: Network metrics
   - Visualization: Brain maps, matrices, plots
"""

import streamlit as st

st.title("🧠 fMRI Analysis Pipeline")

st.markdown("""
### Functional MRI Analysis

Navigate through the three pipeline stages using the sidebar:

- **🔧 Preprocessing**: Submit to HPC, review QC, denoise
- **👤 Subject-Level**: Compute connectivity measures
- **👥 Group-Level**: Statistical analysis and visualization
""")

st.info("🚧 Select a pipeline stage from the sidebar to continue.")
