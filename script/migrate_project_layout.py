#!/usr/bin/env python3
"""
Migrate the repository to the XCP-D-first derivatives layout.

This moves the root-level fmriprep/ directory to
derivatives/preprocessing/fmriprep/ and optionally creates a compatibility
symlink back at the old location so legacy scripts continue to work while the
rest of the repository is migrated.
"""

from __future__ import annotations

from pathlib import Path
import argparse
import shutil


def migrate_layout(project_root: Path, create_legacy_symlink: bool, dry_run: bool) -> None:
    legacy_fmriprep = project_root / "fmriprep"
    target_fmriprep = project_root / "derivatives" / "preprocessing" / "fmriprep"

    print(f"Project root: {project_root}")
    print(f"Legacy fMRIPrep dir: {legacy_fmriprep}")
    print(f"Target fMRIPrep dir: {target_fmriprep}")

    if target_fmriprep.exists() and legacy_fmriprep.is_symlink():
        print("Layout already migrated.")
        return

    if not legacy_fmriprep.exists():
        print("No legacy root-level fmriprep/ directory found. Nothing to migrate.")
        return

    target_fmriprep.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print("[dry-run] Would move legacy fMRIPrep directory to derivatives/preprocessing/fmriprep")
    else:
        shutil.move(str(legacy_fmriprep), str(target_fmriprep))
        print("Moved fMRIPrep directory into derivatives/preprocessing/fmriprep")

    if create_legacy_symlink:
        if dry_run:
            print("[dry-run] Would create compatibility symlink: fmriprep -> derivatives/preprocessing/fmriprep")
        else:
            legacy_fmriprep.symlink_to(target_fmriprep)
            print("Created compatibility symlink at project_root/fmriprep")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate NeuConn project layout")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("/home/clivewong/proj/longevity"),
        help="Path to the project root",
    )
    parser.add_argument(
        "--no-legacy-symlink",
        action="store_true",
        help="Do not create a compatibility symlink at the old fmriprep location",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without modifying the filesystem",
    )
    args = parser.parse_args()

    migrate_layout(
        project_root=args.project_root.resolve(),
        create_legacy_symlink=not args.no_legacy_symlink,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
