# Test Results & Validation Reports

This directory contains all test execution results, validation reports, and temporary test outputs organized by test session and date.

## Directory Structure

```
test-results/
├── README.md (this file - conventions and guidelines)
├── e2e-connectivity-2026-05-01/
│   ├── E2E_TEST_*.md/txt (test execution reports)
│   ├── TFCE_*.md/txt (analysis-specific reports)
│   ├── FINAL_E2E_TEST_RESULTS.md (comprehensive final report)
│   └── images/
│       ├── TFCE_Results_Visualization.png
│       ├── TFCE_Statistical_Distributions.png
│       └── TFCE_Orthogonal_Views.png
└── [other test dates]/
```

## Convention for Test Results

### Naming Convention
- Test result directories: `{test-type}-{date}` (e.g., `e2e-connectivity-2026-05-01`)
- Files in directory: Keep original names for clarity
- Images subdirectory: Always use `images/` for visualization outputs

### File Organization

**Test Reports** (in test directory root):
- `E2E_TEST_*.md/txt` - Individual component test results
- `FINAL_{TEST-NAME}_RESULTS.md` - Comprehensive summary
- `{ANALYSIS-NAME}_RESULTS.md` - Analysis-specific findings
- `{ANALYSIS-NAME}_VALIDATION_*.md` - Detailed validation reports

**Test Images** (in `images/` subdirectory):
- `*.png` - Visualization outputs and screenshots
- `*.svg` - Vector graphics (if generated)

**Test Data** (in test directory root):
- `*.csv` - Test grouping or reference data
- `*.json` - Test metadata

## When to Add Files Here

✅ **DO Add to test-results/**:
- Test execution reports (markdown or text)
- Validation reports and summaries
- Test-generated visualizations (PNG, SVG)
- Screenshots from test runs
- Test-specific data groupings

❌ **DO NOT Add to test-results/**:
- Core analysis outputs → `derivatives/` (permanent results)
- Test scripts → `tests/` or `neuconn_app/tests/`
- Temporary session artifacts → `tmp/`
- Production data files → respective data directories

## When to Remove Files

- Test results are **ephemeral documentation** - they document what was tested, not permanent state
- Keep recent test results (last 2-3 runs) for reference
- Archive or delete older test runs to prevent clutter
- After analysis is validated, move key results to `derivatives/` if they're permanent

## Integration with .gitignore

These test results should generally NOT be committed to git:

```gitignore
# Test results and validation reports (ephemeral)
docs/test-results/**/E2E_TEST_*
docs/test-results/**/TFCE_*
docs/test-results/**/FINAL_E2E_*
docs/test-results/**/FINAL_*
docs/test-results/**/*.png
docs/test-results/**/*.jpg
```

## Example: Future Test Runs

When running new end-to-end tests:

```bash
# 1. Create dated directory
mkdir -p docs/test-results/e2e-connectivity-YYYY-MM-DD/images

# 2. Run test, saving outputs to that directory
cd neuconn_app
streamlit run app.py &
# ... run test ...

# 3. Move all test outputs
mv test_results/* ../docs/test-results/e2e-connectivity-YYYY-MM-DD/
mv screenshots/* ../docs/test-results/e2e-connectivity-YYYY-MM-DD/images/

# 4. Create summary report
# ... generate FINAL_E2E_TEST_RESULTS.md ...
```

## Related Documentation

- **Main Testing Guide**: `docs/testing/`
- **Project Structure**: `CLAUDE.md` - Repository conventions
- **Quick Start**: `QUICK_START.md` - Getting started with tests

## Test History

### e2e-connectivity-2026-05-01
- **Purpose**: End-to-end seed connectivity analysis with TFCE group statistics
- **Status**: ✅ Complete
- **Results**: 72 subject-level maps + group-level TFCE analysis
- **Key Files**:
  - `FINAL_E2E_TEST_RESULTS.md` - Comprehensive report
  - `images/TFCE_*.png` - Publication-ready visualizations

---

**Convention Established**: 2026-05-02  
**Last Updated**: 2026-05-02  
**Maintainer**: Longevity Project Team
