"""
Atlas catalog and dataset helpers for XCP-D runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional
import json

import nibabel as nib


PROJECT_ATLAS_DATASET_KEY = "longevity"
PROJECT_ATLAS_DATASET_DIRNAME = "xcpd_project_atlases"


@dataclass(frozen=True)
class XCPDAtlasSpec:
    atlas_id: str
    label: str
    description: str
    source_type: str
    source_relpath: Optional[str] = None
    label_relpath: Optional[str] = None
    image_suffix: str = "dseg"
    template: str = "MNI152NLin2009cAsym"
    resolution: str = "02"


ATLAS_ALIASES = {
    "DiFuMo256": "LongevityDiFuMo256",
    "difumo256": "LongevityDiFuMo256",
    "Schaefer200x17": "LongevitySchaefer200",
    "Schaefer200x7": "LongevitySchaefer200",
    "Schaefer200_7net": "LongevitySchaefer200",
    "Schaefer400x7": "LongevitySchaefer400",
    "Schaefer400_7net": "LongevitySchaefer400",
}


def recommended_xcpd_atlases() -> List[str]:
    return ["LongevitySchaefer200", "Tian"]


def get_xcpd_atlas_catalog(config: Dict) -> Dict[str, XCPDAtlasSpec]:
    atlases_dir = Path(config["paths"]["atlases_dir"])
    return {
        "Tian": XCPDAtlasSpec(
            atlas_id="Tian",
            label="Tian (XCP-D built-in)",
            description="Built-in Tian subcortical atlas distributed with XCP-D.",
            source_type="builtin",
        ),
        "LongevityDiFuMo256": XCPDAtlasSpec(
            atlas_id="LongevityDiFuMo256",
            label="DiFuMo 256 (project atlas)",
            description="Project-local DiFuMo 256 atlas sourced from atlases/difumo256_4D.nii.",
            source_type="custom",
            source_relpath="difumo256_4D.nii",
            label_relpath="difumo256.txt",
            image_suffix="probseg",
        ),
        "LongevitySchaefer200": XCPDAtlasSpec(
            atlas_id="LongevitySchaefer200",
            label="Schaefer 200 / 7 networks (project atlas)",
            description="Project-local Schaefer 200 parcel atlas from atlases/schaefer200_7net.nii.",
            source_type="custom",
            source_relpath="schaefer200_7net.nii",
            label_relpath="schaefer200_7net.txt",
        ),
        "LongevitySchaefer400": XCPDAtlasSpec(
            atlas_id="LongevitySchaefer400",
            label="Schaefer 400 / 7 networks (project atlas)",
            description="Project-local Schaefer 400 parcel atlas from atlases/schaefer400_7net.nii.",
            source_type="custom",
            source_relpath="schaefer400_7net.nii",
            label_relpath="schaefer400_7net.txt",
        ),
        "LongevitySchaeferTian200S2": XCPDAtlasSpec(
            atlas_id="LongevitySchaeferTian200S2",
            label="Schaefer-Tian S2 200 / 7 networks (project atlas)",
            description="Combined Schaefer-Tian S2 atlas in MNI152NLin6Asym (FSL MNI152) space.",
            source_type="custom",
            source_relpath="tian/Schaefer2018_200Parcels_7Networks_order_Tian_Subcortex_S2_MNI152NLin6Asym_2mm.nii.gz",
            label_relpath="tian/Schaefer2018_200Parcels_7Networks_order_Tian_Subcortex_S2_label.txt",
            template="MNI152NLin6Asym",
        ),
        "LongevitySchaeferTian400S2": XCPDAtlasSpec(
            atlas_id="LongevitySchaeferTian400S2",
            label="Schaefer-Tian S2 400 / 7 networks (project atlas)",
            description="Combined Schaefer-Tian S2 atlas in MNI152NLin6Asym (FSL MNI152) space.",
            source_type="custom",
            source_relpath="tian/Schaefer2018_400Parcels_7Networks_order_Tian_Subcortex_S2_MNI152NLin6Asym_2mm.nii.gz",
            label_relpath="tian/Schaefer2018_400Parcels_7Networks_order_Tian_Subcortex_S2_label.txt",
            template="MNI152NLin6Asym",
        ),
    }


def normalize_xcpd_atlas_selection(atlas_ids: Optional[Iterable[str]]) -> List[str]:
    normalized: List[str] = []
    for atlas_id in atlas_ids or []:
        text = str(atlas_id).strip()
        if not text:
            continue
        mapped = ATLAS_ALIASES.get(text, text)
        if mapped not in normalized:
            normalized.append(mapped)
    return normalized


def atlas_option_ids(config: Dict, current_values: Optional[Iterable[str]] = None) -> List[str]:
    catalog_ids = list(get_xcpd_atlas_catalog(config).keys())
    current_ids = normalize_xcpd_atlas_selection(current_values)
    for atlas_id in current_ids:
        if atlas_id not in catalog_ids:
            catalog_ids.append(atlas_id)
    return catalog_ids


def format_xcpd_atlas_label(config: Dict, atlas_id: str) -> str:
    spec = get_xcpd_atlas_catalog(config).get(atlas_id)
    return spec.label if spec else atlas_id


def missing_xcpd_atlas_resources(config: Dict, atlas_ids: Optional[Iterable[str]]) -> List[Path]:
    catalog = get_xcpd_atlas_catalog(config)
    atlases_dir = Path(config["paths"]["atlases_dir"])
    missing: List[Path] = []
    for atlas_id in normalize_xcpd_atlas_selection(atlas_ids):
        spec = catalog.get(atlas_id)
        if spec is None or spec.source_type != "custom":
            continue
        for relpath in (spec.source_relpath, spec.label_relpath):
            if not relpath:
                continue
            candidate = atlases_dir / relpath
            if not candidate.exists():
                missing.append(candidate)
    return missing


def build_xcpd_atlas_status_rows(
    config: Dict,
    atlas_ids: Optional[Iterable[str]],
) -> List[Dict[str, str]]:
    catalog = get_xcpd_atlas_catalog(config)
    atlases_dir = Path(config["paths"]["atlases_dir"])
    rows: List[Dict[str, str]] = []
    for atlas_id in normalize_xcpd_atlas_selection(atlas_ids):
        spec = catalog.get(atlas_id)
        if spec is None:
            rows.append(
                {
                    "Atlas": atlas_id,
                    "Source": "Unknown",
                    "Status": "Uncatalogued",
                    "Local file": "-",
                }
            )
            continue
        local_file = "-"
        status = "Built-in"
        if spec.source_type == "custom":
            local_path = atlases_dir / str(spec.source_relpath)
            local_file = str(local_path)
            status = "Ready" if local_path.exists() else "Missing"
        rows.append(
            {
                "Atlas": spec.label,
                "Source": spec.source_type,
                "Status": status,
                "Local file": local_file,
            }
        )
    return rows


def custom_xcpd_atlas_ids(config: Dict, atlas_ids: Optional[Iterable[str]]) -> List[str]:
    catalog = get_xcpd_atlas_catalog(config)
    return [
        atlas_id
        for atlas_id in normalize_xcpd_atlas_selection(atlas_ids)
        if catalog.get(atlas_id) and catalog[atlas_id].source_type == "custom"
    ]


def local_xcpd_atlas_dataset_path(config: Dict) -> Path:
    return Path(config["paths"]["atlases_dir"]) / PROJECT_ATLAS_DATASET_DIRNAME


def remote_xcpd_atlas_dataset_path(remote_base: str) -> str:
    return str(Path(remote_base) / "atlases" / PROJECT_ATLAS_DATASET_DIRNAME)


def ensure_xcpd_atlas_dataset(
    config: Dict,
    atlas_ids: Optional[Iterable[str]],
) -> Optional[Path]:
    selected_custom_ids = custom_xcpd_atlas_ids(config, atlas_ids)
    if not selected_custom_ids:
        return None

    catalog = get_xcpd_atlas_catalog(config)
    atlases_dir = Path(config["paths"]["atlases_dir"])
    dataset_root = local_xcpd_atlas_dataset_path(config)
    dataset_root.mkdir(parents=True, exist_ok=True)

    dataset_description = {
        "Name": "Longevity XCP-D atlas dataset",
        "BIDSVersion": "1.8.0",
        "DatasetType": "derivative",
    }
    with open(dataset_root / "dataset_description.json", "w") as f:
        json.dump(dataset_description, f, indent=2, sort_keys=True)

    for atlas_id in selected_custom_ids:
        spec = catalog[atlas_id]
        source_path = atlases_dir / str(spec.source_relpath)
        label_path = atlases_dir / str(spec.label_relpath)
        if not source_path.exists():
            raise FileNotFoundError(f"Missing XCP-D atlas file: {source_path}")
        if not label_path.exists():
            raise FileNotFoundError(f"Missing XCP-D atlas labels: {label_path}")

        template_dir = dataset_root / f"tpl-{spec.template}"
        template_dir.mkdir(parents=True, exist_ok=True)

        stem = (
            f"tpl-{spec.template}_atlas-{spec.atlas_id}_res-{spec.resolution}_{spec.image_suffix}"
        )
        # Always stage as .nii.gz so XCP-D can read/resample without compression errors.
        image_name = f"{stem}.nii.gz"
        dest_path = template_dir / image_name
        if not dest_path.exists() or dest_path.stat().st_mtime < source_path.stat().st_mtime:
            img = nib.load(source_path)
            nib.save(img, dest_path)

        labels = _load_labels(label_path)
        _write_label_tsv(template_dir / f"{stem}.tsv", labels)
        _write_sidecar_json(template_dir / f"{stem}.json", spec)
        _write_sidecar_json(dataset_root / f"atlas-{spec.atlas_id}_description.json", spec)

    return dataset_root


def atlas_cli_dataset_args(
    config: Dict,
    atlas_ids: Optional[Iterable[str]],
    dataset_root: Optional[str] = None,
) -> List[str]:
    if not custom_xcpd_atlas_ids(config, atlas_ids):
        return []
    root = dataset_root or str(local_xcpd_atlas_dataset_path(config))
    return ["--datasets", f"{PROJECT_ATLAS_DATASET_KEY}={root}"]


def _full_suffix(path: Path) -> str:
    return "".join(path.suffixes)


def _load_labels(label_path: Path) -> List[Dict[str, str]]:
    lines = [line.strip() for line in label_path.read_text(errors="ignore").splitlines() if line.strip()]
    labels: List[Dict[str, str]] = []
    idx = 0
    while idx < len(lines):
        current = lines[idx]
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        parts = next_line.split()
        if parts and parts[0].isdigit():
            labels.append({"index": parts[0], "name": current})
            idx += 2
            continue
        labels.append({"index": str(len(labels) + 1), "name": current})
        idx += 1
    return labels


def _write_label_tsv(output_path: Path, labels: List[Dict[str, str]]) -> None:
    with open(output_path, "w") as f:
        f.write("index\tname\n")
        for row in labels:
            name = str(row["name"]).replace("\t", " ").strip()
            f.write(f"{row['index']}\t{name}\n")


def _write_sidecar_json(output_path: Path, spec: XCPDAtlasSpec) -> None:
    payload = {
        "Name": spec.atlas_id,
        "Description": spec.description,
    }
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
