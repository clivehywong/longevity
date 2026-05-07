# Test Suite Documentation

## Overview

This comprehensive test suite validates the neuroimaging connectivity analysis pipeline with **synthetic data**, **unit tests**, **integration tests**, and **output validation**. The tests are designed to catch silent bugs (NaN p-values, singular matrices, etc.) before they propagate to publication.

**Key Design Principles:**
- **Synthetic data with known effects**: All data is generated with implanted effects so we can verify correctness
- **No dependencies on real data**: Tests run instantly on CI/CD with no disk I/O
- **Reproducible**: All randomness seeded for deterministic test results
- **Fast**: Unit tests complete in seconds; integration tests in < 1 minute

---

## Quick Start

### Run All Tests
```bash
cd /home/clivewong/proj/longevity

# Install test dependencies
pip install pytest pytest-cov

# Run all tests with verbose output
pytest tests/ -v

# Run with coverage report
pytest tests/ --cov=script --cov-report=html
```

### Run Specific Test Modules
```bash
# Local measures tests
pytest tests/test_local_measures.py -v

# LME model tests
pytest tests/test_lme_model.py -v

# Permutation correction tests
pytest tests/test_permutation_correction.py -v

# Integration tests (slower)
pytest tests/test_integration.py -v

# Output validation tests
pytest tests/test_validation.py -v

# Seed connectivity tests
pytest tests/test_seed_connectivity.py -v
```

### Run Specific Test Classes
```bash
# All tests in a class
pytest tests/test_lme_model.py::TestLMEEffectSizeEstimation -v

# Single test
pytest tests/test_lme_model.py::TestLMEEffectSizeEstimation::test_lme_recovers_known_effect -v
```

### Run Tests with Coverage
```bash
pytest tests/ --cov=script --cov-report=term-missing
```

---

## Test Structure

### 1. **conftest.py** — Shared Fixtures

Provides synthetic test data fixtures:

```python
# Synthetic BOLD timeseries (90, 90, 90, 480) with implanted 0.7 correlation
@pytest.fixture
def synthetic_bold_timeseries():
    """Returns (bold_data, metadata) with:
    - White noise background
    - Known seed ROI with autocorrelation
    - Target voxels with implanted 0.7 correlation
    """

# Subject metadata (80 scans: 40 subjects × 2 sessions)
@pytest.fixture
def synthetic_subject_metadata():
    """DataFrame with columns:
    subject_id, session, group, age, sex, mean_fd, time, group_code
    Known effects:
    - Group difference = 0.5 SD
    - Age effect = 0.1 SD
    """

# Voxel maps with known group effect
@pytest.fixture
def synthetic_voxel_maps():
    """(80, 90, 90, 90) statistical maps with:
    - Background N(0,1)
    - Group effect = 0.5 SD at central voxel
    - Expected t-statistic ~2.5
    """

# Seed connectivity maps with z-normalization
@pytest.fixture
def synthetic_seed_maps():
    """80 z-maps computed from synthetic BOLD data"""

# Network connectivity matrix (256 DiFuMo ROIs)
@pytest.fixture
def synthetic_network_connectivity_matrix():
    """(256, 256, 80) with modular structure"""
```

**Validation Helper Functions:**
```python
assert_valid_timeseries(ts)      # No NaN, Inf, shape OK
assert_valid_correlation(r)      # r in [-1, 1]
assert_valid_pvalue(p)           # p in [0, 1]
```

---

### 2. **test_local_measures.py** — fALFF & ReHo Tests

**Test Classes:**

| Class | Purpose | Key Tests |
|-------|---------|-----------|
| `TestLocalMeasuresShape` | Output dimensionality | `test_falff_output_shape`, `test_reho_output_shape` |
| `TestLocalMeasuresValidity` | Value ranges | `test_falff_no_negative_values`, `test_reho_in_valid_range` |
| `TestFrequencyFiltering` | Band-pass filtering | `test_lowpass_filter_removes_high_freq` |
| `TestLocalMeasuresWithSyntheticData` | Synthetic data tests | `test_autocorrelation_preserved` |
| `TestLocalMeasuresRobustness` | Edge cases | `test_handling_constant_voxel`, `test_handling_motion_artifacts` |
| `TestLocalMeasuresSpatialConsistency` | Spatial properties | `test_seed_region_higher_than_background` |

