"""
Papaya Viewer Streamlit Wrapper

Interactive NIfTI viewer component using Papaya.js, served via a lightweight
background HTTP file server so Papaya can load files with standard XHR instead
of unreliable base64 data URIs.

Usage::

    from utils.papaya_wrapper import render_papaya_viewer_streamlit

    render_papaya_viewer_streamlit(
        brain_map_path="/abs/path/to/T1w.nii.gz",
        overlays=["/abs/path/to/alff.nii.gz"],
        colormap="Grayscale",
        overlay_colormaps=["Overlay (Positives)"],
    )
"""

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import nibabel as nib
import numpy as np
import streamlit as st

logger = logging.getLogger(__name__)

# Built-in Papaya color table names
PAPAYA_LUTS = [
    "Grayscale",
    "Spectrum",
    "Overlay (Positives)",
    "Overlay (Negatives)",
    "Hot-and-Cold",
    "Gold",
    "Red Overlay",
    "Green Overlay",
    "Blue Overlay",
]


# ============================================================================
# NIfTI stats (for info display only — no longer used for image loading)
# ============================================================================

@st.cache_data
def get_nifti_stats(file_path: str) -> Dict[str, Any]:
    """Return basic statistics about a NIfTI file."""
    try:
        img = nib.load(file_path)
        data = img.get_fdata()
        valid = data[np.isfinite(data)]
        if len(valid) == 0:
            return {"shape": data.shape, "min": 0, "max": 1, "mean": 0, "nonzero_voxels": 0}
        return {
            "shape": data.shape,
            "min": float(np.min(valid)),
            "max": float(np.max(valid)),
            "mean": float(np.mean(valid)),
            "nonzero_voxels": int(np.count_nonzero(valid)),
        }
    except Exception as exc:
        logger.error("Error reading NIfTI stats for %s: %s", file_path, exc)
        return {"shape": (0, 0, 0), "min": 0, "max": 1, "mean": 0, "nonzero_voxels": 0}


# ============================================================================
# HTML generation — proper Papaya JS array params API
# ============================================================================

def _create_papaya_html(
    images: List[str],
    image_options: Optional[Dict[str, Dict]] = None,
    global_options: Optional[Dict] = None,
    height: int = 600,
    container_id: str = "papayaViewer",
    encoded_images: Optional[List[Tuple[str, str]]] = None,
) -> str:
    """Generate Papaya viewer HTML using the official JavaScript array params API.

    Args:
        images: Ordered list of image filenames (used as keys in params).
            When *encoded_images* is supplied these are "virtual" filenames
            that do not need to be real URLs — Papaya matches them by position
            to the JS variable names in ``params["encodedImages"]``.
        image_options: ``{filename: {lut, alpha, minPercent, …}}``.
        global_options: Papaya global params such as ``showOrientation``.
        height: Viewer height in pixels.
        container_id: HTML element ID for the Papaya container.
        encoded_images: List of ``(js_varname, base64_data)`` tuples.
            If provided, the data is embedded directly in the page as JS
            variables — no XHR/file-server required (works over SSH tunnels).
    """
    lines: List[str] = [
        "    var params = [];",
    ]

    if encoded_images:
        # encodedImages API: list of variable NAME strings — Papaya reads window[name]
        # IMPORTANT: do NOT also set params["images"] — loadNextImage checks images FIRST
        # and never reaches encodedImages if images is present (even as empty array).
        varnames = [vn for vn, _ in encoded_images]
        lines.append(f"    params[\"encodedImages\"] = {json.dumps(varnames)};")
        for fname, opts in (image_options or {}).items():
            lines.append(f"    params[{json.dumps(fname)}] = {json.dumps(opts)};")
    else:
        lines.append(f"    params[\"images\"] = {json.dumps(images)};")
        for fname, opts in (image_options or {}).items():
            lines.append(f"    params[{json.dumps(fname)}] = {json.dumps(opts)};")

    for key, val in (global_options or {}).items():
        lines.append(f"    params[{json.dumps(key)}] = {json.dumps(val)};")
    # No explicit addViewer() — Papaya auto-initializes from the global `params`
    # variable when its script loads and finds the .papaya div.

    params_block = "\n".join(lines)

    # Declare base64 JS variables before the params block
    var_decls = ""
    if encoded_images:
        var_decls = "\n".join(
            f'var {vn} = "{data}";' for vn, data in encoded_images
        ) + "\n"

    return f"""<!DOCTYPE html>
<html>
<head>
<script src="https://cdn.jsdelivr.net/gh/rii-mango/Papaya@master/release/current/standard/papaya.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/rii-mango/Papaya@master/release/current/standard/papaya.css">
<style>
  body {{ margin: 0; padding: 0; background: #000; }}
  .papaya {{ width: 100%; height: {height}px; }}
</style>
</head>
<body>
<div id="{container_id}" class="papaya" data-params="params"></div>
<script>
{var_decls}{params_block}
</script>
</body>
</html>"""


