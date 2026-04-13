"""
Subject-Level: Seed-Based Connectivity

Seed-to-voxel and ROI-to-ROI connectivity:

Seed Definition Methods:
1. Atlas-based: Select from DiFuMo 256, Schaefer 400, AAL, Power 264
2. Upload custom NIfTI mask
3. Sphere from MNI coordinates + radius

Analysis Types:
- Seed-to-voxel: Whole-brain z-maps showing connectivity with seed
- ROI-to-ROI: Connectivity matrix between selected ROIs

Processing: Pearson/Spearman correlation, Fisher Z-transform
Outputs: Z-maps (seed-to-voxel), correlation matrices (ROI-to-ROI)

Reuses: script/seed_based_connectivity.py

Implementation: Phase 7
"""

import streamlit as st

def render():
    st.header("🎯 Seed-Based Connectivity")
    st.info("🚧 Implementation coming in Phase 7")

if __name__ == "__main__":
    render()
