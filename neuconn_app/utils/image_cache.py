"""
Smart Image Cache System for QC Images

Implements intelligent caching with:
- BIDS-Derivatives structure (derivatives/qc_images/)
- Modification time tracking
- Background pre-generation thread
- Thread-safe operations

Usage:
    from utils.image_cache import ImageCache

    cache = ImageCache(bids_dir)
    fig = cache.get_anat_image(nifti_path)  # Returns from cache or generates
    cache.start_background_generation()     # Start pre-generating all images
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List, Tuple
import io
import base64

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt


class ImageCache:
    """Thread-safe image caching system with background pre-generation."""

    def __init__(self, bids_dir: Path, cache_subdir: str = "derivatives/qc_images"):
        """
        Initialize cache system.

        Args:
            bids_dir: Path to BIDS directory
            cache_subdir: Subdirectory for cache (default: derivatives/qc_images)
        """
        self.bids_dir = Path(bids_dir)
        self.cache_dir = self.bids_dir / cache_subdir
        self.manifest_path = self.cache_dir / "cache_manifest.json"

        # Thread safety
        self._lock = threading.RLock()
        self._generation_thread: Optional[threading.Thread] = None
        self._stop_generation = threading.Event()

        # Progress tracking
        self._progress: Dict[str, Any] = {
            'total': 0,
            'completed': 0,
            'current_file': '',
            'running': False,
            'errors': []
        }

        # Ensure cache directories exist
        self._ensure_cache_dirs()

        # Load manifest
        self._manifest = self._load_manifest()

    def _ensure_cache_dirs(self):
        """Create cache directory structure."""
        (self.cache_dir / "anat").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "func").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "dwi").mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "fmap").mkdir(parents=True, exist_ok=True)

    def _load_manifest(self) -> Dict[str, Any]:
        """Load cache manifest from disk."""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {'files': {}, 'version': 1}
        return {'files': {}, 'version': 1}

    def _save_manifest(self):
        """Save cache manifest to disk."""
        with self._lock:
            self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.manifest_path, 'w') as f:
                json.dump(self._manifest, f, indent=2)

    def _get_cache_path(self, source_path: Path, image_type: str) -> Path:
        """
        Get cache path for a source NIfTI file.

        Args:
            source_path: Path to source NIfTI file
            image_type: 'anat', 'func_timepoints', 'func_quality', 'dwi', or 'fmap'

        Returns:
            Path to cached PNG file
        """
        # Determine cache subdirectory based on type
        if image_type.startswith('func'):
            subdir = 'func'
        elif image_type in ('anat', 'dwi', 'fmap'):
            subdir = image_type
        else:
            subdir = 'anat'

        # Build filename: sub-XXX_ses-XX_..._<type>.png
        stem = source_path.stem
        if stem.endswith('.nii'):
            stem = stem[:-4]  # Remove .nii from .nii.gz

        # Add image type suffix for func (which has multiple images per file)
        if image_type == 'func_timepoints':
            cache_name = f"{stem}_timepoints.png"
        elif image_type == 'func_quality':
            cache_name = f"{stem}_quality.png"
        else:
            cache_name = f"{stem}.png"

        return self.cache_dir / subdir / cache_name

    def _is_cache_valid(self, source_path: Path, cache_path: Path) -> bool:
        """
        Check if cached image is up-to-date.

        Args:
            source_path: Path to source NIfTI file
            cache_path: Path to cached PNG file

        Returns:
            True if cache is valid (exists and newer than source)
        """
        if not cache_path.exists():
            return False

        if not source_path.exists():
            return False

        # Compare modification times
        source_mtime = source_path.stat().st_mtime
        cache_mtime = cache_path.stat().st_mtime

        # Also check manifest for recorded mtime
        manifest_key = str(source_path.relative_to(self.bids_dir))
        with self._lock:
            if manifest_key in self._manifest['files']:
                recorded_mtime = self._manifest['files'][manifest_key].get('source_mtime', 0)
                if source_mtime > recorded_mtime:
                    return False

        return cache_mtime > source_mtime

    def _update_manifest_entry(self, source_path: Path, cache_path: Path, image_type: str):
        """Update manifest with new cache entry."""
        manifest_key = str(source_path.relative_to(self.bids_dir))

        with self._lock:
            self._manifest['files'][manifest_key] = {
                'cache_path': str(cache_path.relative_to(self.cache_dir)),
                'source_mtime': source_path.stat().st_mtime,
                'cache_mtime': cache_path.stat().st_mtime,
                'image_type': image_type,
                'generated_at': datetime.now().isoformat()
            }
            self._save_manifest()

    def get_cached_image(
        self,
        source_path: Path,
        image_type: str,
        generator_func: Callable[[Path], Optional[plt.Figure]]
    ) -> Optional[plt.Figure]:
        """
        Get image from cache or generate if needed.

        Args:
            source_path: Path to source NIfTI file
            image_type: Type of image ('anat', 'func_timepoints', etc.)
            generator_func: Function to generate the image if not cached

        Returns:
            matplotlib Figure or None on error
        """
        cache_path = self._get_cache_path(source_path, image_type)

        # Check if cache is valid
        if self._is_cache_valid(source_path, cache_path):
            # Load from cache
            try:
                import matplotlib.image as mpimg
                img_array = mpimg.imread(str(cache_path))

                # Convert to figure
                fig, ax = plt.subplots(figsize=(img_array.shape[1]/100, img_array.shape[0]/100))
                ax.imshow(img_array)
                ax.axis('off')
                plt.tight_layout(pad=0)

                return fig
            except Exception as e:
                print(f"Cache load error for {cache_path}: {e}")
                # Fall through to regeneration

        # Generate new image
        fig = generator_func(source_path)

        if fig is not None:
            # Save to cache
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(str(cache_path), dpi=100, bbox_inches='tight', facecolor='white')
                self._update_manifest_entry(source_path, cache_path, image_type)
            except Exception as e:
                print(f"Cache save error for {cache_path}: {e}")

        return fig

    def generate_and_cache(
        self,
        source_path: Path,
        image_type: str,
        generator_func: Callable[[Path], Optional[plt.Figure]],
        force: bool = False
    ) -> bool:
        """
        Generate and cache an image (does not return the figure).

        Args:
            source_path: Path to source NIfTI file
            image_type: Type of image
            generator_func: Generator function
            force: If True, regenerate even if cache is valid

        Returns:
            True if image was generated/cached successfully
        """
        cache_path = self._get_cache_path(source_path, image_type)

        # Check if regeneration needed
        if not force and self._is_cache_valid(source_path, cache_path):
            return True

        # Generate
        fig = generator_func(source_path)

        if fig is not None:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                fig.savefig(str(cache_path), dpi=100, bbox_inches='tight', facecolor='white')
                plt.close(fig)
                self._update_manifest_entry(source_path, cache_path, image_type)
                return True
            except Exception as e:
                print(f"Cache save error: {e}")
                plt.close(fig)
                return False

        return False

    def has_cached_image(self, source_path: Path, image_type: str) -> bool:
        """Check if a valid cached image exists."""
        cache_path = self._get_cache_path(source_path, image_type)
        return self._is_cache_valid(source_path, cache_path)

    def load_cached_image_as_base64(self, source_path: Path, image_type: str) -> Optional[str]:
        """
        Load cached image as base64 string for embedding in HTML.

        Returns:
            Base64 encoded PNG string or None if not cached
        """
        cache_path = self._get_cache_path(source_path, image_type)

        if not self._is_cache_valid(source_path, cache_path):
            return None

        try:
            with open(cache_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            return None

    def get_all_source_files(self) -> Dict[str, List[Path]]:
        """
        Scan BIDS directory for all source files that need QC images.

        Returns:
            Dict with keys 'anat', 'func', 'dwi', 'fmap' containing lists of paths
        """
        files = {
            'anat': [],
            'func': [],
            'dwi': [],
            'fmap': []
        }

        # Scan all subjects
        for subject_dir in sorted(self.bids_dir.iterdir()):
            if not subject_dir.is_dir() or not subject_dir.name.startswith('sub-'):
                continue

            # Scan sessions
            for session_dir in sorted(subject_dir.iterdir()):
                if not session_dir.is_dir() or not session_dir.name.startswith('ses-'):
                    continue

                # Anatomical
                anat_dir = session_dir / 'anat'
                if anat_dir.exists():
                    files['anat'].extend(sorted(anat_dir.glob('*_T1w.nii.gz')))
                    files['anat'].extend(sorted(anat_dir.glob('*_T2w.nii.gz')))

                # Functional
                func_dir = session_dir / 'func'
                if func_dir.exists():
                    files['func'].extend(sorted(func_dir.glob('*_bold.nii.gz')))

                # DWI
                dwi_dir = session_dir / 'dwi'
                if dwi_dir.exists():
                    files['dwi'].extend(sorted(dwi_dir.glob('*_dwi.nii.gz')))

                # Field maps
                fmap_dir = session_dir / 'fmap'
                if fmap_dir.exists():
                    files['fmap'].extend(sorted(fmap_dir.glob('*_epi.nii.gz')))

        return files

    def get_progress(self) -> Dict[str, Any]:
        """Get current pre-generation progress."""
        with self._lock:
            return self._progress.copy()

    def is_generating(self) -> bool:
        """Check if background generation is running."""
        return self._progress['running']

    def start_background_generation(
        self,
        generator_funcs: Dict[str, Callable[[Path], Optional[plt.Figure]]],
        force: bool = False
    ):
        """
        Start background thread to pre-generate all QC images.

        Args:
            generator_funcs: Dict mapping image_type to generator function
                Expected keys: 'anat', 'func_timepoints', 'func_quality', 'dwi', 'fmap'
            force: If True, regenerate all images even if cached
        """
        if self._generation_thread is not None and self._generation_thread.is_alive():
            return  # Already running

        self._stop_generation.clear()
        self._generation_thread = threading.Thread(
            target=self._generation_worker,
            args=(generator_funcs, force),
            daemon=True
        )
        self._generation_thread.start()

    def stop_background_generation(self):
        """Stop background generation thread."""
        self._stop_generation.set()
        if self._generation_thread is not None:
            self._generation_thread.join(timeout=5)

    def _generation_worker(
        self,
        generator_funcs: Dict[str, Callable[[Path], Optional[plt.Figure]]],
        force: bool
    ):
        """Worker thread for background image generation."""
        with self._lock:
            self._progress = {
                'total': 0,
                'completed': 0,
                'current_file': '',
                'running': True,
                'errors': []
            }

        try:
            # Get all files
            all_files = self.get_all_source_files()

            # Build work queue: (source_path, image_type, generator_func)
            work_queue: List[Tuple[Path, str, Callable]] = []

            # Anat files
            if 'anat' in generator_funcs:
                for path in all_files['anat']:
                    work_queue.append((path, 'anat', generator_funcs['anat']))

            # Func files (two images each)
            for path in all_files['func']:
                if 'func_timepoints' in generator_funcs:
                    work_queue.append((path, 'func_timepoints', generator_funcs['func_timepoints']))
                if 'func_quality' in generator_funcs:
                    work_queue.append((path, 'func_quality', generator_funcs['func_quality']))

            # DWI files
            if 'dwi' in generator_funcs:
                for path in all_files['dwi']:
                    work_queue.append((path, 'dwi', generator_funcs['dwi']))

            # Fmap files
            if 'fmap' in generator_funcs:
                for path in all_files['fmap']:
                    work_queue.append((path, 'fmap', generator_funcs['fmap']))

            with self._lock:
                self._progress['total'] = len(work_queue)

            # Process queue
            for source_path, image_type, gen_func in work_queue:
                if self._stop_generation.is_set():
                    break

                with self._lock:
                    self._progress['current_file'] = str(source_path.relative_to(self.bids_dir))

                try:
                    self.generate_and_cache(source_path, image_type, gen_func, force=force)
                except Exception as e:
                    with self._lock:
                        self._progress['errors'].append(f"{source_path.name}: {str(e)}")

                with self._lock:
                    self._progress['completed'] += 1

        finally:
            with self._lock:
                self._progress['running'] = False
                self._progress['current_file'] = ''

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache statistics
        """
        all_files = self.get_all_source_files()

        stats = {
            'anat': {'total': 0, 'cached': 0},
            'func_timepoints': {'total': 0, 'cached': 0},
            'func_quality': {'total': 0, 'cached': 0},
            'dwi': {'total': 0, 'cached': 0},
            'fmap': {'total': 0, 'cached': 0}
        }

        # Count anat
        for path in all_files['anat']:
            stats['anat']['total'] += 1
            if self.has_cached_image(path, 'anat'):
                stats['anat']['cached'] += 1

        # Count func (both types)
        for path in all_files['func']:
            stats['func_timepoints']['total'] += 1
            stats['func_quality']['total'] += 1
            if self.has_cached_image(path, 'func_timepoints'):
                stats['func_timepoints']['cached'] += 1
            if self.has_cached_image(path, 'func_quality'):
                stats['func_quality']['cached'] += 1

        # Count dwi
        for path in all_files['dwi']:
            stats['dwi']['total'] += 1
            if self.has_cached_image(path, 'dwi'):
                stats['dwi']['cached'] += 1

        # Count fmap
        for path in all_files['fmap']:
            stats['fmap']['total'] += 1
            if self.has_cached_image(path, 'fmap'):
                stats['fmap']['cached'] += 1

        # Total
        total = sum(s['total'] for s in stats.values())
        cached = sum(s['cached'] for s in stats.values())

        return {
            'by_type': stats,
            'total': total,
            'cached': cached,
            'percentage': round(100 * cached / total, 1) if total > 0 else 0
        }

    def clear_cache(self, image_type: Optional[str] = None):
        """
        Clear cached images.

        Args:
            image_type: If specified, only clear this type. Otherwise clear all.
        """
        import shutil

        with self._lock:
            if image_type:
                # Clear specific type
                type_dir = self.cache_dir / image_type.split('_')[0]  # 'func_timepoints' -> 'func'
                if type_dir.exists():
                    shutil.rmtree(type_dir)
                    type_dir.mkdir(exist_ok=True)

                # Remove from manifest
                keys_to_remove = [
                    k for k, v in self._manifest['files'].items()
                    if v.get('image_type', '').startswith(image_type.split('_')[0])
                ]
                for k in keys_to_remove:
                    del self._manifest['files'][k]
            else:
                # Clear all
                for subdir in ['anat', 'func', 'dwi', 'fmap']:
                    type_dir = self.cache_dir / subdir
                    if type_dir.exists():
                        shutil.rmtree(type_dir)
                        type_dir.mkdir(exist_ok=True)

                self._manifest['files'] = {}

            self._save_manifest()


# Global cache instance (lazy initialization)
_global_cache: Optional[ImageCache] = None


def get_image_cache(bids_dir: Path) -> ImageCache:
    """
    Get or create global image cache instance.

    Args:
        bids_dir: Path to BIDS directory

    Returns:
        ImageCache instance
    """
    global _global_cache

    if _global_cache is None or _global_cache.bids_dir != Path(bids_dir):
        _global_cache = ImageCache(bids_dir)

    return _global_cache