**Key Assertions:**
- fALFF: non-negative, no NaN/Inf, shape = (90, 90, 90)
- ReHo: in [0, 1], standardized, spatially smooth
- Implanted autocorrelation preserved in seed (AR1 ≈ 0.3)

---

### 3. **test_seed_connectivity.py** — Seed-Based Connectivity Tests

**Test Classes:**

| Class | Purpose |
|-------|---------|
| `TestSeedExtraction` | Single voxel and ROI extraction |
| `TestCorrelationComputation` | Correlation validity and range |
| `TestZMapComputation` | Fisher z-transform, normalization |
| `TestSeedConnectivityMaps` | Map file validity |
| `TestMultipleSeedAnalysis` | Multiple seed independence |

**Key Checks:**
- Seed-seed correlation = 1.0
- All correlations in [-1, 1]
- Implanted correlation (0.7) recovered in target voxels
- Z-maps approximately N(0, 1) in background
- Z-maps ~0.3±0.2 in seed region (reflects implanted correlation)

---

### 4. **test_lme_model.py** — Linear Mixed Effects Tests

**Test Classes:**

| Class | Purpose |
|-------|---------|
| `TestLMEModelConvergence` | Model fitting and convergence |
| `TestLMEEffectSizeEstimation` | Effect size recovery |
| `TestLMECovariateHandling` | Standardization, missing data |
| `TestLMESingularityHandling` | Degenerate cases (catches bugs!) |
| `TestLMEMetadataValidation` | Input validation |
| `TestLMEVoxelBatchProcessing` | Batch processing consistency |
| `TestLMEFormulaParsing` | Formula construction |
| `TestLMEPValueComputation` | P-value derivation |

**Known Issues Detected:**
- ✅ Singular design matrices (all subjects in one group)
- ✅ Perfect multicollinearity (age × age_std)
- ✅ Numerical instability (NaN coefficients)
- ✅ Non-convergence (ill-conditioned data)

**Key Effect Size Test:**
```python
def test_lme_recovers_known_effect():
    # Implanted effect = 0.5 SD
    # Expected t-stat ≈ 2.5 (for 40 subjects/group)
    # Assert: 1.0 < effect_estimate < 2.0
```

---

### 5. **test_permutation_correction.py** — Multiple Comparison Correction

**Test Classes:**

| Class | Purpose |
|-------|---------|
| `TestPermutationPValues` | P-value validity and range |
| `TestPValueDistribution` | Uniform distribution under null |
| `TestPermutationTestMultipleComparisons` | Bonferroni, FDR, FWER |
| `TestClusterExtraction` | 3D cluster connectivity |
| `TestClusterThresholding` | Minimum size filtering |
| `TestClusterLabeling` | Anatomical mapping |
| `TestClusterStatistics` | Size, mean, peak reporting |
| `TestPermutationTestParameters` | Parameter adequacy |

**Critical Tests:**
- ✅ P-values in [0, 1] (no NaN/Inf)
- ✅ P-values uniform under null (K-S test)
- ✅ Bonferroni adjustment reduces alpha correctly
- ✅ Cluster-level threshold less stringent than voxel-level

---

### 6. **test_integration.py** — End-to-End Pipeline Tests

**Test Classes:**

| Class | Purpose |
|-------|---------|
| `TestPipelineExecutionMinimal` | Minimal viable pipeline (2 subjects) |
| `TestLocalMeasuresPipeline` | Stage 1: Local measures |
| `TestSeedConnectivityPipeline` | Stage 2: Seed connectivity |
| `TestGroupAnalysisPipeline` | Stage 3: Group LME |
| `TestOutputConsistency` | Data flow consistency |
| `TestStatisticalModelConsistency` | Model consistency across stages |
| `TestOutputFileStructure` | Directory structure, naming conventions |
| `TestPipelineErrorHandling` | Graceful error handling |
| `TestPipelineReproducibility` | Deterministic results |
| `TestPipelineMemoryEfficiency` | No memory leaks |

**Full Workflow Test:**
```python
def test_pipeline_2subjects_minimal():
    # 1. Load BOLD data (2 subjects, 2 sessions = 4 scans)
    # 2. Compute local measures (fALFF, ReHo)
    # 3. Compute seed connectivity (DiFuMo seeds)
    # 4. Fit LME model (even with 4 scans, should work)
    # 5. Check outputs exist and have valid structure
```

---

### 7. **test_validation.py** — Output Validation

**Test Classes:**

