"""
ROI configuration helpers for the XCP-D pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import json


VALID_ROI_TYPES = {"atlas_parcels", "mni_sphere", "nifti_mask"}


@dataclass
class AtlasLabel:
    """Single atlas label definition."""

    label: str
    index: int
    rgb: List[int]


def load_roi_config(config_path: Path) -> Dict[str, Any]:
    """Load ROI JSON from disk."""
    with open(config_path, "r") as f:
        roi_config = json.load(f)
    validate_roi_config(roi_config)
    return roi_config


def save_roi_config(roi_config: Dict[str, Any], config_path: Path) -> None:
    """Persist ROI JSON to disk."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    validate_roi_config(roi_config)
    with open(config_path, "w") as f:
        json.dump(roi_config, f, indent=2, sort_keys=False)


def validate_roi_config(roi_config: Dict[str, Any]) -> None:
    """Validate the minimal ROI config contract."""
    if "rois" not in roi_config or not isinstance(roi_config["rois"], list):
        raise ValueError("roi_config.json must contain a 'rois' list")

    roi_ids = set()
    for roi in roi_config["rois"]:
        roi_id = roi.get("id")
        if not roi_id:
            raise ValueError("Every ROI must define an 'id'")
        if roi_id in roi_ids:
            raise ValueError(f"Duplicate ROI id: {roi_id}")
        roi_ids.add(roi_id)

        roi_type = roi.get("type")
        if roi_type not in VALID_ROI_TYPES:
            raise ValueError(f"Invalid ROI type for {roi_id}: {roi_type}")

        if roi_type == "atlas_parcels":
            if not roi.get("parcel_labels") and not roi.get("network_filter"):
                raise ValueError(
                    f"atlas_parcels ROI {roi_id} needs parcel_labels or network_filter"
                )
        elif roi_type == "mni_sphere":
            coords = roi.get("mni_coords")
            if not isinstance(coords, list) or len(coords) != 3:
                raise ValueError(f"mni_sphere ROI {roi_id} needs 3 MNI coordinates")
        elif roi_type == "nifti_mask":
            if not roi.get("mask_path"):
                raise ValueError(f"nifti_mask ROI {roi_id} needs mask_path")


def parse_combined_atlas_label_file(label_file: Path) -> List[AtlasLabel]:
    """
    Parse the Tian label file.

    The distributed file alternates between a label line and an RGBA line.
    """
    with open(label_file, "r") as f:
        lines = [line.strip() for line in f if line.strip()]

    if len(lines) % 2 != 0:
        raise ValueError(
            f"Invalid atlas label file format in {label_file}: expected alternating label/RGBA lines."
        )

    labels: List[AtlasLabel] = []
    for idx in range(0, len(lines), 2):
        label = lines[idx]
        rgba_parts = lines[idx + 1].split()
        if len(rgba_parts) < 4:
            raise ValueError(
                f"Invalid RGBA/index line for atlas label '{label}' in {label_file}: {lines[idx + 1]}"
            )
        rgba = [int(value) for value in rgba_parts]
        labels.append(AtlasLabel(label=label, index=rgba[0], rgb=rgba[1:4]))
    return labels


def atlas_label_names(label_file: Path) -> List[str]:
    """Return all atlas label names."""
    return [entry.label for entry in parse_combined_atlas_label_file(label_file)]


def filter_labels(
    labels: Iterable[AtlasLabel],
    network_filter: Optional[str] = None,
    hemisphere: Optional[str] = None,
) -> List[AtlasLabel]:
    """Filter atlas labels by network and/or hemisphere."""
    filtered = list(labels)
    if network_filter:
        filtered = [label for label in filtered if network_filter in label.label]
    if hemisphere:
        filtered = [label for label in filtered if _matches_hemisphere(label.label, hemisphere)]
    return filtered


def _matches_hemisphere(label: str, hemisphere: str) -> bool:
    normalized = hemisphere.strip().lower()
    label_norm = label.lower()

    if normalized in {"lh", "left"}:
        return (
            "_lh_" in label_norm
            or label_norm.endswith("-lh")
            or label_norm.endswith("_lh")
            or "left" in label_norm
        )
    if normalized in {"rh", "right"}:
        return (
            "_rh_" in label_norm
            or label_norm.endswith("-rh")
            or label_norm.endswith("_rh")
            or "right" in label_norm
        )
    return normalized in label_norm


def seed_rois(roi_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return ROIs marked for seed-based analyses."""
    return [roi for roi in roi_config["rois"] if roi.get("use_as_seed", False)]
