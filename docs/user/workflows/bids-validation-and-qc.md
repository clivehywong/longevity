# BIDS Validation and QC

Use this workflow before preprocessing or analysis.

## Step 1: Validate filenames and session consistency

```bash
python script/validate_bids_names.py bids/
```

Use `--json` if you need machine-readable output.

## Step 2: Generate QC images

```bash
python script/qa_check_images.py --bids-dir bids --output qa_images_full
```

Useful optional filters:

- `--subjects sub-033 sub-034`
- `--sessions ses-01 ses-02`

## Step 3: Review the results

- Inspect the generated QA images under `qa_images_full/`.
- Use the NeuConn app for interactive review when you need slice browsing or exclusion management.
- Record or confirm exclusions before running downstream preprocessing.

## Step 4: Re-run validation after any renaming or fixes

Run the validator again after any BIDS naming repair so later scripts do not fail on stale assumptions.

## What this catches early

- Subject/session naming mismatches
- Missing JSON sidecars
- Dataset inconsistencies that would later break preprocessing or metadata generation

## Related docs

- Parameters: [`../reference/parameter-considerations.md`](../reference/parameter-considerations.md)
- Troubleshooting: [`../troubleshooting/common-failures.md`](../troubleshooting/common-failures.md)
