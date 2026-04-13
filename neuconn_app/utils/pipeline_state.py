"""
Persistent XCP-D pipeline state for the NeuConn app.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import json


STEP_ORDER = [
    "fmriprep",
    "fd_inspection",
    "fd_gate",
    "xcpd_fc",
    "xcpd_ec",
    "post_xcpd_qc",
    "qc_gate",
    "subject_level",
    "group_level",
]


def _default_state() -> Dict[str, Any]:
    return {
        "steps": {
            step: {
                "status": "not_started",
                "updated_at": None,
                "summary": "",
            }
            for step in STEP_ORDER
        },
        "approvals": {
            "fd_gate": {"approved": False, "approved_at": None},
            "qc_gate": {"approved": False, "approved_at": None},
        },
        "thresholds": {},
        "runs": {},
        "log": [],
    }


def get_pipeline_state_path(config: Dict[str, Any]) -> Path:
    """Location of the pipeline state JSON."""
    bids_dir = Path(config.get("paths", {}).get("bids_dir", "/tmp"))
    state_dir = bids_dir.parent / ".neuconn"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "xcpd_pipeline_state.json"


def load_pipeline_state(config: Dict[str, Any]) -> Dict[str, Any]:
    """Load state from disk, hydrating missing defaults."""
    state_path = get_pipeline_state_path(config)
    state = _default_state()
    if state_path.exists():
        with open(state_path, "r") as f:
            saved = json.load(f)
        state = _merge_dicts(state, saved)
    return state


def save_pipeline_state(config: Dict[str, Any], state: Dict[str, Any]) -> None:
    """Persist pipeline state to disk."""
    state_path = get_pipeline_state_path(config)
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def append_pipeline_log(
    config: Dict[str, Any],
    message: str,
    level: str = "info",
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Append a timestamped log event."""
    current_state = deepcopy(state) if state is not None else load_pipeline_state(config)
    current_state["log"].append(
        {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
        }
    )
    save_pipeline_state(config, current_state)
    return current_state


def set_step_status(
    config: Dict[str, Any],
    step: str,
    status: str,
    summary: str = "",
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update a pipeline step status."""
    current_state = deepcopy(state) if state is not None else load_pipeline_state(config)
    current_state["steps"].setdefault(step, {})
    current_state["steps"][step].update(
        {
            "status": status,
            "summary": summary,
            "updated_at": datetime.now().isoformat(),
        }
    )
    save_pipeline_state(config, current_state)
    return current_state


def set_approval(
    config: Dict[str, Any],
    approval_key: str,
    approved: bool,
    payload: Optional[Dict[str, Any]] = None,
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist an approval gate decision."""
    current_state = deepcopy(state) if state is not None else load_pipeline_state(config)
    current_state["approvals"].setdefault(approval_key, {})
    current_state["approvals"][approval_key]["approved"] = approved
    current_state["approvals"][approval_key]["approved_at"] = (
        datetime.now().isoformat() if approved else None
    )
    if payload:
        current_state["approvals"][approval_key]["payload"] = payload
    save_pipeline_state(config, current_state)
    return current_state


def set_run_info(
    config: Dict[str, Any],
    run_name: str,
    run_info: Dict[str, Any],
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Store metadata for a named run."""
    current_state = deepcopy(state) if state is not None else load_pipeline_state(config)
    current_state["runs"][run_name] = run_info
    save_pipeline_state(config, current_state)
    return current_state


def _merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged
