# QC Image Cache System

## Overview

The NeuConn app now includes a smart image caching system that dramatically speeds up QC image loading by storing pre-generated PNG images on disk following BIDS-Derivatives structure.

## Features

- **Automatic Caching**: Images are cached to disk when first generated
- **Modification Time Tracking**: Re-generates images only when source NIfTI files change
- **Background Pre-Generation**: Option to pre-generate all QC images in a background thread
- **Thread-Safe**: Safe for concurrent access
- **BIDS-Derivatives Structure**: Follows neuroimaging standards

## Cache Structure

```
bids_directory/
├── sub-033/
│   └── ses-01/
│       ├── anat/
│       │   └── sub-033_ses-01_run-01_T1w.nii.gz  (source)
│       └── func/
│           └── sub-033_ses-01_task-rest_bold.nii.gz  (source)
└── derivatives/
    └── qc_images/  (cache directory)
        ├── anat/
        │   ├── sub-033_ses-01_run-01_T1w.png
        │   └── sub-033_ses-01_run-02_T1w.png
        ├── func/
        │   ├── sub-033_ses-01_task-rest_timepoints.png
        │   └── sub-033_ses-01_task-rest_quality.png
        ├── dwi/
        │   └── sub-033_ses-01_dwi.png
        ├── fmap/
        │   └── sub-033_ses-01_dir-AP_epi.png
        └── cache_manifest.json  (tracks modification times)
```

## Usage

### In Python Code

```python
from utils.image_cache import ImageCache, get_image_cache
from utils.qa_image_generator import generate_anat_montage
from pathlib import Path

# Initialize cache
bids_dir = Path("/path/to/bids")
cache = get_image_cache(bids_dir)

# Get image (from cache or generate if needed)
nifti_file = bids_dir / "sub-033" / "ses-01" / "anat" / "sub-033_ses-01_run-01_T1w.nii.gz"
fig = cache.get_cached_image(nifti_file, 'anat', generate_anat_montage)

# Check if image is cached
is_cached = cache.has_cached_image(nifti_file, 'anat')

# Get cache statistics
stats = cache.get_cache_stats()
print(f"Cached: {stats['cached']}/{stats['total']} ({stats['percentage']}%)")
```

### Pre-Generation

```python
# Define generator functions
generator_funcs = {
    'anat': generate_anat_montage,
    'func_timepoints': generate_func_timepoints,
    'func_quality': generate_func_quality,
    'dwi': generate_dwi_montage,
    'fmap': generate_fmap_montage
}

# Start background generation
cache.start_background_generation(generator_funcs, force=False)

# Monitor progress
while cache.is_generating():
    progress = cache.get_progress()
    print(f"Progress: {progress['completed']}/{progress['total']}")
    time.sleep(1)
```

### In Streamlit App

The cache system is integrated into the Dataset Overview page:

1. Navigate to: **Data QC → Dataset Overview**
2. Scroll to **QC Image Cache** section
3. Click **"Pre-Generate All"** to generate all images in background
4. Progress bar shows generation status
5. Images are automatically used in Visual Check pages

## Image Types

| Type | Description | Generator Function |
|------|-------------|-------------------|
| `anat` | Anatomical T1w/T2w (7 axial + 7 sagittal) | `generate_anat_montage` |
| `func_timepoints` | BOLD timepoints (3 timepoints × 3 views) | `generate_func_timepoints` |
| `func_quality` | BOLD quality maps (mean, std, tSNR) | `generate_func_quality` |
| `dwi` | DWI volumes (b0, mid, high-b) | `generate_dwi_montage` |
| `fmap` | Field maps (AP/PA comparison) | `generate_fmap_montage` |

## Cache Invalidation

The cache automatically invalidates and regenerates images when:

1. **Source NIfTI modified**: If the source file's modification time is newer than the cached PNG
2. **Manual clear**: User clicks "Clear Cache" button
3. **Force regeneration**: User clicks "Pre-Generate All" (force=True)

## Performance Benefits

### Without Cache (Cold Start)
- **Anatomical T1w**: ~0.5-1 second per image
- **Functional Timepoints**: ~1-2 seconds per image
- **Functional Quality Maps**: ~8-10 seconds per image (expensive)

### With Cache (Warm Start)
- **All Images**: ~0.05-0.1 seconds (disk read + PNG decode)

