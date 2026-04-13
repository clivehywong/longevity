"""
Group-Level: TBSS (Tract-Based Spatial Statistics)

Voxelwise statistics on white matter skeleton:

Pipeline:
1. Register all FA maps to FMRIB58_FA template
2. Create mean FA skeleton (center of white matter tracts)
3. Project individual FA onto skeleton
4. Voxelwise statistics on skeleton voxels

Statistical Model:
- Same as fMRI: LME or ANCOVA
- QC profile selection
- CSV upload for participant data

Multiple Comparison Correction:
- TFCE (Threshold-Free Cluster Enhancement)
- FDR
- Uncorrected + cluster extent

Note: TBSS requires FSL. Options:
- Run on HPC (recommended)
- Run locally if FSL installed

Implementation: Phase 12
"""

import streamlit as st

def render():
    st.header("🧠 TBSS (Tract-Based Spatial Statistics)")
    st.info("🚧 Implementation coming in Phase 12")

if __name__ == "__main__":
    render()
