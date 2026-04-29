"""Network connectivity viewer — reads from XCP-D + derivatives/connectivity/.

Shows the full parcel × parcel relmat as a heatmap, optional network
aggregation, top-edges table, and a Pearson sanity panel.
Pipeline selector persists via ``viewer_pipeline_net_conn`` session-state key.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.connectivity_viewer import (
    KNOWN_MEASURES,
    CORRELATION_TYPE,
    pipeline_picker,
    subject_session_pickers,
    list_available_atlases_network,
    list_available_measures,
    load_relmat,
    network_dir,
)

PAGE_KEY = "net_conn"


# ============================================================================
# Cached loaders
# ============================================================================


@st.cache_data(ttl=60)
def _list_atlases(
    bids_root_str: str, pipeline: str, subject: str, session: str
) -> list[str]:
    return list_available_atlases_network(
        Path(bids_root_str), pipeline, subject, session
    )


@st.cache_data(ttl=60)
def _list_measures(
    bids_root_str: str, pipeline: str, subject: str, session: str, atlas: str
) -> list[str]:
    return list_available_measures(
        Path(bids_root_str), pipeline, subject, session, atlas
    )


# ============================================================================
# Network aggregation helper
# ============================================================================


def _infer_network_labels(atlas: str, labels: list[str]) -> list[Optional[str]]:
    """Return per-parcel network names using SeedCatalog logic, or None."""
    try:
        from neuconn_app.utils.seed_catalog import _infer_network
        return [_infer_network(atlas, lbl) for lbl in labels]
    except Exception:
        return [None] * len(labels)


def _aggregate_to_networks(
    mat: np.ndarray, labels: list[str], net_labels: list[Optional[str]]
) -> tuple[np.ndarray, list[str]]:
    """Aggregate parcel matrix to network × network by mean within blocks."""
    networks: dict[str, list[int]] = {}
    for i, net in enumerate(net_labels):
        key = net if net is not None else "Unknown"
        networks.setdefault(key, []).append(i)

    net_names = sorted(networks.keys())
    n = len(net_names)
    agg = np.zeros((n, n))
    for i, net_i in enumerate(net_names):
        for j, net_j in enumerate(net_names):
            idx_i = networks[net_i]
            idx_j = networks[net_j]
            sub = mat[np.ix_(idx_i, idx_j)]
            if i == j:
                # Within-network: exclude diagonal
                mask = ~np.eye(len(idx_i), dtype=bool)
                vals = sub[mask] if len(idx_i) > 1 else sub.flatten()
            else:
                vals = sub.flatten()
            agg[i, j] = float(np.nanmean(vals)) if vals.size > 0 else np.nan
    return agg, net_names


# ============================================================================
# Heatmap renderer
# ============================================================================


def _plot_heatmap(mat: np.ndarray, labels: list[str], title: str, measure: str) -> None:
    try:
        import plotly.express as px
    except ImportError:
        st.warning("plotly not available — cannot render heatmap.")
        return

    is_corr = measure in CORRELATION_TYPE
    abs_max = float(np.nanpercentile(np.abs(mat), 99)) if is_corr else None
    zmin = -abs_max if is_corr else None
    zmax = abs_max if is_corr else None
    colorscale = "RdBu_r" if is_corr else "Viridis"

    n = len(labels)
    fig = px.imshow(
        mat,
        x=labels,
        y=labels,
        color_continuous_scale=colorscale,
        zmin=zmin,
        zmax=zmax,
        title=title,
        aspect="equal" if n <= 100 else "auto",
    )
    fig.update_layout(
        height=max(500, min(900, n * 4)),
        margin=dict(l=10, r=10, t=40, b=10),
        coloraxis_colorbar=dict(title=measure),
    )
    if n > 50:
        fig.update_xaxes(showticklabels=False)
        fig.update_yaxes(showticklabels=False)
    st.plotly_chart(fig, use_container_width=True)


# ============================================================================
# Top-edges table
# ============================================================================


def _render_top_edges(
    mat: np.ndarray,
    labels: list[str],
    net_labels: list[Optional[str]],
    top_n: int = 30,
) -> None:
    n = len(labels)
    rows = []
    for i in range(n):
        for j in range(i + 1, n):
            rows.append(
                {
                    "parcel_i": labels[i],
                    "parcel_j": labels[j],
                    "value": mat[i, j],
                    "network_i": net_labels[i] or "",
                    "network_j": net_labels[j] or "",
                }
            )
    if not rows:
        return
    df = pd.DataFrame(rows)
    df = df.reindex(df["value"].abs().nlargest(top_n).index)
    df["value"] = df["value"].round(4)
    st.dataframe(df.reset_index(drop=True), use_container_width=True)


# ============================================================================
# Main render
# ============================================================================


def render() -> None:
    """Main page render function."""
    st.header("🧩 Network Connectivity")

    config = st.session_state.get("config", {})
    bids_root = Path(
        config.get("paths", {}).get("bids_dir", "")
        or Path(__file__).resolve().parents[3]
    )

    # ── Top selector row ──────────────────────────────────────────────────
    pipeline = pipeline_picker(PAGE_KEY)
    subject, session = subject_session_pickers(bids_root, pipeline, PAGE_KEY)
    if subject is None or session is None:
        return

    # ── Atlas + measure selectors ─────────────────────────────────────────
    atlases = _list_atlases(str(bids_root), pipeline, subject, session)
    if not atlases:
        st.info(
            "No network connectivity outputs found.  "
            "Run the connectivity pipeline first."
        )
        return

    col_atlas, col_measure, col_topn = st.columns([2, 2, 1])
    with col_atlas:
        atlas = st.selectbox(
            "Atlas",
            options=atlases,
            key=f"net_atlas_{PAGE_KEY}_{pipeline}",
        )
    measures = _list_measures(str(bids_root), pipeline, subject, session, atlas)
    if not measures:
        measures = KNOWN_MEASURES  # fallback to full list
    with col_measure:
        measure = st.selectbox(
            "Measure",
            options=measures,
            key=f"net_measure_{PAGE_KEY}_{pipeline}",
        )
    with col_topn:
        top_n = st.number_input(
            "Top edges",
            min_value=5,
            max_value=500,
            value=30,
            key=f"net_topn_{PAGE_KEY}_{pipeline}",
        )

    # ── Load matrix ──────────────────────────────────────────────────────
    mat, labels = load_relmat(str(bids_root), pipeline, subject, session, atlas, measure)
    if mat is None or labels is None:
        st.warning(
            f"Relmat file not found for {subject}/{session}/{pipeline} — "
            f"atlas={atlas}, measure={measure}."
        )
        return

    net_labels = _infer_network_labels(atlas, labels)

    st.caption(
        f"Pipeline: **{pipeline}** | {subject} / {session} | "
        f"Atlas: **{atlas}** | Measure: **{measure}** | "
        f"Shape: {mat.shape[0]} × {mat.shape[1]}"
    )

    # ── Main heatmap ──────────────────────────────────────────────────────
    _plot_heatmap(mat, labels, f"{atlas} — {measure}", measure)

    # ── Network aggregation ───────────────────────────────────────────────
    with st.expander("🔗 Network aggregation"):
        if all(n is None for n in net_labels):
            st.info(f"Atlas **{atlas}** has no network labels — cannot aggregate.")
        else:
            agg_mat, net_names = _aggregate_to_networks(mat, labels, net_labels)
            _plot_heatmap(
                agg_mat, net_names,
                f"Network × Network ({atlas} — {measure})", measure
            )

    # ── Top edges ─────────────────────────────────────────────────────────
    with st.expander(f"📋 Top {top_n} edges by |value|"):
        _render_top_edges(mat, labels, net_labels, int(top_n))

    # ── Compare-with-Pearson ─────────────────────────────────────────────
    if measure != "pearson":
        pearson_mat, _ = load_relmat(
            str(bids_root), pipeline, subject, session, atlas, "pearson"
        )
        if pearson_mat is not None:
            with st.expander("📈 Sanity: scatter vs Pearson"):
                try:
                    import plotly.express as px
                    n_labels = len(labels)
                    idx = np.triu_indices(n_labels, k=1)
                    vals_current = mat[idx]
                    vals_pearson = pearson_mat[idx]
                    scatter_df = pd.DataFrame(
                        {"pearson": vals_pearson, measure: vals_current}
                    )
                    fig = px.scatter(
                        scatter_df.sample(min(5000, len(scatter_df)), random_state=0),
                        x="pearson",
                        y=measure,
                        opacity=0.3,
                        title=f"{measure} vs Pearson (upper triangle, up to 5000 pts)",
                        trendline="ols",
                    )
                    st.plotly_chart(fig, use_container_width=True)
                except Exception as exc:
                    st.warning(f"Scatter plot unavailable: {exc}")


# ============================================================================
# Entry Point
# ============================================================================

if __name__ == "__main__":
    render()
