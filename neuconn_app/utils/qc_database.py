"""
QC Database - Persistent QC Status Storage

Stores QC ratings and notes for each scan in JSON format.

Storage location: <bids_dir>/../qc_status.json

Format:
{
  "sub-033_ses-01_run-01_T1w": {
    "status": "Pass",
    "notes": "Good quality",
    "timestamp": "2026-04-07T10:30:00",
    "reviewer": "user"
  }
}
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional


_QC_STATUS_MAP = {
    'pass': '✅ Pass',
    'review': '⚠️ Review',
    'fail': '❌ Fail',
}


def _normalize_qc_entry(entry: Dict) -> Dict:
    normalized = dict(entry)
    status = normalized.get('status')
    if isinstance(status, str):
        normalized['status'] = _QC_STATUS_MAP.get(status.strip().lower(), status)
    if 'reason' in normalized and 'notes' not in normalized:
        normalized['notes'] = normalized['reason']
    if 'updated_at' in normalized and 'timestamp' not in normalized:
        normalized['timestamp'] = normalized['updated_at']
    normalized.setdefault('reviewer', 'user')
    return normalized


def get_qc_database_path(bids_dir: Path) -> Path:
    """Get path to QC database JSON file."""
    return bids_dir.parent / "qc_status.json"


def load_qc_database(bids_dir: Path) -> Dict:
    """Load QC database from JSON file."""
    db_path = get_qc_database_path(bids_dir)

    if db_path.exists():
        with open(db_path, 'r') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {
                key: _normalize_qc_entry(value) if isinstance(value, dict) else value
                for key, value in data.items()
            }
        return {}
    else:
        return {}


def save_qc_database(bids_dir: Path, qc_db: Dict) -> None:
    """Save QC database to JSON file."""
    db_path = get_qc_database_path(bids_dir)

    with open(db_path, 'w') as f:
        json.dump(qc_db, f, indent=2, sort_keys=True)


def get_qc_status(qc_db: Dict, subject: str, session: str, run: str, modality: str) -> Optional[Dict]:
    """Get QC status for a specific scan."""
    key = f"{subject}_{session}_{run}_{modality}"
    return qc_db.get(key)


def set_qc_status(qc_db: Dict, subject: str, session: str, run: str, modality: str,
                  status: str, notes: str = "") -> Dict:
    """Set QC status for a specific scan."""
    key = f"{subject}_{session}_{run}_{modality}"

    qc_db[key] = {
        'status': status,
        'notes': notes,
        'timestamp': datetime.now().isoformat(),
        'reviewer': 'user'
    }

    return qc_db


def get_qc_summary(qc_db: Dict) -> Dict:
    """Get summary statistics of QC ratings."""
    summary = {
        'total': len(qc_db),
        'pass': 0,
        'review': 0,
        'fail': 0
    }

    for entry in qc_db.values():
        status = entry['status'].lower()
        if 'pass' in status:
            summary['pass'] += 1
        elif 'review' in status:
            summary['review'] += 1
        elif 'fail' in status:
            summary['fail'] += 1

    return summary