| Class | Purpose |
|-------|---------|
| `TestNIfTIValidity` | NIfTI file integrity |
| `TestInvalidNIfTIDetection` | Detect corrupted files |
| `TestNIfTIStatMapValidity` | Z-map, t-map, p-map ranges |
| `TestNIfTIMNIAlignment` | MNI space alignment check |
| `TestStatisticalTableValidity` | CSV/TSV format validation |
| `TestRoiDefinitionValidity` | Binary mask validity |
| `TestConfoundRegressorValidity` | Confound file format |
| `TestGroupAnalysisOutput` | Group stat map validity |
| `TestReproducibilityOfOutputs` | Output reproducibility |

**File Validation Examples:**
```python
def test_nifti_no_nan_values():
    # Load all .nii.gz files
    # Assert: no NaN, no Inf
    # Assert: shape = (181, 217, 181) or (90, 90, 90)

def test_cluster_table_stat_validity():
    # Load cluster CSV
    # Assert: p_value in [0, 1]
    # Assert: t_stat > threshold
    # Assert: n_voxels > 0
    # Assert: coordinates in MNI mm, not voxel indices
```

---

## Synthetic Data Specifications

### BOLD Timeseries
```
Shape: (90, 90, 90, 480)
Composition:
  - White noise background: N(0, 1)
  - Low-frequency trend: linear drift ≈ 0.3
  - Seed voxel: AR(1) process, ρ=0.3, autocorr ≈ 0.3
  - Target voxels: correlated with seed, r ≈ 0.7
Scale: ~500 ± 100 (realistic fMRI units)
Known Effects:
  ✓ Seed-seed autocorrelation = 0.3
  ✓ Seed-target correlation = 0.7
  ✓ Background: white noise
```

### Subject Metadata
```
Rows: 80 (40 subjects × 2 sessions)
Columns:
  - subject_id: "sub-033" to "sub-082"
  - session: 1 or 2
  - group: "control" (20) or "intervention" (20)
  - age: Uniform(50, 75) years, increases per session
  - sex: Balanced M/F
  - mean_fd: Exponential(0.2) + 0.05 mm
  - time: 0 (session 1) or 1 (session 2)
Known Effects:
  ✓ Group difference (if present): 0.5 SD
  ✓ Age effect: -0.1 SD per decade
  ✓ Sex effect: ~0.1 SD
```

### Voxel Maps
```
Shape: (80, 90, 90, 90)
Content:
  - Background: N(0, 1)
  - Central voxel [45,45,45]:
    - Control group (0-40): N(0, 1)
    - Intervention group (40-80): N(0.5, 1)  ← Implanted effect
Expected Statistics:
  ✓ t-statistic ≈ 2.5 (two-sample t-test, 40/group)
  ✓ p-value ≈ 0.015 (uncorrected)
```

---

## Interpreting Test Results

### All Tests Pass ✅
```
========== 150 passed in 2.34s ==========
```
**Interpretation:** Pipeline is numerically stable; no silent bugs detected.

### Specific Test Fails ❌
```
FAILED tests/test_lme_model.py::TestLMEEffectSizeEstimation::test_lme_recovers_known_effect
```
**Action:**
1. Check if effect size estimation is off (suggests algorithmic bug)
2. Verify LME formula is correct
3. Check covariate standardization
4. Run with `pytest -vv --tb=long` for detailed traceback

### NaN/Inf Detected ⚠️
```
FAILED tests/test_validation.py::TestNIfTIValidity::test_nifti_no_nan_values
AssertionError: NIfTI contains NaN values
```
**Action:**
1. This is critical—NaN p-values silently invalidate results
2. Check for:
   - Division by zero (std = 0)
   - Singular matrices (high multicollinearity)
   - Invalid correlations (const timeseries)
3. Add input validation to pipeline script

### Singular Matrix Error ⚠️
```
FAILED tests/test_lme_model.py::TestLMESingularityHandling::test_degenerate_group_variable
```
**Action:**
1. Check metadata for duplicate subjects or sessions
2. Verify group variable has > 1 unique value
3. Check for redundant covariates

---

## Common Test Patterns

### Pattern 1: Synthetic Data Validation
```python
def test_feature_works_on_synthetic():
    bold_data, metadata = synthetic_bold_timeseries
    
    # Verify input has expected properties
    assert bold_data.shape == (90, 90, 90, 480)
    assert not np.isnan(bold_data).any()
    
    # Compute feature
    output = compute_feature(bold_data)
    
    # Verify output validity
    assert output.shape == (90, 90, 90)
    assert (output >= 0).all()
```

