"""
Subject-level functional connectivity helpers backed by XCP-D outputs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence
import re

import numpy as np
import pandas as pd

from utils.roi_config import load_roi_config, seed_rois


ARTIFACT_PATTERNS = {
    "timeseries": "**/*timeseries*.tsv",
    "connectome": "**/*connectome*.tsv",
    "alff": "**/*_alff.nii.gz",
    "falff": "**/*_falff.nii.gz",
    "reho": "**/*_reho.nii.gz",
    "exec_report": "**/*exec_report*.html",
}


def discover_fc_artifacts(config: Dict[str, Any]) -> pd.DataFrame:
    """Discover subject-level FC-relevant artifacts under the XCP-D FC tree."""
    xcpd_fc_dir = Path(config["paths"]["xcpd_fc_dir"])
    rows: List[Dict[str, Any]] = []
    for artifact_type, pattern in ARTIFACT_PATTERNS.items():
        for artifact_path in sorted(xcpd_fc_dir.glob(pattern)):
            if artifact_path.is_dir():
                continue
            rows.append(_artifact_row(artifact_path, artifact_type))

    if not rows:
        return pd.DataFrame(
            columns=[
                "artifact_type",
                "measure",
                "subject_id",
                "session",
                "task",
                "atlas",
                "space",
                "desc",
                "source_file",
                "file_name",
            ]
        )

    return pd.DataFrame(rows).sort_values(
        ["artifact_type", "subject_id", "session", "atlas", "file_name"],
        na_position="last",
    )


def refresh_subject_level_fc(config: Dict[str, Any]) -> Dict[str, Any]:
    """Create and persist FC manifests derived from XCP-D outputs."""
    subject_root = Path(config["paths"]["subject_level_fc_dir"])
    manifest_dir = subject_root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    artifacts = discover_fc_artifacts(config)
    artifacts_path = manifest_dir / "xcpd_fc_artifacts.csv"
    artifacts.to_csv(artifacts_path, index=False)

    timeseries = artifacts[artifacts["artifact_type"] == "timeseries"].copy()
    connectomes = artifacts[artifacts["artifact_type"] == "connectome"].copy()
    local_measures = artifacts[
        artifacts["artifact_type"].isin(["alff", "falff", "reho"])
    ].copy()

    timeseries_path = manifest_dir / "timeseries_manifest.csv"
    connectomes_path = manifest_dir / "connectome_manifest.csv"
    local_measures_path = manifest_dir / "local_measures_manifest.csv"
    inventory_path = manifest_dir / "artifact_inventory.csv"

    timeseries.to_csv(timeseries_path, index=False)
    connectomes.to_csv(connectomes_path, index=False)
    local_measures.to_csv(local_measures_path, index=False)

    inventory = (
        artifacts.groupby(["artifact_type", "atlas"], dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values(["artifact_type", "atlas"], na_position="last")
    )
    inventory.to_csv(inventory_path, index=False)

    return {
        "artifacts": artifacts,
        "timeseries": timeseries,
        "connectomes": connectomes,
        "local_measures": local_measures,
        "inventory": inventory,
        "manifest_dir": manifest_dir,
        "artifacts_path": artifacts_path,
        "timeseries_path": timeseries_path,
        "connectomes_path": connectomes_path,
        "local_measures_path": local_measures_path,
        "inventory_path": inventory_path,
    }


def export_seed_level_outputs(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Export atlas-based seed timeseries and connectivity summaries.

    The current XCP-D-backed export path only supports atlas_parcels ROIs,
    because sphere/mask seeds require voxel-space extraction outside the
    parcellated XCP-D outputs.
    """
    manifests = refresh_subject_level_fc(config)
    subject_root = Path(config["paths"]["subject_level_fc_dir"])
    export_root = subject_root / "seed_connectivity"
    export_root.mkdir(parents=True, exist_ok=True)

    timeseries_root = export_root / "timeseries"
    matrices_root = export_root / "matrices"
    profiles_root = export_root / "profiles"
    manifest_dir = subject_root / "manifests"
    for output_dir in (timeseries_root, matrices_root, profiles_root, manifest_dir):
        output_dir.mkdir(parents=True, exist_ok=True)

    roi_config = load_roi_config(Path(config["paths"]["roi_config_path"]))
    seeds = seed_rois(roi_config)
    supported_seeds = [seed for seed in seeds if seed.get("type") == "atlas_parcels"]
    support_rows = []
    for seed in seeds:
        support_rows.append(
            {
                "seed_id": seed["id"],
                "label": seed.get("label", seed["id"]),
                "roi_type": seed.get("type", ""),
                "supported": seed.get("type") == "atlas_parcels",
                "reason": ""
                if seed.get("type") == "atlas_parcels"
                else "Requires voxel-space extraction beyond parcellated XCP-D outputs.",
            }
        )
    support_manifest = pd.DataFrame(support_rows)
    support_manifest.to_csv(manifest_dir / "seed_support_manifest.csv", index=False)

    timeseries_exports: List[Dict[str, Any]] = []
    connectivity_exports: List[Dict[str, Any]] = []

    for _, artifact in manifests["timeseries"].iterrows():
        export = _export_seed_timeseries_file(Path(artifact["source_file"]), supported_seeds, timeseries_root)
        if export:
            timeseries_exports.append({**artifact.to_dict(), **export})

    for _, artifact in manifests["connectomes"].iterrows():
        export = _export_seed_connectivity_file(
            Path(artifact["source_file"]),
            supported_seeds,
            matrices_root,
            profiles_root,
        )
        if export:
            connectivity_exports.append({**artifact.to_dict(), **export})

    timeseries_manifest = pd.DataFrame(
        timeseries_exports,
        columns=[
            "artifact_type",
            "measure",
            "subject_id",
            "session",
            "task",
            "atlas",
            "space",
            "desc",
            "source_file",
            "file_name",
            "seed_count",
            "seed_ids",
            "selected_labels",
            "export_file",
        ],
    )
    connectivity_manifest = pd.DataFrame(
        connectivity_exports,
        columns=[
            "artifact_type",
            "measure",
            "subject_id",
            "session",
            "task",
            "atlas",
            "space",
            "desc",
            "source_file",
            "file_name",
            "seed_count",
            "seed_ids",
            "selected_labels",
            "matrix_file",
            "profile_file",
        ],
    )
    timeseries_manifest.to_csv(manifest_dir / "seed_timeseries_manifest.csv", index=False)
    connectivity_manifest.to_csv(manifest_dir / "seed_connectivity_manifest.csv", index=False)

    return {
        **manifests,
        "seed_support": support_manifest,
        "seed_timeseries_manifest": timeseries_manifest,
        "seed_connectivity_manifest": connectivity_manifest,
        "timeseries_export_dir": timeseries_root,
        "matrix_export_dir": matrices_root,
        "profile_export_dir": profiles_root,
    }


