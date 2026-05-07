#!/usr/bin/env python3
"""
HPC Manifest Manager: Track job completion, validate readiness for group analysis
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional


class ManifestManager:
    """Manage manifest.json for HPC job tracking and validation"""

    def __init__(self, manifest_path: str):
        """
        Initialize manifest at path.
        
        Args:
            manifest_path: Path to .manifest.json file
        """
        self.manifest_path = Path(manifest_path)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_or_create_manifest()

    def _load_or_create_manifest(self):
        """Load existing manifest or create new one"""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r') as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load manifest {self.manifest_path}: {e}")
                self._init_empty_manifest()
        else:
            self._init_empty_manifest()

    def _init_empty_manifest(self):
        """Initialize empty manifest structure"""
        self.data = {
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "tasks": {},
            "analyses_ready": {},
            "metadata": {
                "total_subjects": 0,
                "total_sessions": 0
            }
        }
        self._save_manifest()

    def _save_manifest(self):
        """Save manifest to disk"""
        self.data["updated_at"] = datetime.now().isoformat()
        try:
            with open(self.manifest_path, 'w') as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            print(f"Error: Could not save manifest {self.manifest_path}: {e}")
            raise

    def record_completion(
        self,
        subject_id: str,
        session: str,
        seed: str,
        atlas: str,
        status: str = "complete",
        metadata: Optional[Dict] = None
    ):
        """
        Record that a task completed.
        
        Args:
            subject_id: Subject identifier (e.g., 'sub-033')
            session: Session label (e.g., 'ses-01')
            seed: Seed name (e.g., 'dlpfc_l')
            atlas: Atlas name (e.g., 'difumo256')
            status: Task status ('complete', 'failed', 'partial')
            metadata: Optional dict with task metadata (output_path, job_id, etc.)
        """
        task_key = f"{subject_id}_{session}_{seed}_{atlas}"
        
        self.data["tasks"][task_key] = {
            "subject_id": subject_id,
            "session": session,
            "seed": seed,
            "atlas": atlas,
            "status": status,
            "completed_at": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self._save_manifest()

    def get_completion_rate(self, seed: str, atlas: str) -> Tuple[int, int, float]:
        """
        Return (completed, total, percentage) for a seed-atlas combination.
        
        Args:
            seed: Seed name
            atlas: Atlas name
            
        Returns:
            Tuple of (completed_count, total_count, percentage)
        """
        completed = 0
        total = 0
        
        for task_key, task_data in self.data["tasks"].items():
            if task_data["seed"] == seed and task_data["atlas"] == atlas:
                total += 1
                if task_data["status"] == "complete":
                    completed += 1
        
        percentage = (completed / total * 100) if total > 0 else 0
        return completed, total, percentage

    def is_ready_for_group_analysis(
        self,
        seed: str,
        atlas: str,
        min_threshold: float = 0.8
    ) -> bool:
        """
        Check if enough subjects have completed for group analysis.
        
        Args:
            seed: Seed name
            atlas: Atlas name
            min_threshold: Minimum completion rate (0.0-1.0, default 0.8 = 80%)
            
        Returns:
            True if completion rate >= min_threshold, False otherwise
        """
        completed, total, percentage = self.get_completion_rate(seed, atlas)
        threshold_pct = min_threshold * 100
        return percentage >= threshold_pct and total > 0

    def mark_analysis_ready(self, seed: str, atlas: str):
        """
        Mark this seed-atlas combo ready for group analysis.
        
        Args:
            seed: Seed name
            atlas: Atlas name
        """
        key = f"{seed}_{atlas}"
        self.data["analyses_ready"][key] = {
            "ready_at": datetime.now().isoformat(),
            "completion_status": self.get_completion_rate(seed, atlas)
        }
        self._save_manifest()

    def get_missing_subjects(self, seed: str, atlas: str) -> List[Tuple[str, str]]:
        """
        Return list of subject-session pairs that are incomplete.
        
        Args:
            seed: Seed name
            atlas: Atlas name
            
        Returns:
            List of (subject_id, session) tuples for incomplete tasks
        """
        incomplete = []
        
        for task_key, task_data in self.data["tasks"].items():
            if task_data["seed"] == seed and task_data["atlas"] == atlas:
                if task_data["status"] != "complete":
                    incomplete.append((task_data["subject_id"], task_data["session"]))
        
        return sorted(list(set(incomplete)))  # Remove duplicates and sort

    def get_failed_subjects(self, seed: str, atlas: str) -> List[Tuple[str, str]]:
        """
        Return list of subject-session pairs that failed.
        
        Args:
            seed: Seed name
            atlas: Atlas name
            
        Returns:
            List of (subject_id, session) tuples for failed tasks
        """
        failed = []
        
        for task_key, task_data in self.data["tasks"].items():
            if task_data["seed"] == seed and task_data["atlas"] == atlas:
                if task_data["status"] == "failed":
                    failed.append((task_data["subject_id"], task_data["session"]))
        
        return sorted(list(set(failed)))  # Remove duplicates and sort

    def get_summary(self) -> Dict:
        """Get summary of all tasks and readiness status"""
        summary = {
            "total_tasks": len(self.data["tasks"]),
            "analyses_ready": list(self.data["analyses_ready"].keys()),
            "seed_atlas_progress": {}
        }
        
        # Collect unique seed-atlas combinations
        seed_atlas_pairs = set()
        for task_data in self.data["tasks"].values():
            pair = (task_data["seed"], task_data["atlas"])
            seed_atlas_pairs.add(pair)
        
        # Get progress for each pair
        for seed, atlas in sorted(seed_atlas_pairs):
            completed, total, percentage = self.get_completion_rate(seed, atlas)
            is_ready = self.is_ready_for_group_analysis(seed, atlas)
            summary["seed_atlas_progress"][f"{seed}_{atlas}"] = {
                "completed": completed,
                "total": total,
                "percentage": round(percentage, 1),
                "ready_for_group": is_ready
            }
        
        return summary

    def print_status(self):
        """Print human-readable status report"""
        summary = self.get_summary()
        print("\n" + "="*80)
        print("HPC MANIFEST STATUS")
        print("="*80)
        print(f"Total tasks: {summary['total_tasks']}")
        print(f"Analyses ready: {len(summary['analyses_ready'])}")
        
        if summary["seed_atlas_progress"]:
            print("\nSeed-Atlas Progress:")
            print("-" * 80)
            for key, progress in sorted(summary["seed_atlas_progress"].items()):
                ready_str = "✓ READY" if progress["ready_for_group"] else "  pending"
                print(
                    f"  {key:40s} "
                    f"{progress['completed']:3d}/{progress['total']:3d} "
                    f"({progress['percentage']:5.1f}%) {ready_str}"
                )
        print("="*80 + "\n")


def main():
    """CLI interface for manifest management"""
    import argparse
    
    parser = argparse.ArgumentParser(description="HPC Manifest Manager")
    parser.add_argument("--manifest", default=".manifest.json", help="Path to manifest file")
    
    subparsers = parser.add_subparsers(dest="command")
    
    # record command
    record_parser = subparsers.add_parser("record", help="Record task completion")
    record_parser.add_argument("--subject", required=True, help="Subject ID")
    record_parser.add_argument("--session", required=True, help="Session label")
    record_parser.add_argument("--seed", required=True, help="Seed name")
    record_parser.add_argument("--atlas", required=True, help="Atlas name")
    record_parser.add_argument("--status", default="complete", help="Task status")
    record_parser.add_argument("--output", help="Output path")
    record_parser.add_argument("--job-id", help="SLURM job ID")
    
    # status command
    status_parser = subparsers.add_parser("status", help="Show manifest status")
    status_parser.add_argument("--seed", help="Filter by seed")
    status_parser.add_argument("--atlas", help="Filter by atlas")
    
    # check-ready command
    ready_parser = subparsers.add_parser("check-ready", help="Check if analysis is ready")
    ready_parser.add_argument("--seed", required=True, help="Seed name")
    ready_parser.add_argument("--atlas", required=True, help="Atlas name")
    ready_parser.add_argument("--threshold", type=float, default=0.8, help="Completion threshold")
    
    # missing command
    missing_parser = subparsers.add_parser("missing", help="List missing subjects")
    missing_parser.add_argument("--seed", required=True, help="Seed name")
    missing_parser.add_argument("--atlas", required=True, help="Atlas name")
    
    args = parser.parse_args()
    
    manager = ManifestManager(args.manifest)
    
    if args.command == "record":
        metadata = {}
        if args.output:
            metadata["output_path"] = args.output
        if args.job_id:
            metadata["job_id"] = args.job_id
        
        manager.record_completion(
            args.subject,
            args.session,
            args.seed,
            args.atlas,
            status=args.status,
            metadata=metadata
        )
        print(f"Recorded: {args.subject} {args.session} {args.seed} {args.atlas} -> {args.status}")
    
    elif args.command == "status":
        manager.print_status()
    
    elif args.command == "check-ready":
        is_ready = manager.is_ready_for_group_analysis(
            args.seed,
            args.atlas,
            min_threshold=args.threshold
        )
        completed, total, percentage = manager.get_completion_rate(args.seed, args.atlas)
        
        print(f"\nSeed: {args.seed}, Atlas: {args.atlas}")
        print(f"Completion: {completed}/{total} ({percentage:.1f}%)")
        print(f"Threshold: {args.threshold*100:.0f}%")
        print(f"Ready for group analysis: {'YES' if is_ready else 'NO'}")
        
        if not is_ready:
            missing = manager.get_missing_subjects(args.seed, args.atlas)
            if missing:
                print(f"\nMissing {len(missing)} subject-sessions:")
                for sub, ses in missing[:10]:
                    print(f"  - {sub} {ses}")
                if len(missing) > 10:
                    print(f"  ... and {len(missing) - 10} more")
        
        sys.exit(0 if is_ready else 1)
    
    elif args.command == "missing":
        missing = manager.get_missing_subjects(args.seed, args.atlas)
        failed = manager.get_failed_subjects(args.seed, args.atlas)
        
        print(f"\nSeed: {args.seed}, Atlas: {args.atlas}")
        print(f"Total incomplete: {len(missing)}")
        print(f"Failed: {len(failed)}")
        
        if missing:
            print("\nMissing subject-sessions:")
            for sub, ses in missing:
                status = "FAILED" if (sub, ses) in failed else "NOT STARTED"
                print(f"  - {sub} {ses} ({status})")


if __name__ == "__main__":
    main()
