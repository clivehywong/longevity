# Parameter Considerations

These notes summarize the main parameters exposed by the current scripts. Use them to understand the trade-offs before changing defaults.

## Validation and QC

### `qa_check_images.py`

- `--subjects`: narrow the run when debugging or spot-checking
- `--sessions`: restrict to one session if a dataset is incomplete
- `--output`: choose a stable directory so later review is repeatable

## Local measures

### `compute_local_measures.py`

- `--tr` (default `0.8`): must match acquisition timing
- `--low-freq` / `--high-freq` (defaults `0.01` / `0.1`): set the retained frequency band
- `--neighborhood` (default `faces_edges_corners`): controls the ReHo neighborhood definition
- `--space` / `--res`: must match the available fMRIPrep outputs

## Time series extraction

### `extract_timeseries.py`

- `--atlas`: choose the ROI definition to extract
- `--smoothing`: spatial smoothing in millimeters
- `--high-pass` / `--low-pass`: temporal filtering band
- `--confounds`: denoising aggressiveness; more aggressive settings can remove more variance but may also remove signal of interest

## Seed-based connectivity

### `seed_based_connectivity.py`

- `--seed-names`: restrict to specific seeds for testing or focused analysis
- `--smoothing`: matched in the master workflow to `6.0`
- `--high-pass` / `--low-pass`: matched to `0.01` / `0.1`

## Network connectivity

### `python_connectivity_analysis.py`

- `--within-network`: use for a single targeted network analysis
- `--between-networks`: use for a targeted pair
- `--all-within` / `--all-between`: much broader scope and output volume
- `--alpha`: significance threshold before multiple-comparison interpretation

## Group analysis

### `group_level_analysis.py`

- `--cluster-threshold`: threshold for cluster reporting
- `--n-permutations`: more permutations improve stability but increase runtime
- `--min-cluster-size`: removes tiny clusters from reporting
- `--no-uncorrected-fallback`: stricter behavior when corrected results are absent

## Rule of thumb

Test new parameters on a narrow subset first, then move them into a larger workflow once paths, performance, and output shapes look correct.