### Pattern 2: Known Effect Recovery
```python
def test_effect_recovered():
    # Create data with known effect
    group = np.tile([0, 1], 20)
    effect = 1.5
    y = group * effect + np.random.normal(0, 0.5, 40)
    
    # Estimate effect
    coef = np.mean(y[group==1]) - np.mean(y[group==0])
    
    # Verify close to true effect
    assert 1.0 < coef < 2.0
```

### Pattern 3: Distribution Testing
```python
def test_null_distribution():
    # Generate N(0, 1) test statistics
    stats = np.random.normal(0, 1, 1000)
    
    # Test against expected distribution
    mean_stat = np.mean(stats)
    std_stat = np.std(stats)
    
    assert abs(mean_stat) < 0.1
    assert 0.9 < std_stat < 1.1
```

---

## Adding New Tests

### Step 1: Create Test File (if needed)
```bash
touch tests/test_my_feature.py
```

### Step 2: Import Fixtures and Utils
```python
import pytest
import numpy as np
from conftest import assert_valid_timeseries, assert_valid_pvalue
```

### Step 3: Write Test Class
```python
class TestMyFeature:
    """Test my new feature."""
    
    def test_basic_functionality(self, synthetic_bold_timeseries):
        """Test basic functionality."""
        bold_data, metadata = synthetic_bold_timeseries
        
        # YOUR TEST HERE
        result = my_function(bold_data)
        
        assert result.shape == expected_shape
    
    def test_edge_case(self):
        """Test edge case."""
        data = np.ones((10, 10, 10, 100))  # Constant signal
        
        result = my_function(data)
        
        # Should handle gracefully (not crash, not NaN)
        assert result is not None
```

### Step 4: Create Synthetic Data Fixture (if needed)
```python
@pytest.fixture
def my_synthetic_data():
    """Generate synthetic data for my feature."""
    np.random.seed(42)
    
    # Create data with known properties
    data = np.random.normal(0, 1, (90, 90, 90, 480))
    
    metadata = {
        'known_property': 'value',
    }
    
    return data, metadata
```

### Step 5: Run and Debug
```bash
pytest tests/test_my_feature.py -v
pytest tests/test_my_feature.py::TestMyFeature::test_basic_functionality -vv
```

---

## Troubleshooting

### Issue: Tests Hang / Timeout
**Solution:** Integration tests may be slow. Run unit tests only:
```bash
pytest tests/test_local_measures.py tests/test_lme_model.py -v
```

### Issue: ImportError (missing nibabel, scipy, etc.)
**Solution:** Install dependencies:
```bash
pip install -r /home/clivewong/proj/longevity/neuconn_app/requirements.txt
pip install pytest pytest-cov
```

### Issue: Fixture Not Found
**Solution:** Ensure `conftest.py` is in `tests/` directory:
```bash
ls -la /home/clivewong/proj/longevity/tests/conftest.py
```

### Issue: Random Seed Not Working
**Solution:** Ensure `np.random.seed()` is called at start of test:
```python
def test_deterministic():
    np.random.seed(42)
    data = np.random.normal(0, 1, 100)
    # ...
```

---

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Test Pipeline

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - run: pip install -r neuconn_app/requirements.txt pytest pytest-cov
      - run: pytest tests/ -v --cov=script
      - run: coverage report --fail-under=70
```

---

## References

- **Synthetic Data Generation:** `conftest.py`
- **Frequency Domain Analysis:** TR=0.8s, Nyquist=0.625Hz, Band=0.01-0.1Hz
- **MNI Space:** 2mm isotropic, shape=(181,217,181), affine standard
- **Statistical Tests:** Two-tailed, α=0.05, Bonferroni/FDR for multiple comparisons
- **Cluster Thresholding:** Permutation-based, minimum size typically 10-50 voxels

---

## Test Maintenance

**Review tests quarterly for:**
- ✓ New pipeline features not covered by tests
- ✓ Known issues that tests should catch
- ✓ Changes to fMRIPrep/atlas versions requiring fixture updates
- ✓ Performance regressions

**Update synthetic data when:**
- TR changes (update frequency band)
- Atlas changes (update N_DIFUMO_ROIS)
- New covariate added (extend metadata fixture)

