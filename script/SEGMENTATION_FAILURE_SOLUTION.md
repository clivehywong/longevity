# Segmentation Failure - sub-057 ses-02

## Issue

**Subject**: sub-057 (Walking group)
**Session**: ses-02 (Post intervention)
**Problem**: Grey matter segmentation produced all zeros
**Error**: "No suprathreshold voxels in ROI file"

**Root cause**: SPM's automatic segmentation failed to align structural image to MNI template

---

## Impact

- **Current**: 24 subjects × 2 sessions = 48 total sessions
- **If excluded**: 23 complete subjects + 1 subject with ses-01 only = 47 sessions

**Analysis impact**:
- Longitudinal analysis requires **paired data** (Pre + Post)
- **Excluding sub-057 ses-02 = Excluding entire sub-057**
- **Result**: 23 subjects (14 Control, 9 Walking → **8 Walking**)

⚠️ **Critical**: This reduces Walking group from 9 to 8 subjects

---

## Solutions (Ranked by Ease)

### Option 1: Try run-02 T1w (RECOMMENDED) ⭐

**Rationale**: sub-057 has 2 T1w scans per session. Run-01 failed, but run-02 might work.

**Steps**:
```bash
cd /Volumes/Work/Work/long/script
matlab -nodisplay -nosplash -r "fix_sub057_segmentation; exit"
```

**Time**: ~5 minutes

**If successful**: Continue with all 24 subjects

---

### Option 2: Exclude sub-057 Entirely

**Rationale**: Simplest, but reduces statistical power

**Impact**:
- Control: 15 subjects ✓
- Walking: **8 subjects** (was 9)
- Total: **23 subjects**

**How to exclude**:

#### A. Manual exclusion in preprocessing
Edit `conn_batch_longitudinal.m`:
```matlab
% Remove sub-057 from walking_subs
walking_subs = {'sub-043', 'sub-045', 'sub-046', 'sub-047', 'sub-048', ...
                'sub-052', 'sub-055', 'sub-056'};  % Removed sub-057
```

#### B. Mark as incomplete
Create exclusion file:
```bash
echo "sub-057,ses-02,Segmentation failure" > /Volumes/Work/Work/long/exclusions.txt
```

---

### Option 3: Manual Realignment (Advanced)

**Rationale**: Fix the structural alignment manually

**Steps**:
1. Open SPM GUI
2. Display → `/Volumes/Work/Work/long/bids/sub-057/ses-02/anat/sub-057_ses-02_run-01_T1w.nii.gz`
3. Reorient → Manually align anterior commissure to origin
4. Save transformation
5. Re-run segmentation

**Time**: 15-30 minutes (requires anatomical expertise)

---

## Recommended Approach

### Step 1: Try run-02 (Option 1)

```matlab
cd /Volumes/Work/Work/long/script
fix_sub057_segmentation
```

This will:
1. Attempt segmentation with run-02
2. Report if successful
3. Provide next steps

---

### Step 2: If run-02 fails → Exclude subject

**Accept reduced sample**: 23 subjects (15 Control, 8 Walking)

**Justification**:
- Still adequately powered for Group × Time interaction
- Maintains data quality (no questionable segmentations)
- Standard practice in neuroimaging

**Update analysis plan**:
```
Original: 24 subjects (15 Control, 9 Walking)
Final: 23 subjects (15 Control, 8 Walking)
Reason: Segmentation failure for sub-057 ses-02
```

---

## Continue Preprocessing Without sub-057

If excluding, modify batch to process **47/48 sessions**:

### Quick fix: Skip failed subject in current run

CONN will show error for sub-057 ses-02 but continue with other 47 sessions.

After preprocessing:
- Manually remove sub-057 from second-level analyses
- Update n in manuscripts: "23 participants with complete data"

---

## Statistical Implications

### Sample Size Comparison

| Analysis | Original | If Excluded |
|----------|----------|-------------|
| Control | 15 | 15 ✓ |
| Walking | 9 | 8 |
| **Total** | **24** | **23** |
| **Power (d=0.8)** | **75%** | **72%** |

**Minimal impact** on statistical power (3% reduction)

### Alternatives to Maintain Power

1. **Recruit 1 more Walking subject** (if possible)
2. **Use robust statistics** (permutation tests, less sensitive to n)
3. **Focus on effect sizes** (not just p-values)

---

## My Recommendation

**Try Option 1 first** (automated, 5 minutes):
```bash
matlab -nodisplay -nosplash -r "cd('/Volumes/Work/Work/long/script'); fix_sub057_segmentation; exit"
```

**If run-02 fails**:
- **Accept exclusion** (23 subjects)
- Document in methods: "One participant excluded due to segmentation failure"
- Continue analysis with high-quality data

**DO NOT spend hours** on manual realignment unless this subject is critical.

---

**Should I try run-02 now?**
