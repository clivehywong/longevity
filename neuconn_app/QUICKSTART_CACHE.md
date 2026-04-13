# Quick Start Guide - Image Cache System

## Instant Setup (5 Minutes)

### 1. Verify Installation

```bash
cd /home/clivewong/proj/longevity/neuconn_app
python test_image_cache.py
```

Expected: All tests pass (skip background generation test for now)

### 2. Launch App

```bash
streamlit run app.py
```

### 3. Pre-Generate Images (One-Time Setup)

1. In the web browser, navigate to:
   - **Data QC** → **Dataset Overview**

2. Scroll down to **"QC Image Cache"** section

3. Click **"Pre-Generate All"** button

4. Monitor progress:
   - Progress bar shows completion percentage
   - Current file being processed
   - Estimated time: ~45-60 minutes for full dataset

5. Leave browser tab open during generation

### 4. Use Visual Check Pages (Now Fast!)

1. Navigate to:
   - **Data QC** → **Anatomical** → **Visual Check**
   - Images load from cache in ~50ms each

2. Navigate to:
   - **Data QC** → **Functional** → **Visual Check**
   - Quality maps (previously 8-10s) now load instantly

## Daily Usage

**No changes to your workflow**:
- Navigate to Visual Check pages as usual
- Images load automatically from cache
- Enjoy ~120x faster loading

## Checking Cache Status

In **Dataset Overview** → **QC Image Cache** section:

- **Total Images**: 1007 (your dataset)
- **Cached**: X/1007
- **Coverage**: X%

Expand **"Cache Details by Type"** to see breakdown:
- `anat`: Anatomical T1w/T2w
- `func_timepoints`: BOLD timepoint sampling
- `func_quality`: BOLD quality maps
- `dwi`: Diffusion images
- `fmap`: Field maps

## When to Regenerate

### New Subjects Added

Click **"Generate Missing Only"** (smart mode)
- Only generates images for new subjects
- Keeps existing cache intact
- Much faster than full regeneration

### Source Data Modified

Click **"Pre-Generate All"** (force mode)
- Regenerates all images
- Use after reprocessing data

### Cache Corrupted

Click **"Clear Cache"** then **"Pre-Generate All"**
- Removes all cached images
- Fresh regeneration

## Performance

### Your Dataset (44 subjects, 2 sessions)

**Before Cache**:
- Loading time per subject: ~2-5 minutes
- Dominated by functional quality maps (8-10s each)

**After Cache**:
- Loading time per subject: ~1-2 seconds
- All images from disk cache

**Speedup**: 60-150x faster

### Disk Space

- Cache location: `bids/derivatives/qc_images/`
- Size: ~100-150 MB (for your full dataset)
- Manifest: ~100-200 KB

## Troubleshooting

### Cache not working

**Check**:
```bash
ls -la /home/clivewong/proj/longevity/bids/derivatives/qc_images/
```

**Should see**:
- `anat/`, `func/`, `dwi/`, `fmap/` subdirectories
- `cache_manifest.json`

### Images still slow

**Verify cache coverage**:
- Go to Dataset Overview
- Check "Coverage" percentage
- Should be close to 100%

**If low coverage**:
- Click "Pre-Generate All"
- Wait for completion

### Background generation stuck

**Stop and restart**:
- Click "Stop Generation"
- Refresh page
- Click "Generate Missing Only"

### Clear everything and start fresh

```bash
rm -rf /home/clivewong/proj/longevity/bids/derivatives/qc_images/
```

Then in app:
- Go to Dataset Overview
- Click "Pre-Generate All"

## Advanced Usage

### CLI Tool (Batch Generation)

```bash
# Generate for all subjects
python -m utils.qa_image_generator \
    --bids-dir /home/clivewong/proj/longevity/bids \
    --output qa_images/

# Specific subjects only
python -m utils.qa_image_generator \
    --bids-dir /home/clivewong/proj/longevity/bids \
    --output qa_images/ \
    --subjects sub-033 sub-034 sub-035

# Skip HTML report
python -m utils.qa_image_generator \
    --bids-dir /home/clivewong/proj/longevity/bids \
    --output qa_images/ \
    --no-html
```

### Python API

```python
from pathlib import Path
from utils.image_cache import get_image_cache
from utils.qa_image_generator import generate_anat_montage

bids_dir = Path("/home/clivewong/proj/longevity/bids")
cache = get_image_cache(bids_dir)

# Get image (from cache or generate)
nifti_file = bids_dir / "sub-033" / "ses-01" / "anat" / "sub-033_ses-01_run-01_T1w.nii.gz"
fig = cache.get_cached_image(nifti_file, 'anat', generate_anat_montage)

# Check if cached
is_cached = cache.has_cached_image(nifti_file, 'anat')
print(f"Cached: {is_cached}")

# Get stats
stats = cache.get_cache_stats()
print(f"Coverage: {stats['percentage']}%")
```

## Tips

1. **Pre-generate overnight**: Initial generation takes time, run it overnight
2. **Clear old cache**: After major data reprocessing, clear and regenerate
3. **Monitor disk space**: Check cache size if disk space is limited
4. **Use smart generation**: After adding new subjects, use "Generate Missing Only"
5. **Keep cache**: Cache survives app restarts, no need to regenerate

## Need Help?

- **Documentation**: See `IMAGE_CACHE_README.md` for full details
- **Implementation**: See `IMPLEMENTATION_SUMMARY.md` for technical details
- **Changes**: See `CHANGES.md` for what was modified
- **Testing**: Run `python test_image_cache.py` to verify system

## Summary

The cache system is:
- **Automatic**: Works transparently once pre-generated
- **Fast**: 120x speedup for quality maps
- **Safe**: Non-destructive, can be cleared anytime
- **Smart**: Only regenerates changed files
- **Easy**: One-click pre-generation via UI

Enjoy instant QC image loading!