def load_manifest_table(config: Dict[str, Any], name: str) -> pd.DataFrame:
    """Load one of the persisted subject-level FC manifest tables."""
    manifest_path = Path(config["paths"]["subject_level_fc_dir"]) / "manifests" / name
    if not manifest_path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(manifest_path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _artifact_row(path: Path, artifact_type: str) -> Dict[str, Any]:
    file_name = path.name
    return {
        "artifact_type": artifact_type,
        "measure": artifact_type if artifact_type in {"alff", "falff", "reho"} else "",
        "subject_id": _extract_entity(file_name, r"(sub-[A-Za-z0-9]+)"),
        "session": _extract_entity(file_name, r"(ses-[A-Za-z0-9]+)"),
        "task": _extract_entity(file_name, r"_task-([^_]+)"),
        "atlas": _extract_entity(file_name, r"_atlas-([^_]+)"),
        "space": _extract_entity(file_name, r"_space-([^_]+)"),
        "desc": _extract_entity(file_name, r"_desc-([^_]+)"),
        "source_file": str(path),
        "file_name": file_name,
    }


def _extract_entity(file_name: str, pattern: str) -> str:
    match = re.search(pattern, file_name)
    return match.group(1) if match else ""


def _export_seed_timeseries_file(
    source_file: Path,
    seeds: Sequence[Dict[str, Any]],
    output_dir: Path,
) -> Dict[str, Any] | None:
    timeseries = pd.read_csv(source_file, sep="\t")
    resolved = _resolve_seed_columns(timeseries.columns, seeds)
    if not resolved:
        return None

    export = pd.DataFrame(index=timeseries.index)
    for seed_id, labels in resolved.items():
        export[seed_id] = timeseries.loc[:, labels].mean(axis=1)

    export_path = output_dir / source_file.name.replace(".tsv", "_seed_timeseries.tsv")
    export.to_csv(export_path, sep="\t", index=False)

    return {
        "seed_count": len(resolved),
        "seed_ids": ",".join(resolved.keys()),
        "selected_labels": "; ".join(
            f"{seed_id}:{','.join(labels)}" for seed_id, labels in resolved.items()
        ),
        "export_file": str(export_path),
    }


def _export_seed_connectivity_file(
    source_file: Path,
    seeds: Sequence[Dict[str, Any]],
    matrix_output_dir: Path,
    profile_output_dir: Path,
) -> Dict[str, Any] | None:
    matrix = _load_connectome(source_file)
    resolved = _resolve_seed_columns(matrix.columns, seeds)
    if not resolved:
        return None

    seed_ids = list(resolved.keys())
    seed_matrix = pd.DataFrame(index=seed_ids, columns=seed_ids, dtype=float)
    seed_profiles = pd.DataFrame(index=matrix.columns)

    for seed_id, labels in resolved.items():
        seed_profiles[seed_id] = matrix.loc[labels, :].mean(axis=0)

    for seed_i, labels_i in resolved.items():
        for seed_j, labels_j in resolved.items():
            block = matrix.loc[labels_i, labels_j].to_numpy(dtype=float)
            if seed_i == seed_j and block.shape[0] == block.shape[1] and block.shape[0] > 1:
                mask = ~np.eye(block.shape[0], dtype=bool)
                values = block[mask]
            else:
                values = block.reshape(-1)
            seed_matrix.loc[seed_i, seed_j] = float(np.nanmean(values))

    matrix_path = matrix_output_dir / source_file.name.replace(".tsv", "_seed_matrix.tsv")
    profile_path = profile_output_dir / source_file.name.replace(".tsv", "_seed_to_roi.tsv")
    seed_matrix.to_csv(matrix_path, sep="\t")
    seed_profiles.to_csv(profile_path, sep="\t")

    return {
        "seed_count": len(resolved),
        "seed_ids": ",".join(seed_ids),
        "selected_labels": "; ".join(
            f"{seed_id}:{','.join(labels)}" for seed_id, labels in resolved.items()
        ),
        "matrix_file": str(matrix_path),
        "profile_file": str(profile_path),
    }


def _load_connectome(source_file: Path) -> pd.DataFrame:
    table = pd.read_csv(source_file, sep="\t")
    if table.empty:
        raise ValueError(f"Connectome table is empty: {source_file}")

    if table.columns[0].startswith("Unnamed") or table.shape[1] == table.shape[0] + 1:
        matrix = table.set_index(table.columns[0])
    else:
        matrix = table.copy()
        matrix.index = matrix.columns

    matrix.index = matrix.index.map(str)
    matrix.columns = [str(column) for column in matrix.columns]
    return matrix.apply(pd.to_numeric, errors="coerce")


def _resolve_seed_columns(
    columns: Iterable[Any],
    seeds: Sequence[Dict[str, Any]],
) -> Dict[str, List[str]]:
    available = [str(column) for column in columns]
    resolved: Dict[str, List[str]] = {}

    for seed in seeds:
        matches = _match_seed_labels(available, seed)
        if matches:
            resolved[seed["id"]] = matches

    return resolved


def _match_seed_labels(available: Sequence[str], seed: Dict[str, Any]) -> List[str]:
    if seed.get("type") != "atlas_parcels":
        return []

    candidates = list(available)
    parcel_labels = [str(label) for label in seed.get("parcel_labels", []) if label]
    if parcel_labels:
        parcel_matches: List[str] = []
        for target in parcel_labels:
            target_norm = _normalize_label(target)
            exact = [label for label in available if _normalize_label(label) == target_norm]
            contains = [
                label
                for label in available
                if target_norm in _normalize_label(label) or _normalize_label(label) in target_norm
            ]
            parcel_matches.extend(exact or contains)
        candidates = list(dict.fromkeys(parcel_matches))

    network_filter = str(seed.get("network_filter", "")).strip()
    if network_filter:
        source = candidates if parcel_labels else available
        network_matches = [
            label for label in source if network_filter.lower() in label.lower()
        ]
        candidates = network_matches

    hemisphere = str(seed.get("hemisphere", "")).strip()
    if hemisphere:
        source = candidates if candidates else available
        hemisphere_matches = [
            label for label in source if _matches_hemisphere(label, hemisphere)
        ]
        candidates = hemisphere_matches

    return list(dict.fromkeys(candidates))


def _matches_hemisphere(label: str, hemisphere: str) -> bool:
    hemi = hemisphere.lower()
    label_norm = label.lower()
    if hemi in {"lh", "left"}:
        return (
            label_norm.startswith("lh_")
            or label_norm.endswith("-lh")
            or label_norm.endswith("_lh")
            or "left" in label_norm
        )
    if hemi in {"rh", "right"}:
        return (
            label_norm.startswith("rh_")
            or label_norm.endswith("-rh")
            or label_norm.endswith("_rh")
            or "right" in label_norm
        )
    return hemisphere.lower() in label_norm


def _normalize_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", label.lower())
