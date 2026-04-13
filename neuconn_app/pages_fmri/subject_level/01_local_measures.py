"""
Subject-Level: Local Measures

Compute voxel-wise functional measures:
- fALFF: Fractional amplitude of low-frequency fluctuations
- ALFF: Amplitude of low-frequency fluctuations
- ReHo: Regional homogeneity (Kendall's W, 26-neighbor)
- VMHC: Voxel-mirrored homotopic connectivity (optional)

Input: fMRIPrep or denoised BOLD
Processing: Bandpass filter (0.01-0.1 Hz), confound regression
Output: 3D maps per subject/session

Reuses: script/compute_local_measures.py

Implementation: Phase 7
"""

import streamlit as st

def render():
    st.header("📊 Local Measures (fALFF, ReHo)")
    st.info("🚧 Implementation coming in Phase 7")

if __name__ == "__main__":
    render()
