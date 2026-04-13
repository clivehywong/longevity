"""
NIfTI Loading and Slicing Utilities

Functions for loading and extracting slices from NIfTI files.
Ported from script/qa_check_images.py

Implementation: Phase 2 ✅
"""

import nibabel as nib
import numpy as np
from pathlib import Path
from typing import Dict, Tuple
import base64
import io


def load_nifti_mid_slices(nifti_file):
    """
    Load middle slices from a NIfTI file.

    Ported from script/qa_check_images.py:29-51

    Returns:
        dict with 'axial', 'coronal', 'sagittal' slices, and shape
    """
    img = nib.load(nifti_file)
    data = img.get_fdata()

    # Handle 4D (functional) or 3D (structural)
    if len(data.shape) == 4:
        # Take mean across time for functional
        data = data.mean(axis=-1)

    # Get middle slices
    slices = {
        'axial': data[:, :, data.shape[2] // 2],
        'coronal': data[:, data.shape[1] // 2, :],
        'sagittal': data[data.shape[0] // 2, :, :]
    }

    return slices, data.shape


def fig_to_base64(fig):
    """
    Convert matplotlib figure to base64 encoded PNG.

    Ported from script/qa_check_images.py:54-61
    """
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    return img_base64
