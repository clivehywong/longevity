# Copilot CLI Skills

This directory contains skill documentation for the Copilot CLI, providing domain expertise and best practices for this project.

## Available Skills

### 1. **skill-statsmodels-fsl.md** - Statsmodels + FSL Thresholding
   **Size**: 51 KB | **Sections**: 13  
   **Purpose**: Comprehensive guide for group-level statistical analysis using Linear Mixed Effects (LME) models and FSL thresholding for multiple comparison correction and anatomical labeling.

   **Key Topics**:
   - Statsmodels LME formula syntax and fitting
   - Data preparation: flattening brain maps, long-format DataFrames
   - Model specifications: intervention, longitudinal, multi-region designs
   - FSL cluster-based thresholding (GRF correction)
   - TFCE and permutation testing alternatives
   - atlasq integration for anatomical labeling
   - Complete working code examples (Python + Bash)
   - Error handling and troubleshooting

   **Context**: Longevity neuroimaging study (44 subjects, 40 with 2 sessions)

   **When to Use**:
   - Implementing group-level statistical analysis
   - Setting up multiple comparison correction
   - Creating anatomically-labeled cluster reports
   - Debugging LME model fitting
   - Configuring FSL cluster workflows

---

## Skills Index

| Skill | Topics | Use For |
|-------|--------|---------|
| **statsmodels-fsl** | LME, GRF, TFCE, atlasq | Group stats, cluster labeling |

---

## How Skills Are Used

Copilot CLI agents automatically reference these skills during related development tasks. Skills provide:

1. **Pattern Examples** - Real working code from the project
2. **Best Practices** - Conventions and recommendations specific to this codebase
3. **Troubleshooting** - Common issues and solutions
4. **Complete Workflows** - End-to-end examples for complex tasks

### Example Agent Prompt

```
You are implementing group-level statistical analysis for a neuroimaging study.
Reference the statsmodels-fsl skill for:
- Formula syntax for longitudinal intervention analysis
- Data preparation (long-format DataFrame from brain maps)
- FSL cluster thresholding with GRF correction
- Anatomical labeling via atlasq
- Output formats (CSV cluster tables, NIfTI maps, HTML reports)
```

---

## Creating New Skills

To add a new skill to this directory:

1. **Create `skill-<topic>.md`** with clear sections and code examples
2. **Include**:
   - Purpose and context (what project/problem domain)
   - Detailed explanations (not just code snippets)
   - Real working examples from the codebase
   - Error handling and edge cases
   - Troubleshooting guide
3. **Reference existing conventions** in the project (paths, naming, configs)
4. **Add to this README.md**

---

## Project Context

- **Repository**: longevity (neuroimaging analysis)
- **Study**: Longitudinal walking intervention
- **Subjects**: 44 (22 intervention, 22 control); 40 with 2 sessions, 4 with 1 session
- **Data**: BIDS format, preprocessed with fMRIPrep (MNI2mm + T1w)
- **Analysis**: Connectivity, local measures, group-level statistics

Key directories:
- `script/` - Analysis workflows
- `script/fsl/` - FSL thresholding scripts (cluster.sh, tfce-cluster.sh)
- `bids/` - Raw/derivative data
- `neuconn_app/` - Streamlit QC/orchestration UI

---

## Links

- **Developer Docs**: See `docs/developer/README.md` for architecture
- **User Docs**: See `docs/user/README.md` for workflows and setup
- **Memory/Context**: See `.claude/memory/` for persistent session info

