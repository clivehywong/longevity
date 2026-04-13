"""
fMRIPrep QC Reports & Summary

View fMRIPrep quality control reports:

Individual Mode:
- Embed sub-XXX.html in iframe
- Extract key metrics (FD, tSNR, BBR cost) from confounds

Summary Table Mode:
- All subjects in color-coded table
- Motion parameters (FD mean, max, n_outliers)
- Temporal SNR
- Registration quality (BBR cost)
- Flag subjects exceeding QC thresholds
- Export to CSV

Parses:
- fmriprep/sub-XXX/ses-XX/func/*_desc-confounds_timeseries.tsv
- fmriprep/sub-XXX.html (Bootstrap 5 report)

Implementation: Phase 5
"""

import streamlit as st

def render():
    st.header("📊 fMRIPrep QC Reports")
    st.info("🚧 Implementation coming in Phase 5")

if __name__ == "__main__":
    render()
