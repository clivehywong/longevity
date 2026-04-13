"""
Subject-Level: Diffusion Metrics

Extract scalar diffusion maps from QSIPrep outputs:

Metrics:
- FA (Fractional Anisotropy): 0-1, white matter integrity
- MD (Mean Diffusivity): mm²/s, overall diffusion
- RD (Radial Diffusivity): Perpendicular to fiber
- AD (Axial Diffusivity): Parallel to fiber

Output Space: T1w or MNI152NLin2009cAsym
Visualization: Overlay on anatomical template

Implementation: Phase 12
"""

import streamlit as st

def render():
    st.header("📊 Diffusion Metrics (FA, MD)")
    st.info("🚧 Implementation coming in Phase 12")

if __name__ == "__main__":
    render()
