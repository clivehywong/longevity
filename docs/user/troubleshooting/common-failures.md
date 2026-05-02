# Common Failures

| Problem | Likely cause | What to do |
|---|---|---|
| `validate_bids_names.py` reports mismatches | Subject/session names do not match directory structure | Fix naming first, then re-run validation |
| `qa_check_images.py` produces incomplete output | Wrong BIDS path or filtered subjects/sessions | Re-run with `--bids-dir` and confirm the dataset layout |
| `prepare_metadata.py` misses subjects | `bids/participants.tsv` or demographics do not match detected fMRIPrep subjects | Check subject IDs, confirm the tab-separated columns, and regenerate metadata |
| `seed_based_connectivity.py` says no BOLD files found | Wrong space/path assumptions or missing fMRIPrep outputs | Verify `fmriprep/sub-*/ses-*/func/` contents and the expected MNI space |
| Group analysis is too slow or fails | Permutation count is too high for the current environment | Reduce permutations for testing, then scale up deliberately |
| Streamlit app fails to load config | Missing or invalid `~/neuconn_projects/<project>.yaml` overrides | Start from defaults or fix the YAML file |
| `Slider min_value must be less than max_value` in fMRIPrep Submit | Only 1 subject selected; slider range collapses to [1,1] | Fixed in app code (single subject bypasses slider) |
| `AttributeError: 'HPCConfig' object has no attribute 'singularity_image'` | HPC submit uses wrong attribute name for fMRIPrep singularity image | Fixed in `hpc.py` (`singularity_fmriprep` is the correct attribute) |
| XCP-D fails with missing input (no `MNI152NLin6Asym:res-2` files) | fMRIPrep was run without that output space | Re-run fMRIPrep with `output_spaces` including `MNI152NLin6Asym:res-2` in config |

## Practical recovery order

1. Validate raw naming.
2. Confirm the expected input files exist.
3. Re-run the smallest possible workflow or smoke test.
4. Only then resume the larger batch or master workflow.

## Useful checks

```bash
python script/validate_bids_names.py bids/
cd neuconn_app && python test_cli.py
```
