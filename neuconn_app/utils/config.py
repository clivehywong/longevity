"""
Configuration Management

Load, validate, and manage YAML configuration files:
- load_config(): Load config with validation
- save_config(): Save config to file
- merge_configs(): Deep merge of config dicts
- validate_config(): Validate against JSON schema
- get_default_config(): Return default configuration

Configuration precedence:
1. Default config (config/default_config.yaml)
2. User config (~/neuconn_projects/*.yaml)
3. Runtime overrides (from Settings page)

Implementation: Phase 1
"""

from pathlib import Path
from typing import Dict, Optional
import yaml
import json
import jsonschema


def load_config(config_path: Optional[str] = None) -> Dict:
    """
    Load and validate configuration.

    Args:
        config_path: Path to user config file (optional)

    Returns:
        Validated configuration dictionary
    """
    # Load default config
    default_config_path = Path(__file__).parent.parent / "config" / "default_config.yaml"

    with open(default_config_path, 'r') as f:
        config = yaml.safe_load(f)

    # Override with user config if provided
    if config_path and Path(config_path).exists():
        with open(config_path, 'r') as f:
            user_config = yaml.safe_load(f)
            config = merge_configs(config, user_config)

    # Expand environment variables in paths
    config = expand_config_vars(config)

    return config


def save_config(config: Dict, config_path: str) -> None:
    """
    Save configuration to YAML file.

    Args:
        config: Configuration dictionary
        config_path: Destination path
    """
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def validate_config(config: Dict) -> bool:
    """
    Validate configuration against JSON schema.

    Args:
        config: Configuration dictionary

    Returns:
        True if valid

    Raises:
        jsonschema.ValidationError if invalid
    """
    # For now, basic validation - JSON schema in future
    required_keys = ['project', 'paths']
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required config key: {key}")
    return True


def merge_configs(base: Dict, override: Dict) -> Dict:
    """Deep merge two configuration dictionaries."""
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value

    return result


def expand_config_vars(config: Dict) -> Dict:
    """Expand ${variable} references in config values.

    Variables are resolved from a flat lookup table built from ALL scalar
    values in the config (not just the top level). Keys are the leaf key names,
    with section-prefixed names taking lower priority (e.g. 'derivatives_dir'
    can be referenced as ${derivatives_dir} even though it lives under 'paths').

    Resolution order per ${var}:
    1. Sibling keys in the same section (for remote_paths ${base} etc.)
    2. Flat top-level keys
    3. All nested scalar keys (allows ${derivatives_dir} from paths.derivatives_dir)
    4. OS environment variables
    5. Leave unchanged if not found
    """
    import re
    import os

    def _flatten(d: Dict, prefix: str = "") -> Dict:
        """Build flat key->value mapping from nested dict."""
        flat = {}
        for k, v in d.items():
            if isinstance(v, str):
                flat[k] = v
                if prefix:
                    flat[f"{prefix}.{k}"] = v
            elif isinstance(v, dict):
                flat.update(_flatten(v, k))
        return flat

    # Build a flat lookup from all string values in the config
    global_flat = _flatten(config)

    def expand_value(value, local_context: Dict):
        """Expand a single value. local_context provides sibling keys."""
        if isinstance(value, str):
            def replace_var(match):
                var_name = match.group(1)
                # 1. Sibling keys (e.g. ${base} within remote_paths)
                if var_name in local_context:
                    return str(local_context[var_name])
                # 2. Global flat lookup (all nested keys by leaf name)
                if var_name in global_flat:
                    return str(global_flat[var_name])
                # 3. OS environment
                return os.environ.get(var_name, match.group(0))

            value = re.sub(r'\$\{(\w+)\}', replace_var, value)
            # Expand ~ for home directory
            value = os.path.expanduser(value)

        elif isinstance(value, dict):
            # Pass this dict as local context so siblings resolve each other
            return {k: expand_value(v, value) for k, v in value.items()}

        elif isinstance(value, list):
            return [expand_value(item, local_context) for item in value]

        return value

    # Two passes: first pass resolves most vars; second pass resolves
    # any vars whose values themselves contained ${...} references
    result = expand_value(config, config)
    # Rebuild flat after first pass (resolves chains like fmriprep_dir -> derivatives_dir -> /path)
    global_flat = _flatten(result)
    return expand_value(result, result)
