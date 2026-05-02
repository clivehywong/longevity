"""Local serial executor for subject-level connectivity scripts.

Designed for the "Run target = Local" path on the Submit Connectivity pages.
No parallelism: one (subject, session) at a time, sequential subprocess calls.

Why subprocess (not in-process import):
- Isolates memory: nibabel + numpy can hold gigabytes per BOLD load; subprocess
  release on exit prevents Streamlit-server bloat over a long run.
- Robust to per-subject crashes: a segfault in one subject doesn't kill the UI.
- Mirrors the HPC sbatch model — same script, same CLI.

Progress is written to JSON so the UI can resume after a Streamlit rerun.

Schema (``<state_dir>/connectivity_local_runs/<run_id>.json``)::

    {
      "run_id":         "...",
      "analysis":       "seed_connectivity" | "network_connectivity",
      "started_at":     ISO8601,
      "ended_at":       ISO8601 | null,
      "status":         "running" | "completed" | "failed" | "cancelled",
      "total":          int,
      "completed":      int,
      "failed":         int,
      "current":        "sub-XXX/ses-XX" | null,
      "items": [
        {"subject": "sub-033", "session": "ses-01",
         "status": "pending|running|completed|failed",
         "duration_sec": float | null, "error": str | null}
      ],
      "command_template": ["python", "...", "--subject", "{sub}", ...]
    }
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

# Path to the app-resident scripts directory.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "connectivity"
SEED_SCRIPT = _SCRIPTS_DIR / "compute_seed_connectivity_xcpd.py"
NETWORK_SCRIPT = _SCRIPTS_DIR / "compute_network_connectivity_xcpd.py"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class LocalConnectivityRunner:
    """Serial local executor with progress + resume support."""

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir) / "connectivity_local_runs"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    # ---- state helpers --------------------------------------------------- #

    def state_file(self, run_id: str) -> Path:
        return self.state_dir / f"{run_id}.json"

    def load_state(self, run_id: str) -> Optional[Dict[str, Any]]:
        path = self.state_file(run_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_state(self, state: Dict[str, Any]) -> None:
        path = self.state_file(state["run_id"])
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(path)

    def list_runs(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for p in sorted(self.state_dir.glob("*.json"), reverse=True):
            try:
                rows.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return rows

    # ---- planning -------------------------------------------------------- #

    @staticmethod
    def plan_seed(
        subjects_sessions: Dict[str, List[str]],
        seeds: Sequence[str],
        measures: Sequence[str],
        bids_root: str,
        out_root: str,
        pipeline: str = "fc",
        bold_variant: str = "denoisedSmoothed",
        tr: float = 0.8,
        force: bool = False,
    ) -> List[Dict[str, Any]]:
        """Build a flat list of work items (subject,session) sharing seeds+measures."""
        items: List[Dict[str, Any]] = []
        for sub, sessions in subjects_sessions.items():
            for ses in sessions:
                items.append({
                    "subject": sub,
                    "session": ses,
                    "seeds": list(seeds),
                    "measures": list(measures),
                    "bids_root": bids_root,
                    "out_root": out_root,
                    "pipeline": pipeline,
                    "bold_variant": bold_variant,
                    "tr": tr,
                    "force": force,
                    "status": "pending",
                    "duration_sec": None,
                    "error": None,
                })
        return items

    @staticmethod
    def build_seed_command(item: Dict[str, Any]) -> List[str]:
        cmd = [
            sys.executable, str(SEED_SCRIPT),
            "--bids-root", str(item["bids_root"]),
            "--subject", item["subject"],
            "--session", item["session"],
            "--pipeline", item["pipeline"],
            "--measures", ",".join(item["measures"]),
            "--bold", item["bold_variant"],
            "--out-root", item["out_root"],
            "--tr", str(item["tr"]),
        ]
        for s in item["seeds"]:
            cmd.extend(["--seed", s])
        if item.get("force"):
            cmd.append("--force")
        return cmd

    # ---- execution ------------------------------------------------------- #

    def start_run(
        self,
        analysis: str,
        items: List[Dict[str, Any]],
        run_id: Optional[str] = None,
    ) -> str:
        """Initialize state file. Caller drives execution via run_one_pending()."""
        run_id = run_id or f"local-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        state = {
            "run_id": run_id,
            "analysis": analysis,
            "started_at": _now(),
            "ended_at": None,
            "status": "running",
            "total": len(items),
            "completed": 0,
            "failed": 0,
            "current": None,
            "items": items,
        }
        self.save_state(state)
        return run_id

    def run_one_pending(
        self,
        run_id: str,
        log_callback: Optional[Callable[[str], None]] = None,
        timeout: int = 3600,
    ) -> Optional[Dict[str, Any]]:
        """Run the next pending item. Returns the item dict (with updated status), or None when done."""
        state = self.load_state(run_id)
        if state is None or state["status"] in {"cancelled", "completed"}:
            return None

        idx = next((i for i, it in enumerate(state["items"]) if it["status"] == "pending"), None)
        if idx is None:
            state["status"] = "completed" if state["failed"] == 0 else "failed"
            state["ended_at"] = _now()
            state["current"] = None
            self.save_state(state)
            return None

        item = state["items"][idx]
        item["status"] = "running"
        state["current"] = f"{item['subject']}/{item['session']}"
        self.save_state(state)

        if state["analysis"] == "seed_connectivity":
            cmd = self.build_seed_command(item)
        else:
            raise ValueError(f"Unsupported analysis: {state['analysis']}")

        if log_callback:
            log_callback(f"$ {' '.join(shlex.quote(c) for c in cmd)}")

        t0 = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            dur = time.time() - t0
            item["duration_sec"] = round(dur, 2)
            if proc.returncode == 0:
                item["status"] = "completed"
                state["completed"] += 1
                if log_callback:
                    tail = (proc.stdout or "").strip().splitlines()[-3:]
                    for line in tail:
                        log_callback(f"  {line}")
                    log_callback(f"  ✓ {item['subject']}/{item['session']} in {dur:.1f}s")
            else:
                item["status"] = "failed"
                item["error"] = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()[-500:]
                state["failed"] += 1
                if log_callback:
                    log_callback(f"  ✗ {item['subject']}/{item['session']} FAILED ({proc.returncode}): {item['error'][:200]}")
        except subprocess.TimeoutExpired:
            item["status"] = "failed"
            item["error"] = f"Timeout after {timeout}s"
            item["duration_sec"] = round(time.time() - t0, 2)
            state["failed"] += 1
            if log_callback:
                log_callback(f"  ✗ {item['subject']}/{item['session']} TIMEOUT")
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = str(exc)[:500]
            item["duration_sec"] = round(time.time() - t0, 2)
            state["failed"] += 1
            if log_callback:
                log_callback(f"  ✗ {item['subject']}/{item['session']} ERROR: {exc}")

        # Was it the last one?
        any_pending = any(it["status"] == "pending" for it in state["items"])
        if not any_pending:
            state["status"] = "completed" if state["failed"] == 0 else "failed"
            state["ended_at"] = _now()
            state["current"] = None

        self.save_state(state)
        return item

    def run_all(
        self,
        run_id: str,
        log_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        timeout: int = 3600,
    ) -> Dict[str, Any]:
        """Block-run all pending items serially. Returns final state."""
        while True:
            item = self.run_one_pending(run_id, log_callback=log_callback, timeout=timeout)
            if item is None:
                break
            state = self.load_state(run_id) or {}
            if progress_callback:
                progress_callback(
                    state.get("completed", 0) + state.get("failed", 0),
                    state.get("total", 0),
                    f"{item['subject']}/{item['session']} ({item['status']})",
                )
        return self.load_state(run_id) or {}

    def cancel(self, run_id: str) -> bool:
        state = self.load_state(run_id)
        if not state:
            return False
        if state["status"] in {"completed", "failed", "cancelled"}:
            return False
        state["status"] = "cancelled"
        state["ended_at"] = _now()
        self.save_state(state)
        return True
