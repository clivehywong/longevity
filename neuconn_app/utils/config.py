"""
Configuration loading and persistence helpers.

This module keeps the existing YAML-backed workflow, then hydrates that
configuration with repository-specific derived paths and XCP-D defaults from
``neuconn_app/config.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import importlib.util
import json
import os

import jsonschema
import yaml

_PROJECT_CONFIG_PATH = Path(__file__).parent.parent / "config.py"
_PROJECT_CONFIG_SPEC = importlib.util.spec_from_file_location(
    "neuconn_project_config",
    _PROJECT_CONFIG_PATH,
)
if _PROJECT_CONFIG_SPEC is None or _PROJECT_CONFIG_SPEC.loader is None:
    raise ImportError(f"Could not load project config facade: {_PROJECT_CONFIG_PATH}")
project_config = importlib.util.module_from_spec(_PROJECT_CONFIG_SPEC)
_PROJECT_CONFIG_SPEC.loader.exec_module(project_config)


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load, expand, and hydrate the NeuConn configuration."""
    default_config_path = Path(__file__).parent.parent / "config" / "default_config.yaml"

    with open(default_config_path, "r") as f:
        config = yaml.safe_load(f) or {}

    if config_path and Path(config_path).exists():
        with open(config_path, "r") as f:
            user_config = yaml.safe_load(f) or {}
            config = merge_configs(config, user_config)

    config = expand_config_vars(config)
    config = project_config.ensure_project_defaults(config)
    validate_config(config)
    return config


def save_config(config: Dict[str, Any], config_path: str) -> None:
    """Save configuration to YAML."""
    config_path_obj = Path(config_path)
    config_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path_obj, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def validate_config(config: Dict[str, Any]) -> bool:
    """Validate required top-level sections and key paths."""
    required_keys = ["project", "paths", "xcpd", "roi_config"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required config key: {key}")

    project_root = config.get("project_root") or config.get("paths", {}).get("project_root")
    if not project_root:
        raise ValueError("Missing project_root in configuration")

    paths = config.get("paths", {})
    for key in ("bids_dir", "derivatives_dir", "fmriprep_dir", "roi_config_path"):
        if key not in paths:
            raise ValueError(f"Missing required derived path: paths.{key}")

    return True


def merge_configs(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two configuration dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def expand_config_vars(config: Dict[str, Any]) -> Dict[str, Any]:
    """Expand ${var} references and ``~`` values in the config tree."""
    import re

    def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
        flat: Dict[str, Any] = {}
        for key, value in d.items():
            if isinstance(value, str):
                flat[key] = value
                if prefix:
                    flat[f"{prefix}.{key}"] = value
            elif isinstance(value, dict):
                flat.update(_flatten(value, key))
        return flat

    global_flat = _flatten(config)

    def expand_value(value: Any, local_context: Dict[str, Any]) -> Any:
        if isinstance(value, str):
            def replace_var(match: re.Match[str]) -> str:
                var_name = match.group(1)
                if var_name in local_context:
                    return str(local_context[var_name])
                if var_name in global_flat:
                    return str(global_flat[var_name])
                return os.environ.get(var_name, match.group(0))

            value = re.sub(r"\$\{(\w+)\}", replace_var, value)
            return os.path.expanduser(value)

        if isinstance(value, dict):
            return {k: expand_value(v, value) for k, v in value.items()}

        if isinstance(value, list):
            return [expand_value(item, local_context) for item in value]

        return value

    result = expand_value(config, config)
    global_flat = _flatten(result)
    return expand_value(result, result)


def dump_config_json(config: Dict[str, Any], output_path: str) -> None:
    """Write the current config to JSON for debugging or downstream tools."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(config, f, indent=2, sort_keys=True)


def get_default_config() -> Dict[str, Any]:
    """Return the default hydrated configuration."""
    return load_config()


def requires_pipeline_rerun(key_path: str) -> bool:
    """Proxy for path invalidation checks used in the UI."""
    return project_config.requires_pipeline_rerun(key_path)
