"""
Unit tests for papaya_wrapper.py

Tests NIfTI loading, caching, atlas discovery, and Streamlit integration.
"""

import pytest
import sys
from pathlib import Path
import tempfile
import numpy as np
import nibabel as nib
from unittest.mock import Mock, patch, MagicMock

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from utils.papaya_wrapper import (
    load_nifti_as_base64,
    get_nifti_stats,
    get_available_atlases,
    _create_papaya_html,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_nifti():
    """Create a temporary NIfTI file for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Create synthetic data
        data = np.random.randn(32, 32, 32).astype(np.float32)
        data[data < 0] = 0  # Make mostly positive

        affine = np.eye(4)
        img = nib.Nifti1Image(data, affine)

        # Save uncompressed
        nifti_path = tmppath / "test.nii"
        nib.save(img, nifti_path)

        yield str(nifti_path)


@pytest.fixture
def temp_nifti_gz(temp_nifti):
    """Create a temporary compressed NIfTI file."""
    import gzip
    import shutil

    nifti_path = Path(temp_nifti)
    gz_path = nifti_path.with_suffix(".nii.gz")

    with open(nifti_path, "rb") as f_in:
        with gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    yield str(gz_path)

    # Cleanup
    gz_path.unlink(missing_ok=True)


# ============================================================================
# Test File Loading & Caching
# ============================================================================

def test_load_nifti_as_base64(temp_nifti):
    """Test loading NIfTI and converting to base64."""
    b64_data = load_nifti_as_base64(temp_nifti)

    assert isinstance(b64_data, str)
    assert len(b64_data) > 100  # Should be substantial
    # Base64 should only contain valid characters
    assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in b64_data)


def test_load_nifti_as_base64_compressed(temp_nifti_gz):
    """Test loading compressed NIfTI file."""
    b64_data = load_nifti_as_base64(temp_nifti_gz)

    assert isinstance(b64_data, str)
    assert len(b64_data) > 0


def test_load_nifti_file_not_found():
    """Test error handling for missing file."""
    with pytest.raises(FileNotFoundError):
        load_nifti_as_base64("/nonexistent/path/file.nii.gz")


def test_load_nifti_invalid_format(temp_nifti):
    """Test error handling for invalid NIfTI file."""
    # Create a fake file that's not a NIfTI
    with tempfile.NamedTemporaryFile(suffix=".nii") as f:
        f.write(b"Not a NIfTI file")
        f.flush()

        with pytest.raises(ValueError):
            load_nifti_as_base64(f.name)


# ============================================================================
# Test NIfTI Statistics
# ============================================================================

def test_get_nifti_stats(temp_nifti):
    """Test extracting NIfTI statistics."""
    stats = get_nifti_stats(temp_nifti)

    assert isinstance(stats, dict)
    assert "shape" in stats
    assert "min" in stats
    assert "max" in stats
    assert "mean" in stats
    assert "p5" in stats
    assert "p95" in stats
    assert "nonzero_voxels" in stats

    assert stats["shape"] == (32, 32, 32)
    assert stats["min"] <= stats["p5"] <= stats["p95"] <= stats["max"]
    assert stats["nonzero_voxels"] > 0


def test_get_nifti_stats_with_nan(temp_nifti):
    """Test statistics calculation with NaN values."""
    # Load, add NaNs, and save
    img = nib.load(temp_nifti)
    data = img.get_fdata()
    data[0:10, 0:10, 0:10] = np.nan
    img_nan = nib.Nifti1Image(data, img.affine)

    with tempfile.TemporaryDirectory() as tmpdir:
        nan_path = Path(tmpdir) / "with_nan.nii"
        nib.save(img_nan, nan_path)

        stats = get_nifti_stats(str(nan_path))

        # Should handle NaN gracefully
        assert not np.isnan(stats["mean"])
        assert not np.isnan(stats["min"])


def test_get_nifti_stats_file_not_found():
    """Test stats error handling for missing file."""
    stats = get_nifti_stats("/nonexistent/file.nii.gz")

    # Should return default stats instead of crashing
    assert stats["min"] == 0
    assert stats["max"] == 1


# ============================================================================
# Test Atlas Discovery
# ============================================================================

def test_get_available_atlases():
    """Test discovering available atlases."""
    atlases = get_available_atlases()

    assert isinstance(atlases, dict)
    # Should find at least some atlases in the project
    # (but might be empty if running in different environment)
    for name, path in atlases.items():
        assert isinstance(name, str)
        assert isinstance(path, str)


# ============================================================================
# Test HTML Generation
# ============================================================================

def test_create_papaya_html_basic():
    """Test basic HTML generation."""
    html = _create_papaya_html(
        brain_map_path="data:application/octet-stream;base64,test_data",
        colormap="Hot",
        threshold_range=(0, 100),
        height=600,
    )

    assert isinstance(html, str)
    assert "<script" in html
    assert "papaya.js" in html
    assert "papaya.css" in html
    assert "papayaViewer" in html
    assert "Hot" in html or "colorMap" in html
    assert "600" in html


def test_create_papaya_html_with_overlays():
    """Test HTML generation with overlays."""
    overlays = [
        "data:application/octet-stream;base64,overlay1",
        "data:application/octet-stream;base64,overlay2",
    ]

    html = _create_papaya_html(
        brain_map_path="data:application/octet-stream;base64,main",
        overlays=overlays,
        overlay_colormaps=["spectrum", "jet"],
    )

    assert isinstance(html, str)
    assert "papaya.js" in html
    assert "overlay" in html.lower() or "alpha" in html.lower()


def test_create_papaya_html_custom_id():
    """Test HTML generation with custom container ID."""
    html = _create_papaya_html(
        brain_map_path="test_path",
        container_id="custom_viewer_123",
    )

    assert "custom_viewer_123" in html


# ============================================================================
# Test Streamlit Integration
# ============================================================================

@pytest.mark.skipif(
    not Path("/home/clivewong/proj/longevity").exists(),
    reason="Project path not found"
)
def test_papaya_viewer_with_real_atlases():
    """Integration test with real project atlases (skipped if not available)."""
    from utils.papaya_wrapper import render_papaya_viewer_streamlit

    # This is a visual test - just ensure it doesn't crash
    # Mock streamlit to avoid interactive session
    with patch("utils.papaya_wrapper.st") as mock_st:
        mock_st.markdown = Mock()
        mock_st.columns = Mock(
            return_value=[
                MagicMock(),  # main column
                MagicMock(),  # sidebar column
            ]
        )
        mock_st.error = Mock()
        mock_st.session_state = {}
        mock_st.components.v1.html = Mock()

        # Should not raise
        mni_template = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz"
        state = render_papaya_viewer_streamlit(
            brain_map_path=mni_template,
            title="Test",
            height=600,
        )

        assert isinstance(state, dict)


# ============================================================================
# Test Edge Cases
# ============================================================================

def test_nifti_with_negative_values(temp_nifti):
    """Test handling of negative values in NIfTI."""
    img = nib.load(temp_nifti)
    data = img.get_fdata()
    data = data - np.abs(data).mean()  # Make negative and positive values
    img_neg = nib.Nifti1Image(data, img.affine)

    with tempfile.TemporaryDirectory() as tmpdir:
        neg_path = Path(tmpdir) / "negative.nii"
        nib.save(img_neg, neg_path)

        stats = get_nifti_stats(str(neg_path))

        assert stats["min"] < 0
        assert stats["max"] > 0


def test_nifti_all_zeros():
    """Test handling of all-zero NIfTI file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data = np.zeros((32, 32, 32), dtype=np.float32)
        img = nib.Nifti1Image(data, np.eye(4))

        zero_path = Path(tmpdir) / "zeros.nii"
        nib.save(img, zero_path)

        stats = get_nifti_stats(str(zero_path))

        assert stats["min"] == 0
        assert stats["max"] == 0
        assert stats["nonzero_voxels"] == 0


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
