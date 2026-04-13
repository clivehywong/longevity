"""
dMRI Preprocessing - HPC Submit

Submit QSIPrep/QSIRecon jobs to HPC:

QSIPrep (Preprocessing):
- Distortion correction (field maps)
- Eddy current correction
- Motion correction
- Denoising (MP-PCA, Gibbs)
- Output spaces: T1w, MNI152NLin2009cAsym
- Uses qsiprep-1.1.1.sif

QSIRecon (Reconstruction):
- Tensor fitting (FA, MD, RD, AD)
- CSD (Constrained Spherical Deconvolution)
- Tractography (deterministic/probabilistic)
- Connectivity matrices (Schaefer 400, DiFuMo 256)
- Uses qsirecon-1.2.0.sif

Workflow:
- Upload anat/, dwi/, fmap/ (func excluded)
- Submit both QSIPrep and QSIRecon (sequential)
- Monitor progress
- Download derivatives
- Auto-cleanup

Resources: 16 CPUs, 64GB RAM, 48h (more intensive than fMRIPrep)

Implementation: Phase 12
"""

import streamlit as st

def render():
    st.header("🖥️ HPC Submit - QSIPrep/QSIRecon")
    st.info("🚧 Implementation coming in Phase 12")

if __name__ == "__main__":
    render()