### Example: Full Dataset (44 subjects, 2 sessions)
- **T1w images**: 176 (2 runs × 44 subjects × 2 sessions)
- **Functional images**: 136 timepoints + 136 quality maps = 272
- **Total**: 448 images

**Time savings**:
- Cold: ~45 minutes (quality maps dominate)
- Warm: ~22 seconds (all from cache)

## Cache Management

### Get Cache Stats

```python
stats = cache.get_cache_stats()
# Returns:
# {
#     'total': 448,
#     'cached': 224,
#     'percentage': 50.0,
#     'by_type': {
#         'anat': {'total': 176, 'cached': 88},
#         'func_timepoints': {'total': 136, 'cached': 68},
#         'func_quality': {'total': 136, 'cached': 68},
#         ...
#     }
# }
```

### Clear Cache

```python
# Clear all
cache.clear_cache()

# Clear specific type
cache.clear_cache(image_type='func_quality')
```

### View Manifest

```bash
cat /path/to/bids/derivatives/qc_images/cache_manifest.json
```

## Implementation Details

### Modification Time Tracking

Each cache entry stores:
- `source_mtime`: Modification time of source NIfTI
- `cache_mtime`: Modification time of cached PNG
- `generated_at`: ISO timestamp of generation

### Thread Safety

- Uses `threading.RLock()` for thread-safe manifest updates
- Background generation runs in separate daemon thread
- Progress tracking is thread-safe

### Memory Management

- Figures are closed after saving to disk to free memory
- Streamlit `@st.cache_resource` provides additional in-memory caching
- Two-tier caching: disk (persistent) + Streamlit memory (session)

## Testing

Run the test suite:

```bash
cd /home/clivewong/proj/longevity/neuconn_app
python test_image_cache.py
```

Tests include:
1. Cache initialization
2. Single image generation and caching
3. Cache hit/miss detection
4. Cache statistics
5. Manifest integrity
6. Background pre-generation (optional)

## Troubleshooting

### Cache not working

Check if cache directory exists:
```bash
ls -la /path/to/bids/derivatives/qc_images/
```

### Images not regenerating after source change

Clear cache and force regeneration:
```python
cache.clear_cache()
cache.start_background_generation(generator_funcs, force=True)
```

### Background generation stuck

Stop and restart:
```python
cache.stop_background_generation()
time.sleep(2)
cache.start_background_generation(generator_funcs)
```

### Disk space usage

Check cache size:
```bash
du -sh /path/to/bids/derivatives/qc_images/
```

Typical PNG sizes:
- Anatomical: ~100-200 KB each
- Functional timepoints: ~200-300 KB each
- Functional quality: ~200-300 KB each

For 448 images: ~100-150 MB total

## API Reference

### `ImageCache`

#### Methods

- `__init__(bids_dir, cache_subdir='derivatives/qc_images')`
- `get_cached_image(source_path, image_type, generator_func)` → Figure
- `generate_and_cache(source_path, image_type, generator_func, force=False)` → bool
- `has_cached_image(source_path, image_type)` → bool
- `get_all_source_files()` → Dict[str, List[Path]]
- `get_cache_stats()` → Dict[str, Any]
- `get_progress()` → Dict[str, Any]
- `is_generating()` → bool
- `start_background_generation(generator_funcs, force=False)`
- `stop_background_generation()`
- `clear_cache(image_type=None)`

### `get_image_cache(bids_dir)` → ImageCache

Get or create global cache instance (singleton pattern).

## Integration with Existing Code

The cache system integrates seamlessly with existing visualization functions:

### Before (No Cache)

```python
from utils.visualization import plot_anat_montage

fig = plot_anat_montage(nifti_path)
st.pyplot(fig)
```

### After (With Cache)

```python
from utils.visualization import plot_anat_montage

# Automatic caching if bids_dir is provided
fig = plot_anat_montage(nifti_path, use_cache=True, bids_dir=bids_dir)
st.pyplot(fig)
```

The cache is **transparent** - existing code works without changes, but gains caching benefits when `bids_dir` is provided.

## Future Enhancements

Potential improvements:

1. **Compression**: Use PNG compression for smaller cache size
2. **Purge old entries**: Auto-delete cache entries older than N days
3. **Cache on HPC**: Share cache across HPC cluster nodes
4. **Parallel generation**: Multi-threaded image generation
5. **Incremental updates**: Only regenerate changed subjects

## Credits

Implemented for NeuConn app (Phase 3)
Based on original QA script: `/script/qa_check_images.py`
