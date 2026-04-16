"""
Project-wide configuration facade for the NeuConn XCP-D pipeline.

This module layers the repository-specific project structure and runtime
defaults on top of the existing YAML-backed configuration system in
``utils.config``.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import os


APP_DIR = Path(__file__).resolve().parent
DEFAULT_PROJECT_ROOT = APP_DIR.parent
ATLAS_LABEL_FILENAME = "Schaefer2018_200Parcels_7Networks_order_Tian_Subcortex_S2_label.txt"
DEFAULT_XCPD_IMAGE = "~/software/xcp-d-26.0.2.sif"

RERUN_REQUIRED_KEYS = {
    "xcpd.fc.fd_thresh",
    "xcpd.fc.min_time",
    "xcpd.fc.output_type",
    "xcpd.fc.output_layout",
    "xcpd.fc.motion_filter_type",
    "xcpd.fc.band_stop_min",
    "xcpd.fc.band_stop_max",
    "xcpd.fc.high_pass",
    "xcpd.fc.low_pass",
    "xcpd.fc.smoothing",
    "xcpd.fc.atlases",
    "xcpd.fc.nuisance_regressors",
    "xcpd.fc.despike",
    "xcpd.fc.bandpass_filter",
    "xcpd.fc_gsr.fd_thresh",
    "xcpd.fc_gsr.min_time",
    "xcpd.fc_gsr.output_type",
    "xcpd.fc_gsr.output_layout",
    "xcpd.fc_gsr.motion_filter_type",
    "xcpd.fc_gsr.band_stop_min",
    "xcpd.fc_gsr.band_stop_max",
    "xcpd.fc_gsr.high_pass",
    "xcpd.fc_gsr.low_pass",
    "xcpd.fc_gsr.smoothing",
    "xcpd.fc_gsr.atlases",
    "xcpd.fc_gsr.nuisance_regressors",
    "xcpd.fc_gsr.despike",
    "xcpd.fc_gsr.bandpass_filter",
    "xcpd.ec.fd_thresh",
    "xcpd.ec.min_time",
    "xcpd.ec.output_type",
    "xcpd.ec.output_layout",
    "xcpd.ec.motion_filter_type",
    "xcpd.ec.band_stop_min",
    "xcpd.ec.band_stop_max",
    "xcpd.ec.high_pass",
    "xcpd.ec.low_pass",
    "xcpd.ec.smoothing",
    "xcpd.ec.atlases",
    "xcpd.ec.nuisance_regressors",
    "xcpd.ec.despike",
    "xcpd.ec.bandpass_filter",
    "roi_config.path",
    "subject_exclusion.mean_fd_threshold",
    "subject_exclusion.min_scan_time",
}


def _setdefault_nested(config: Dict[str, Any], path: List[str], value: Any) -> None:
    current: Dict[str, Any] = config
    for key in path[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current.setdefault(path[-1], value)


def _infer_root_from_derivatives_path(derivatives_path: Path) -> Optional[Path]:
    if derivatives_path.name == "derivatives":
        return derivatives_path.parent
    if derivatives_path.name == "preprocessing" and derivatives_path.parent.name == "derivatives":
        return derivatives_path.parent.parent
    if (derivatives_path / "derivatives").exists() and (derivatives_path / "bids").exists():
        return derivatives_path
    return None


def get_project_root(config: Optional[Dict[str, Any]] = None) -> Path:
    """Return the configured project root or the repository root."""
    if config:
        explicit_root = (
            config.get("project_root")
            or config.get("paths", {}).get("project_root")
            or config.get("project", {}).get("root")
        )
        default_root = Path(os.path.expanduser(str(DEFAULT_PROJECT_ROOT))).resolve()

        bids_dir = config.get("paths", {}).get("bids_dir")
        bids_parent: Optional[Path] = None
        if bids_dir and "${" not in str(bids_dir):
            bids_path = Path(os.path.expanduser(str(bids_dir))).resolve()
            if bids_path.name == "bids":
                bids_parent = bids_path.parent

        derivatives_dir = config.get("paths", {}).get("derivatives_dir")
        derivatives_parent: Optional[Path] = None
        if derivatives_dir and "${" not in str(derivatives_dir):
            derivatives_path = Path(os.path.expanduser(str(derivatives_dir))).resolve()
            derivatives_parent = _infer_root_from_derivatives_path(derivatives_path)

        if explicit_root:
            resolved_root = Path(os.path.expanduser(str(explicit_root))).resolve()
            if bids_parent and bids_parent != resolved_root and resolved_root == Path(os.path.expanduser("~/neuconn_project")).resolve():
                return bids_parent
            if derivatives_parent and derivatives_parent != resolved_root and resolved_root == Path(os.path.expanduser("~/neuconn_project")).resolve():
                return derivatives_parent
            return resolved_root

        if bids_parent:
            return bids_parent
        if derivatives_parent:
            return derivatives_parent
        return default_root
    return DEFAULT_PROJECT_ROOT.resolve()


def derive_project_paths(project_root: Path) -> Dict[str, str]:
    """Derive all project paths from PROJECT_ROOT."""
    derivatives = project_root / "derivatives"
    preprocessing = derivatives / "preprocessing"
    fmriprep = preprocessing / "fmriprep"
    xcpd = preprocessing / "xcpd"
    subject_level = derivatives / "subject_level"
    group_level = derivatives / "group_level"
    qc = derivatives / "qc"
    app_root = project_root / "neuconn_app"
    atlas_resources = app_root / "resources"

    return {
        "project_root": str(project_root),
        "bids_dir": str(project_root / "bids"),
        "neuconn_app_dir": str(app_root),
        "derivatives_dir": str(derivatives),
        "preprocessing_dir": str(preprocessing),
        "fmriprep_dir": str(fmriprep),
        "legacy_fmriprep_dir": str(project_root / "fmriprep"),
        "xcpd_dir": str(xcpd),
        "xcpd_fc_dir": str(xcpd / "fc"),
        "xcpd_fc_gsr_dir": str(xcpd / "fc_gsr"),
        "xcpd_ec_dir": str(xcpd / "ec"),
        "subject_level_dir": str(subject_level),
        "subject_level_fc_dir": str(subject_level / "fc"),
        "subject_level_fc_gsr_dir": str(subject_level / "fc_gsr"),
        "subject_level_ec_dir": str(subject_level / "ec"),
        "group_level_dir": str(group_level),
        "group_level_fc_dir": str(group_level / "fc"),
        "group_level_fc_gsr_dir": str(group_level / "fc_gsr"),
        "group_level_ec_dir": str(group_level / "ec"),
        "qc_dir": str(qc),
        "fd_inspection_dir": str(qc / "fd_inspection"),
        "xcpd_fc_qc_dir": str(qc / "xcpd_fc"),
        "xcpd_fc_gsr_qc_dir": str(qc / "xcpd_fc_gsr"),
        "xcpd_ec_qc_dir": str(qc / "xcpd_ec"),
        "excluded_dir": str(project_root / "bids_excluded"),
        "atlases_dir": str(project_root / "atlases"),
        "atlas_resources_dir": str(atlas_resources),
        "roi_config_path": str(app_root / "roi_config.json"),
        "atlas_label_file": str(atlas_resources / ATLAS_LABEL_FILENAME),
        "temp_dir": "/tmp/neuconn",
        "cache_dir": "~/.cache/neuconn",
    }


def default_bind_mounts(project_root: Path) -> List[str]:
    """Default bind mounts for Singularity/Apptainer execution."""
    return [
        str(project_root),
        str(project_root / "bids"),
        str(project_root / "derivatives"),
        str(project_root / "atlases"),
        str(Path.home() / "software"),
    ]


def _resolve_template_value(value: str, derived_paths: Dict[str, str]) -> str:
    resolved = os.path.expanduser(value)
    for key, replacement in derived_paths.items():
        resolved = resolved.replace(f"${{{key}}}", replacement)
    resolved = resolved.replace("${project_root}", derived_paths["project_root"])
    return resolved


def _default_xcpd_section() -> Dict[str, Any]:
    common = {
        "mode": "linc",
        "motion_filter_type": "notch",
        "band_stop_min": 12,
        "band_stop_max": 18,
        "high_pass": 0.01,
        "smoothing": 6.0,
        "atlases": ["LongevitySchaefer200", "Tian"],
        "input_type": "fmriprep",
        "file_format": "cifti",
        "report_output_level": "session",
        "output_layout": "bids",
        "clean_workdir": False,
        "output_run_wise_correlations": True,
        "dummy_scans": "auto",
        "despike": True,
        "bandpass_filter": True,
        "head_radius": "auto",
        "min_coverage": 0.5,
    }
    fc_common = {
        **common,
        "nuisance_regressors": "acompcor",
        "fd_thresh": 0.3,
        "min_time": 240,
        "low_pass": 0.08,
        "output_type": "censored",
        "file_format": "nifti",
    }
    return {
        "singularity_image_path": DEFAULT_XCPD_IMAGE,
        "singularity_bind_mounts": [],
        # FC: no GSR (conservative default)
        "fc": fc_common,
        # FC-GSR: same parameters with global signal regression for comparison
        "fc_gsr": {**fc_common, "nuisance_regressors": "36P"},
        # EC: no GSR, no smoothing, wider bandpass, longer minimum scan time
        "ec": {
            **common,
            "nuisance_regressors": "acompcor",
            "fd_thresh": 0.5,
            "min_time": 300,
            "low_pass": 0.10,
            "smoothing": 0.0,
            "output_type": "interpolated",
            "file_format": "nifti",
        },
    }


def ensure_project_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    """Hydrate the YAML-backed config with project-derived defaults."""
    hydrated = deepcopy(config)
    project_root = get_project_root(hydrated)

    hydrated["project_root"] = str(project_root)
    hydrated.setdefault("project", {})
    hydrated["project"]["root"] = str(project_root)

    paths = hydrated.setdefault("paths", {})
    derived_paths = derive_project_paths(project_root)
    for key, value in derived_paths.items():
        paths[key] = value

    hydrated.setdefault("roi_config", {})
    hydrated["roi_config"].setdefault("path", derived_paths["roi_config_path"])
    hydrated["roi_config"].setdefault("label_file", derived_paths["atlas_label_file"])
    hydrated["roi_config"].setdefault(
        "atlas",
        {
            "combined": "Schaefer2018_200Parcels_7Networks_Tian_S2",
            "n_cortical": 200,
            "n_subcortical": 32,
            "n_total": 232,
        },
    )

    hydrated.setdefault("external_tools", {})
    hydrated["external_tools"].setdefault("julia_executable", "julia")
    hydrated["external_tools"].setdefault("matlab_executable", "matlab")
    hydrated["external_tools"].setdefault("jgranger_toolbox_root", "")
    hydrated["external_tools"].setdefault(
        "rdcm_package", "RegressionDynamicCausalModeling"
    )
    hydrated["external_tools"].setdefault(
        "sdcm_package", "SpectralDynamicCausalModeling"
    )

    hydrated.setdefault("subject_exclusion", {})
    hydrated["subject_exclusion"].setdefault("mean_fd_threshold", 0.5)
    hydrated["subject_exclusion"].setdefault("min_scan_time", 100)

    hydrated.setdefault("ec_methods", {})
    hydrated["ec_methods"].setdefault("pairwise_granger", True)
    hydrated["ec_methods"].setdefault("joint_granger", True)
    hydrated["ec_methods"].setdefault("rdcm", True)
    hydrated["ec_methods"].setdefault("spectral_dcm", True)
    hydrated["ec_methods"].setdefault("full_granger_matrix", False)
    hydrated["ec_methods"].setdefault("granger_lag_order", 1)

    hydrated.setdefault("study_design", {})
    hydrated["study_design"].setdefault("group_variable", "Group")
    hydrated["study_design"].setdefault("time_variable", "Time")
    hydrated["study_design"].setdefault("session_pre", "ses-01")
    hydrated["study_design"].setdefault("session_post", "ses-02")
    hydrated["study_design"].setdefault("covariates", ["Age", "Sex"])
    hydrated["study_design"].setdefault("nuisance_regressors", ["MeanFD"])
    hydrated["study_design"].setdefault(
        "primary_contrast", "Group × Time interaction"
    )

    hydrated.setdefault("xcpd", {})
    xcpd = hydrated["xcpd"]
    defaults = _default_xcpd_section()
    for key, value in defaults.items():
        if isinstance(value, dict):
            xcpd.setdefault(key, {})
            for nested_key, nested_value in value.items():
                xcpd[key].setdefault(nested_key, nested_value)
        else:
            xcpd.setdefault(key, value)

    # Heal None mode values: YAML `mode: none` (unquoted) is parsed as Python None,
    # which str(None)="None" causes XCP-D to fall into "none" mode unexpectedly.
    _VALID_XCPD_MODES = {"linc", "abcd", "hbcd", "nichart", "none"}
    for _pipeline_key in ("fc", "fc_gsr", "ec"):
        if _pipeline_key in xcpd and isinstance(xcpd[_pipeline_key], dict):
            _current_mode = xcpd[_pipeline_key].get("mode")
            if not _current_mode or _current_mode not in _VALID_XCPD_MODES:
                xcpd[_pipeline_key]["mode"] = "linc"

    if not xcpd.get("singularity_bind_mounts"):
        xcpd["singularity_bind_mounts"] = default_bind_mounts(project_root)
    else:
        bind_mounts = [
            _resolve_template_value(str(bind_mount), derived_paths)
            for bind_mount in xcpd["singularity_bind_mounts"]
        ]
        for required in default_bind_mounts(project_root):
            if required not in bind_mounts:
                bind_mounts.append(required)
        xcpd["singularity_bind_mounts"] = list(dict.fromkeys(bind_mounts))

    xcpd["singularity_image_path"] = _resolve_template_value(
        str(xcpd.get("singularity_image_path", DEFAULT_XCPD_IMAGE)),
        derived_paths,
    )

    hydrated.setdefault("pipeline", {})
    hydrated["pipeline"].setdefault(
        "steps",
        [
            "fmriprep",
            "fd_inspection",
            "xcpd_fc",
            "xcpd_fc_gsr",
            "xcpd_ec",
            "post_xcpd_qc",
            "subject_level",
            "group_level",
        ],
    )

    hydrated.setdefault("fmriprep", {})
    hydrated["fmriprep"].setdefault("legacy_symlink", True)

    _setdefault_nested(
        hydrated,
        ["hpc", "singularity_images", "xcp_d"],
        os.path.expanduser(DEFAULT_XCPD_IMAGE),
    )
    _setdefault_nested(hydrated, ["hpc", "singularity_images", "fmripost_aroma"], "")
    _setdefault_nested(hydrated, ["hpc", "singularity_images", "qsiprep"], "")
    _setdefault_nested(hydrated, ["hpc", "singularity_images", "qsirecon"], "")
    _setdefault_nested(hydrated, ["hpc", "slurm", "xcpd_cpus"], 16)
    _setdefault_nested(hydrated, ["hpc", "slurm", "xcpd_memory"], "64GB")
    _setdefault_nested(hydrated, ["hpc", "slurm", "xcpd_time"], "12:00:00")

    # software.singularity_images: local image paths for all tools
    software = hydrated.setdefault("software", {})
    simg = software.setdefault("singularity_images", {})
    simg.setdefault("fmriprep", os.path.expanduser("~/software/fmriprep-25.1.4.simg"))
    simg.setdefault("xcp_d", os.path.expanduser(DEFAULT_XCPD_IMAGE))
    simg.setdefault("fmripost_aroma", "")
    simg.setdefault("qsiprep", "")
    simg.setdefault("qsirecon", "")
    simg.setdefault("freesurfer_license", os.path.expanduser("~/freesurfer/license.txt"))
    if not software.get("singularity_bind_mounts"):
        software["singularity_bind_mounts"] = default_bind_mounts(project_root)
    else:
        bind_mounts = [
            _resolve_template_value(str(m), derived_paths)
            for m in software["singularity_bind_mounts"]
        ]
        for required in default_bind_mounts(project_root):
            if required not in bind_mounts:
                bind_mounts.append(required)
        software["singularity_bind_mounts"] = list(dict.fromkeys(bind_mounts))
    # Expand ~ in local image paths
    for key in ("fmriprep", "xcp_d", "fmripost_aroma", "qsiprep", "qsirecon", "freesurfer_license"):
        val = simg.get(key, "")
        if val:
            simg[key] = os.path.expanduser(str(val))

    return hydrated


def requires_pipeline_rerun(key_path: str) -> bool:
    """Return True if a config path requires invalidating XCP-D outputs."""
    return key_path in RERUN_REQUIRED_KEYS
