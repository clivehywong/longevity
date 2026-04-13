"""
Group-Level: Voxelwise Analysis

Voxelwise statistical analysis on local measures or seed-to-voxel maps:

Statistical Models:
- Linear Mixed-Effects: value ~ Group × Time + covariates + (1|Subject)
- ANCOVA: value ~ Group × Time + covariates
- Correlation: Continuous variable vs brain measure

Features:
- QC profile selection (Strict/Moderate/Lenient/Custom)
- CSV upload for participant data
- Formula editor for custom models
- Multiple comparison correction (FWE/FDR/Uncorrected)
- 3-column side-by-side results view

Outputs:
- Statistical maps (t-stat, F-stat, p-value)
- Cluster tables with anatomical labels
- Effect size plots

Reuses: script/group_level_analysis.py

Implementation: Phase 8
"""

import streamlit as st

def render():
    st.header("🗺️ Voxelwise Analysis")
    st.info("🚧 Implementation coming in Phase 8")

if __name__ == "__main__":
    render()
