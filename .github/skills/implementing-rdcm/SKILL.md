---
name: implementing-rdcm
description: Implementing regression Dynamic Causal Modeling (rDCM) for effective connectivity analysis on resting-state fMRI data. Use when estimating directed connectivity parameters between brain regions using the RegressionDynamicCausalModeling.jl Julia package.
license: Apache-2.0
---

# Implementing rDCM (Regression Dynamic Causal Modeling)

rDCM is a computationally efficient variant of DCM for fMRI that estimates **directed (effective) connectivity** between brain regions using a Bayesian linear regression framework. It scales to whole-brain networks, making it suitable for large-scale analyses.

**Package**: [RegressionDynamicCausalModeling.jl](https://github.com/ComputationalPsychiatry/RegressionDynamicCausalModeling.jl) (Julia)  
**Part of**: [TAPAS](https://translationalneuromodeling.github.io/tapas/) toolbox (TNU, ETH Zürich)

---

## Key Concepts

| Term | Meaning |
|------|---------|
| A matrix | Directed connectivity (region-to-region), inferred parameter |
| C matrix | External input to regions (set to identity for resting-state) |
| `RigidRdcm` | Fixed network architecture — all connections tested |
| `SparseRdcm` | Sparse network — learns which connections exist via binary indicators (Z matrix) |
| `invert()` | Runs variational Bayes inversion to estimate posterior of A |
| `μ` (output) | Posterior mean of connectivity parameters (nr × nr matrix) |
| `Z` (SparseOutput) | Posterior probability each connection exists (0–1) |
| Free energy `F` | Model evidence — use to compare models |

---

## Data Requirements

rDCM has **strict data quality requirements**. Verify before proceeding:

| Requirement | Recommendation | Longevity Study |
|-------------|---------------|-----------------|
| TR | ≤ 1.0 s (ideally ≤ 0.8 s) | ✅ TR = 0.8 s |
| Volumes | ≥ 200–400 per session | ✅ 480 volumes |
| SNR | High SNR | ✅ 3T Prisma |
| Denoising | Global signal regression or equivalent | ✅ XCP-D FC+GSR |
| Space | Any standard space (MNI preferred) | ✅ MNI 2mm |

> **Warning**: rDCM is not reliable on low-quality data (low SNR, slow TR, few volumes). Results on non-compliant data should be interpreted with caution or not at all.

---

## Environment Setup

### Install Julia (if not present)

```bash
# Check if Julia is installed
julia --version

# Install Julia (if needed)
curl -fsSL https://install.julialang.org | sh
# Or via juliaup:
curl -fsSL https://julialang.org/juliaup/bin/juliaup.sh | sh
```

### Install rDCM Package

```julia
# In Julia REPL:
using Pkg
Pkg.add("RegressionDynamicCausalModeling")

# Optional: install visualization dependencies
Pkg.add(["CairoMakie", "CSV", "DataFrames", "NPZ", "HDF5"])
```

### Verify Installation

```julia
using RegressionDynamicCausalModeling

# Test with the built-in example
dcm = load_example_DCM()
y, _, _, _ = generate_BOLD(dcm; SNR=10)
opt = Options(RigidInversionParams(); synthetic=true, verbose=1)
rdcm = RigidRdcm(dcm)
output = invert(rdcm, opt)
println("Verification passed. F = $(output.F)")
```

---

## Data Preparation

rDCM takes **parcellated BOLD timeseries** as input (not voxel-level data). Use XCP-D outputs.

### Step 1: Extract ROI Timeseries from XCP-D

XCP-D already provides parcellated timeseries. Locate them:

```
derivatives/preprocessing/xcpd/
└── sub-{id}/ses-{id}/func/
    └── sub-{id}_ses-{id}_task-rest_space-MNI152NLin2009cAsym_res-2_
        atlas-{atlas}_timeseries.tsv   ← Use this
```

Supported atlases in XCP-D:
- `Schaefer417` (Schaefer 400 + Tian 17 subcortical)
- `Gordon333`

### Step 2: Load Timeseries in Julia

```julia
using CSV, DataFrames

# Load timeseries TSV from XCP-D
function load_xcpd_timeseries(tsv_path::String)
    df = CSV.read(tsv_path, DataFrame)
    # Each column = one ROI, each row = one timepoint
    # Return as matrix: timepoints × regions
    return Matrix{Float64}(df)
end

# Example
ts = load_xcpd_timeseries("derivatives/preprocessing/xcpd/sub-066/ses-01/func/sub-066_ses-01_task-rest_space-MNI152NLin2009cAsym_res-2_atlas-Schaefer417_timeseries.tsv")
n_timepoints, n_regions = size(ts)
println("Loaded: $n_timepoints timepoints × $n_regions regions")
```

### Step 3: Build DCM Structure for Resting-State

For resting-state fMRI, there is no external input — use an identity C matrix:

```julia
using RegressionDynamicCausalModeling

TR = 0.8  # seconds (longevity study)

function build_restingstate_dcm(timeseries::Matrix{Float64}, TR::Float64; region_names=nothing)
    n_timepoints, n_regions = size(timeseries)
    
    # BOLD signal structure
    Y = BoldY(
        y = timeseries,        # T × nr matrix
        dt = TR,               # sampling interval in seconds
        name = isnothing(region_names) ? ["region_$i" for i in 1:n_regions] : region_names
    )
    
    # For resting-state: no external input (use identity-like structure)
    # Create a minimal constant input required by rDCM
    U = InputU(
        u = ones(n_timepoints, 1),   # constant input
        dt = TR,
        name = ["constant"]
    )
    
    # Initial A matrix (fully connected prior) — rDCM will estimate actual values
    A = ones(n_regions, n_regions) - I  # off-diagonal connections
    C = zeros(n_regions, 1)              # no direct inputs for resting-state
    
    return LinearDCM(A, C, Y, U)
end

dcm = build_restingstate_dcm(ts, TR)
```

---

## Model Selection: RigidRdcm vs SparseRdcm

| Feature | `RigidRdcm` | `SparseRdcm` |
|---------|-------------|--------------|
| Network | Fixed (all-to-all) | Learns which connections exist |
| Speed | Fast | Slower (multiple reruns) |
| Output | `μ` (connectivity strengths) | `μ` + `Z` (binary indicators) |
| Use when | Hypothesis-driven (known network) | Exploratory (unknown network structure) |
| Regions | Any | Works best with ≤ 50–100 regions |
| Recommended | ✅ Start here for validation | Use after RigidRdcm confirms feasibility |

**For the longevity study**: Start with `RigidRdcm` on a subset of ROIs (e.g., 50 DMN regions). Expand to `SparseRdcm` for whole-brain analysis.

---

## Running rDCM Inversion

### Rigid rDCM (Fixed Network)

```julia
using RegressionDynamicCausalModeling

# 1. Create rDCM model from DCM
rdcm = RigidRdcm(dcm)

# 2. Set inversion options
#    maxIter: max iterations per region (default: 500)
#    tol: convergence tolerance (default: 1e-3)
opt = Options(
    RigidInversionParams(maxIter=500, tol=1e-3);
    synthetic = false,   # real data (not synthetic)
    verbose = 1          # 0=silent, 1=standard, 2=verbose
)

# 3. Invert (estimate posterior)
output = invert(rdcm, opt)

# 4. Key results
println("Free energy: $(output.F)")
println("Posterior mean connectivity (A matrix): $(size(output.μ))")  # nr × nr
```

### Sparse rDCM (Data-Driven Network)

```julia
# Create sparse rDCM model
rdcm_sparse = SparseRdcm(dcm)

# Set sparse inversion options
opt_sparse = Options(
    SparseInversionParams(maxIter=500, tol=1e-3, reruns=100, restrictInputs=true);
    synthetic = false,
    verbose = 1
)

# Invert
output_sparse = invert(rdcm_sparse, opt_sparse)

# Additional output: Z matrix (connection probability)
println("Connection probabilities (Z matrix): $(size(output_sparse.Z))")  # nr × nr
# Z[i,j] > 0.5 → connection from j to i is likely present
```

---

## Output Interpretation

### RigidOutput Fields

| Field | Type | Meaning |
|-------|------|---------|
| `F` | Float64 | Total model log-evidence (negative free energy) |
| `F_r` | Vector | Per-region free energy |
| `μ` | Matrix (nr×nr) | **Posterior mean connectivity** — rows=target, cols=source |
| `Σ` | Vector of matrices | Posterior covariance per region |
| `α`, `β` | Vectors | Posterior noise (Gamma distribution parameters) |
| `iter_all` | Vector | Iterations until convergence per region |

### Reading the A matrix (μ)

```julia
# μ[i, j] = connection strength from region j → region i
# Positive = excitatory, Negative = inhibitory
A_estimated = output.μ

# Self-inhibition is on the diagonal (typically negative)
# Off-diagonal: directed connectivity

# For SparseRdcm, threshold by connection probability
Z = output_sparse.Z
A_thresholded = A_estimated .* (Z .> 0.5)  # only connections with >50% probability
```

### Saving Results

```julia
using CSV, DataFrames, HDF5

function save_rdcm_results(output, subject_id, session_id, region_names, out_dir)
    mkpath(out_dir)
    
    # Save connectivity matrix as CSV
    A_df = DataFrame(output.μ, region_names)
    insertcols!(A_df, 1, :source => region_names)
    CSV.write(joinpath(out_dir, "$(subject_id)_$(session_id)_A_matrix.csv"), A_df)
    
    # Save full output as HDF5 for later analysis
    h5open(joinpath(out_dir, "$(subject_id)_$(session_id)_rdcm_output.h5"), "w") do file
        file["A_posterior_mean"] = output.μ
        file["free_energy"] = output.F
        file["free_energy_per_region"] = output.F_r
        if hasproperty(output, :Z)
            file["connection_probability"] = output.Z
        end
    end
end
```

---

## Batch Processing (All Subjects)

```julia
using RegressionDynamicCausalModeling, CSV, DataFrames

BIDS_DIR = "/home/clivewong/proj/longevity"
XCPD_DIR = joinpath(BIDS_DIR, "derivatives/preprocessing/xcpd")
RESULTS_DIR = joinpath(BIDS_DIR, "results/connectivity/rdcm")
TR = 0.8

# Find all timeseries files
subjects = ["sub-066", "sub-068", "sub-072", "sub-077"]  # or scan XCPD_DIR
sessions = ["ses-01", "ses-02"]
atlas = "Schaefer417"

for sub in subjects, ses in sessions
    tsv_glob = glob("*atlas-$(atlas)_timeseries.tsv",
                    joinpath(XCPD_DIR, sub, ses, "func"))
    isempty(tsv_glob) && (println("Missing: $sub/$ses"); continue)
    
    ts = load_xcpd_timeseries(tsv_glob[1])
    dcm = build_restingstate_dcm(ts, TR)
    rdcm = RigidRdcm(dcm)
    opt = Options(RigidInversionParams(); synthetic=false, verbose=0)
    
    output = invert(rdcm, opt)
    save_rdcm_results(output, sub, ses, nothing, joinpath(RESULTS_DIR, sub, ses))
    println("✓ $sub/$ses: F=$(round(output.F; digits=2))")
end
```

---

## Visualization

### Python (for integration with existing pipeline)

```python
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

def plot_connectivity_matrix(csv_path, title="rDCM Effective Connectivity", threshold=None):
    """Plot rDCM A matrix as a heatmap."""
    df = pd.read_csv(csv_path, index_col="source")
    A = df.values
    
    if threshold is not None:
        A = A * (np.abs(A) > threshold)
    
    fig, ax = plt.subplots(figsize=(12, 10))
    sns.heatmap(A, 
                center=0, 
                cmap="RdBu_r", 
                ax=ax,
                xticklabels=df.columns,
                yticklabels=df.index,
                cbar_kws={"label": "Connectivity Strength"})
    ax.set_title(title)
    ax.set_xlabel("Source Region")
    ax.set_ylabel("Target Region")
    plt.tight_layout()
    return fig

# Group-level average
def group_average_connectivity(result_dir, subjects, sessions):
    """Average A matrices across subjects/sessions."""
    matrices = []
    for sub in subjects:
        for ses in sessions:
            csv = f"{result_dir}/{sub}/{ses}/{sub}_{ses}_A_matrix.csv"
            if os.path.exists(csv):
                df = pd.read_csv(csv, index_col="source")
                matrices.append(df.values)
    
    group_mean = np.mean(matrices, axis=0)
    group_std = np.std(matrices, axis=0)
    return group_mean, group_std, df.columns.tolist()
```

---

## Integration with Longevity Project

### File Locations

```
longevity/
├── derivatives/preprocessing/xcpd/
│   └── sub-{id}/ses-{id}/func/
│       └── *atlas-Schaefer417_timeseries.tsv   ← Input
├── results/connectivity/rdcm/
│   ├── sub-{id}/ses-{id}/
│   │   ├── {id}_A_matrix.csv                   ← Output
│   │   └── {id}_rdcm_output.h5                 ← Full output
│   └── group/
│       ├── group_mean_A.csv
│       └── group_mean_A_heatmap.png
└── script/
    └── run_rdcm.jl                              ← Batch script
```

### Project-Specific Notes

- **TR = 0.8 s** — meets rDCM's fast-TR requirement ✅
- **480 volumes** — sufficient for stable estimates ✅
- **Use XCP-D FC+GSR variant** — global signal regression recommended for rDCM
- **2 sessions per subject** — run rDCM separately per session, then compare
- **Start with ≤ 50 ROIs** — use DMN or salience network subset before whole-brain
- **Whole-brain**: Schaefer 400 + Tian S2 (417 total ROIs) is feasible with `SparseRdcm`

---

## Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `Not positive definite covariance` | Singular BOLD data | Check for constant or NaN timeseries columns |
| `Size of y and name vector don't match` | Wrong region count | Verify atlas TSV columns match name vector |
| `Invalid inversion parameters` | maxIter ≤ 0 | Use positive maxIter (e.g., 500) |
| Slow convergence | Too many regions for RigidRdcm | Switch to SparseRdcm or reduce region count |
| Poor F (very negative) | Low data quality or wrong TR | Check TR matches BoldY.dt exactly |
| NaN in output μ | Ill-conditioned data | Check for zero-variance timeseries; remove flat ROIs |

---

## Required Citations

Always cite when using rDCM:

1. **TAPAS framework**: Frässle et al. (2021). TAPAS. *Frontiers in Psychiatry* 12, 857.
2. **rDCM original**: Frässle et al. (2017). Regression DCM for fMRI. *NeuroImage* 155, 406–421.
3. **Sparse rDCM**: Frässle et al. (2018). Generative model of whole-brain EC. *NeuroImage* 179, 505–529.
4. **Resting-state rDCM**: Frässle et al. (2021). rDCM for resting-state fMRI. *Human Brain Mapping* 42, 2159–2180.

---

## References

- [Package repository](https://github.com/ComputationalPsychiatry/RegressionDynamicCausalModeling.jl)
- [Documentation](https://computationalpsychiatry.github.io/RegressionDynamicCausalModeling.jl/stable/)
- [TAPAS toolbox](https://translationalneuromodeling.github.io/tapas/)
- [Original MATLAB implementation](https://github.com/translationalneuromodeling/tapas/tree/master/rDCM)