# ============================================================================
# File encoding (replaces file server — works over SSH tunnels)
# ============================================================================

@st.cache_data(max_entries=20, ttl=3600)
def _load_nifti_b64(file_path: str) -> str:
    """Base64-encode a NIfTI file (cached per path)."""
    with open(file_path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


# ============================================================================
# Session-state helpers
# ============================================================================

def _init_state(prefix: str, colormap: str, ov_alpha: float,
                ov_min: float, ov_max: float) -> None:
    # Keys use _val suffix to avoid collision with old int-based keys
    defaults = {
        f"{prefix}_colormap": colormap,
        f"{prefix}_ov_alpha": ov_alpha,
        f"{prefix}_ov_min_val": ov_min,
        f"{prefix}_ov_max_val": ov_max,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ============================================================================
# Main component
# ============================================================================

def render_papaya_viewer_streamlit(
    brain_map_path: str,
    title: str = "",
    overlays: Optional[List[str]] = None,
    colormap: str = "Grayscale",
    overlay_colormaps: Optional[List[str]] = None,
    overlay_alpha: float = 0.7,
    overlay_min: Optional[float] = None,   # actual value; None → auto (20% of imageMax)
    overlay_max: Optional[float] = None,   # actual value; None → auto (imageMax)
    overlay_mode: str = "positive",        # "positive" | "bidirectional" (future)
    height: int = 600,
    key: Optional[str] = None,
    enable_export: bool = False,
    show_info: bool = False,
    serve_dir: Optional[str] = None,
    **_kwargs,  # absorb deprecated overlay_min_pct/overlay_max_pct
) -> Dict[str, Any]:
    """Render a Papaya NIfTI viewer in Streamlit.

    NIfTI files are base64-encoded and embedded directly in the HTML page
    via Papaya's ``encodedImages`` API.  This avoids the need for an
    auxiliary file server and works over SSH tunnels.

    Args:
        brain_map_path: Background NIfTI image (local path).
        title: Optional section heading.
        overlays: Overlay NIfTI images (local paths).
        colormap: Papaya LUT name for the background image.
        overlay_colormaps: Per-overlay Papaya LUT names.
        overlay_alpha: Initial opacity for overlays (0–1).
        overlay_min: Initial lower threshold in actual image units (None → 20% of imageMax).
        overlay_max: Initial upper threshold in actual image units (None → imageMax).
        overlay_mode: ``"positive"`` (default) for ALFF/ReHo-style maps; ``"bidirectional"``
            for z-scores/t-stats with both positive and negative values (future).
        height: Viewer height in pixels.
        key: Streamlit component key / session-state prefix.
        enable_export: Unused; kept for API compatibility.
        show_info: Show NIfTI stats beneath the controls.
        serve_dir: Unused; kept for API compatibility.
    """
    if title:
        st.markdown(f"### {title}")

    prefix = key or "papaya"

    # Read overlay image stats upfront so slider range and defaults are data-driven.
    # get_nifti_stats is cached, so this is cheap after the first call.
    img_max = 1.0
    img_min = 0.0
    if overlays:
        ov_stats = get_nifti_stats(overlays[0])
        img_max = max(float(ov_stats.get("max", 1.0)), 1e-6)
        img_min = float(ov_stats.get("min", 0.0))

    default_ov_min = overlay_min if overlay_min is not None else round(img_max * 0.2, 2)
    default_ov_max = overlay_max if overlay_max is not None else img_max

    _init_state(prefix, colormap, overlay_alpha, default_ov_min, default_ov_max)

    col_main, col_ctrl = st.columns([3, 1])

    # ── Controls ──────────────────────────────────────────────────────────
    with col_ctrl:
        st.markdown("**⚙️ Controls**")

        if overlays:
            step = max(round(img_max / 100, 2), 0.01)

            st.markdown("**🌡️ Stat Map**")
            st.session_state[f"{prefix}_ov_min_val"] = st.slider(
                "Threshold Min", 0.0, float(img_max),
                float(st.session_state[f"{prefix}_ov_min_val"]),
                step, format="%.2f",
                key=f"{prefix}_ov_min_sl",
            )
            st.session_state[f"{prefix}_ov_max_val"] = st.slider(
                "Threshold Max", 0.0, float(img_max),
                float(st.session_state[f"{prefix}_ov_max_val"]),
                step, format="%.2f",
                key=f"{prefix}_ov_max_sl",
            )
            st.session_state[f"{prefix}_ov_alpha"] = st.slider(
                "Opacity", 0.0, 1.0,
                st.session_state[f"{prefix}_ov_alpha"], 0.05,
                key=f"{prefix}_ov_alpha_sl",
            )
            st.markdown("**🧠 Background**")

        cur_cmap = st.session_state[f"{prefix}_colormap"]
        if cur_cmap not in PAPAYA_LUTS:
            cur_cmap = PAPAYA_LUTS[0]
        st.session_state[f"{prefix}_colormap"] = st.selectbox(
            "Colormap",
            PAPAYA_LUTS,
            index=PAPAYA_LUTS.index(cur_cmap),
            key=f"{prefix}_cmap_sel",
        )

        if show_info and brain_map_path:
            try:
                stats = get_nifti_stats(brain_map_path)
                st.markdown("**ℹ️ File Info**")
                st.caption(f"Shape: {stats['shape']}")
                st.caption(f"Min: {stats['min']:.2f}")
                st.caption(f"Max: {stats['max']:.2f}")
                st.caption(f"Nonzero: {stats['nonzero_voxels']}")
            except Exception:
                pass

    # ── Viewer ────────────────────────────────────────────────────────────
    with col_main:
        all_paths = [brain_map_path] + (overlays or [])
        encoded_images: List[Tuple[str, str]] = []
        varnames: List[str] = []
        for i, p in enumerate(all_paths):
            vn = f"nii_{prefix.replace('-', '_').replace('.', '_')}_{i}"
            try:
                data = _load_nifti_b64(p)
            except Exception as exc:
                logger.error("Cannot encode %s: %s", p, exc)
                st.error(f"Cannot load image: {Path(p).name}")
                return {}
            encoded_images.append((vn, data))
            varnames.append(vn)

        image_options: Dict[str, Dict] = {
            varnames[0]: {
                "lut": st.session_state[f"{prefix}_colormap"],
            }
        }

        ov_cmaps = overlay_colormaps or (["Overlay (Positives)"] * len(overlays or []))
        for idx, (ov_path, ov_lut) in enumerate(zip(overlays or [], ov_cmaps)):
            vn = varnames[1 + idx]
            ov_min_val = float(st.session_state[f"{prefix}_ov_min_val"])
            ov_max_val = float(st.session_state[f"{prefix}_ov_max_val"])
            # Papaya's minPercent/maxPercent are FRACTIONS (0–1), not percentages:
            #   screenMin = imageMax * minPercent
            #   screenMax = imageMax * maxPercent
            image_options[vn] = {
                "lut": ov_lut,
                "alpha": float(st.session_state[f"{prefix}_ov_alpha"]),
                "minPercent": ov_min_val / img_max,
                "maxPercent": ov_max_val / img_max,
            }

        container_id = prefix.replace("-", "_").replace(".", "_")
        html = _create_papaya_html(
            images=[],
            image_options=image_options,
            global_options={"showOrientation": True},
            height=height,
            container_id=container_id,
            encoded_images=encoded_images,
        )
        st.components.v1.html(html, height=height + 30)

    return {
        "colormap": st.session_state[f"{prefix}_colormap"],
        "overlay_alpha": st.session_state[f"{prefix}_ov_alpha"],
        "overlay_min": st.session_state[f"{prefix}_ov_min_val"],
        "overlay_max": st.session_state[f"{prefix}_ov_max_val"],
    }


# ============================================================================
# Convenience helpers (kept for backward compatibility)
# ============================================================================

@st.cache_data
def load_nifti_as_base64(file_path: str) -> str:
    """Load NIfTI file as base64 string (kept for external callers)."""
    import base64
    import os
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"NIfTI file not found: {file_path}")
    with open(file_path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("utf-8")


def render_atlas_comparison(
    atlases: Dict[str, str],
    brain_template_path: Optional[str] = None,
    height: int = 600,
) -> None:
    """Render multiple atlases in tabs (kept for backward compatibility)."""
    tabs = st.tabs(list(atlases.keys()))
    for tab, (atlas_name, atlas_path) in zip(tabs, atlases.items()):
        with tab:
            render_papaya_viewer_streamlit(
                brain_map_path=brain_template_path or atlas_path,
                overlays=[atlas_path] if brain_template_path else None,
                title=atlas_name,
                height=height,
                key=f"atlas_{atlas_name.replace(' ', '_')}",
            )


def get_available_atlases() -> Dict[str, str]:
    """Get dictionary of available atlases in the project."""
    atlas_base = Path(__file__).resolve().parents[2] / "atlases"
    atlases: Dict[str, str] = {}
    if (atlas_base / "difumo256.nii").exists():
        atlases["DiFuMo 256"] = str(atlas_base / "difumo256.nii")
    schaefer = atlas_base / "schaefer200_7net.nii"
    if schaefer.exists():
        atlases["Schaefer 200"] = str(schaefer)
    return atlases


