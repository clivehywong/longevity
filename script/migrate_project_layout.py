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


def _ensure_legacy_symlink(legacy_fmriprep: Path, target_fmriprep: Path, dry_run: bool) -> None:
    if legacy_fmriprep.exists() or legacy_fmriprep.is_symlink():
        if legacy_fmriprep.is_symlink() and legacy_fmriprep.resolve() == target_fmriprep.resolve():
            print("Compatibility symlink already exists at project_root/fmriprep")
            return
        raise RuntimeError(
            f"Cannot create compatibility symlink because {legacy_fmriprep} already exists."
        )

    if dry_run:
        print("[dry-run] Would create compatibility symlink: fmriprep -> derivatives/preprocessing/fmriprep")
        return

    legacy_fmriprep.symlink_to(Path("derivatives") / "preprocessing" / "fmriprep")
    print("Created compatibility symlink at project_root/fmriprep")


def migrate_layout(project_root: Path, create_legacy_symlink: bool, dry_run: bool) -> None:
    legacy_fmriprep = project_root / "fmriprep"
    target_fmriprep = project_root / "derivatives" / "preprocessing" / "fmriprep"

    print(f"Project root: {project_root}")
    print(f"Legacy fMRIPrep dir: {legacy_fmriprep}")
    print(f"Target fMRIPrep dir: {target_fmriprep}")

    if target_fmriprep.exists():
        if legacy_fmriprep.is_symlink():
            print("Layout already migrated.")
            return
        if not legacy_fmriprep.exists():
            print("Layout already migrated (legacy root-level directory already removed).")
            if create_legacy_symlink:
                _ensure_legacy_symlink(legacy_fmriprep, target_fmriprep, dry_run)
            return
        raise RuntimeError(
            "Target fMRIPrep directory already exists while the legacy path is still present. "
            "Resolve the duplicate directories before migrating."
        )

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
        _ensure_legacy_symlink(legacy_fmriprep, target_fmriprep, dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate NeuConn project layout")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Path to the project root (defaults to the current working directory)",
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
