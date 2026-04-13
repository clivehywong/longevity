"""
fMRIPost-AROMA - ICA-AROMA Denoising

ICA-AROMA automatically removes motion artifacts:
- Uses predefined classifier (no training data needed)
- Lighter weight than FSL FIX
- Two strategies: non-aggressive (partial) vs aggressive (full removal)

Input: fMRIPrep preprocessed BOLD
Output: *_desc-smoothAROMAnonaggr_bold.nii.gz

Execution options:
- Local (if fMRIPost-AROMA installed)
- HPC (using fmripost-aroma.sif)

Faster than FSL FIX (~30 min vs 2-4 hours per subject)

Implementation: Phase 6
"""

import streamlit as st

def render():
    st.header("🌪️ fMRIPost-AROMA Denoising")
    st.info("🚧 Implementation coming in Phase 6")

if __name__ == "__main__":
    render()
