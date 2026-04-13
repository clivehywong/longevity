# Cerebellar Functional Zone Classification

## Overview

The 23 cerebellar components in DiFuMo 256 have been classified into **3 functional zones** based on established neuroanatomical literature:

1. **Motor Zone** (11 components) - Primary sensorimotor
2. **Cognitive Zone** (10 components) - Executive functions, learning
3. **Vestibular Zone** (1 component) - Balance, spatial orientation

*(1 CSF component excluded from analysis)*

---

## Cerebellar Functional Zones

### 🔴 Motor Zone (11 components)
**Lobules**: IV, V, VI, VIIIb

**Functions**:
- Primary motor control
- Sensorimotor coordination
- Fine motor adjustments
- Eye movements

**Cortical Connections**:
- Primary motor cortex (M1)
- Premotor cortex (PMC)
- Somatosensory cortex (S1)

**Clinical Relevance**:
- Ataxia (coordination deficits)
- Dysmetria (impaired distance judgment)
- Gait impairment

**Walking Study Relevance**: ⭐ **PRIMARY**
- Direct sensorimotor loop for walking coordination
- Real-time gait adjustments
- Motor execution

---

### 🔵 Cognitive Zone (10 components)
**Lobules**: Crus I, Crus II, VIIb

**Functions**:
- Executive functions
- Working memory
- Language processing
- Attention
- Motor learning & planning

**Cortical Connections**:
- Prefrontal cortex (DLPFC)
- Parietal cortex
- Temporal cortex

**Clinical Relevance**:
- Planning deficits
- Attention impairment
- Cerebellar Cognitive Affective Syndrome (CCAS)

**Walking Study Relevance**: ⭐ **SECONDARY**
- Motor learning (gait pattern adaptation)
- Gait planning & strategy
- Dual-task walking (walking + cognitive task)
- Internal models of movement

---

### 🟢 Vestibular Zone (1 component)
**Lobules**: IX

**Functions**:
- Vestibular processing
- Balance control
- Spatial orientation
- Head-eye coordination

**Cortical Connections**:
- Vestibular nuclei
- Brainstem

**Clinical Relevance**:
- Balance deficits
- Vertigo
- Spatial disorientation

**Walking Study Relevance**: **TERTIARY**
- Balance maintenance during walking
- Postural adjustments

---

## DiFuMo Components by Zone

### Motor Zone (11 components)

| Component | Index | Lobule | Hemisphere |
|-----------|-------|--------|------------|
| 50 | 49 | VIIIb posterior | - |
| 69 | 68 | VIIIb anterior | - |
| 96 | 95 | IV | - |
| 154 | 153 | V | - |
| 161 | 160 | VI superior | LH |
| 173 | 172 | VI anterior | - |
| 181 | 180 | VI | - |
| 200 | 199 | V | - |
| 211 | 210 | VI | RH |
| 223 | 222 | VI superior | - |
| 233 | 232 | VI anterior | - |

**Dominant Lobule**: VI (6 components) - Primary sensorimotor cerebellum

---

### Cognitive Zone (10 components)

| Component | Index | Lobule | Hemisphere |
|-----------|-------|--------|------------|
| 36 | 35 | VIIb | - |
| 81 | 80 | Crus I | RH |
| 91 | 90 | Crus I superior | - |
| 143 | 142 | Crus I posterior | - |
| 147 | 146 | Crus I lateral | RH |
| 156 | 155 | Crus II | - |
| 172 | 171 | Crus I anterior | LH |
| 179 | 178 | Crus II | - |
| 187 | 186 | VIIb | - |
| 209 | 208 | Crus I posterior | LH |

**Dominant Lobule**: Crus I (6 components) - Cognitive cerebellum

---

## Refined Hypothesis-Driven Network Pairs

### 1. Motor Cortex ↔ Motor Cerebellum ⭐⭐⭐
**Primary Hypothesis**

- **Networks**: Somatomotor (26) ↔ Cerebellar_Motor (11)
- **Connections**: 286 pairs
- **Hypothesis**: Walking intervention **strengthens sensorimotor integration**
- **Expected**: Increased connectivity Post vs Pre in Walking group
- **Mechanism**: Direct motor loop (M1 → Cerebellum VI/V → M1)

---

### 2. Motor Cortex ↔ Cognitive Cerebellum ⭐⭐
**Motor Learning Hypothesis**

- **Networks**: Somatomotor (26) ↔ Cerebellar_Cognitive (10)
- **Connections**: 260 pairs
- **Hypothesis**: Walking training **engages cerebellar learning systems**
- **Expected**: Increased connectivity during skill acquisition phase
- **Mechanism**: Motor cortex recruits Crus I/II for gait optimization

---

### 3. Frontoparietal ↔ Cognitive Cerebellum ⭐⭐
**Executive-Motor Integration**

- **Networks**: FrontoParietal (26) ↔ Cerebellar_Cognitive (10)
- **Connections**: 260 pairs
- **Hypothesis**: **Cognitive control of complex motor sequences**
- **Expected**: Stronger in Walking group (intentional gait training)
- **Mechanism**: FPCN guides cerebellar motor learning

---

### 4. Default Mode ↔ Cognitive Cerebellum ⭐
**Predictive Processing**

- **Networks**: DefaultMode (32) ↔ Cerebellar_Cognitive (10)
- **Connections**: 320 pairs
- **Hypothesis**: Cerebellar contributions to **internal models and prediction**
- **Expected**: Network reconfiguration with training
- **Mechanism**: DMN-cerebellum creates predictive models of walking

---

## Comparison: Motor vs Cognitive Cerebellar Connectivity

| Aspect | Motor Cerebellum | Cognitive Cerebellum |
|--------|------------------|---------------------|
| **Components** | 11 | 10 |
| **Lobules** | IV, V, VI, VIIIb | Crus I, Crus II, VIIb |
| **Primary Function** | Motor execution | Motor learning, planning |
| **Cortical Partners** | M1, PMC, S1 | DLPFC, parietal cortex |
| **Walking Relevance** | Direct gait control | Gait strategy, adaptation |
| **Intervention Effect** | Immediate | Delayed (learning) |
| **Expected Change** | ↑ Connectivity strength | ↑ Network integration |

---

## Analysis Strategy

### Primary Analyses (Motor Zones)

1. **Motor-Motor connectivity** (286 pairs)
   - Main effect: Group × Time interaction
   - Hypothesis: Walking > Control in Post-Pre change
   - FDR correction across 286 pairs

2. **Within-motor cerebellar connectivity** (55 pairs)
   - 11 × 10 / 2 = 55 unique pairs
   - Test network cohesion changes

### Secondary Analyses (Cognitive Zones)

3. **Motor-Cognitive connectivity** (260 pairs)
   - Test motor learning engagement
   - Correlate with behavioral improvements

4. **FPCN-Cognitive connectivity** (260 pairs)
   - Executive control of motor learning

### Exploratory

5. **Motor vs Cognitive cerebellar engagement**
   - Compare effect sizes: Motor-Motor vs Motor-Cognitive
   - Test differential recruitment hypothesis

6. **Laterality effects**
   - LH vs RH cerebellar components
   - Relevant for motor dominance

---

## Expected Results Pattern

### Scenario 1: Pure Motor Training
- **Strong**: Motor-Motor connectivity ↑↑
- **Weak**: Motor-Cognitive connectivity ↑
- **Interpretation**: Automatized gait, no learning engagement

### Scenario 2: Motor Learning
- **Strong**: Motor-Motor connectivity ↑↑
- **Strong**: Motor-Cognitive connectivity ↑↑
- **Interpretation**: Active skill acquisition

### Scenario 3: Cognitive-Motor Integration
- **Strong**: Motor-Motor connectivity ↑↑
- **Strong**: Motor-Cognitive connectivity ↑↑
- **Strong**: FPCN-Cognitive connectivity ↑↑
- **Interpretation**: Executive-guided motor optimization

---

## Files Created

- ✅ `difumo256_network_definitions.json` - Updated with cerebellar zones
- ✅ `cerebellar_functional_zones_summary.csv` - Functional zone summary table
- ✅ `classify_cerebellar_zones.py` - Classification script

---

## Usage in Python

```python
import json

# Load network definitions
with open('atlases/difumo256_network_definitions.json') as f:
    networks = json.load(f)

# Access cerebellar zones
motor_cereb = networks['networks']['Cerebellar_Motor']  # 11 components
cognitive_cereb = networks['networks']['Cerebellar_Cognitive']  # 10 components
vestibular_cereb = networks['networks']['Cerebellar_Vestibular']  # 1 component

# Get refined hypothesis pairs
motor_motor = networks['hypothesis_driven_pairs_refined']['Motor_Cerebellar_Motor']
motor_cognitive = networks['hypothesis_driven_pairs_refined']['Motor_Cerebellar_Cognitive']

# Component details
cerebellar_details = networks['special_regions']['cerebellar_details']
for comp in cerebellar_details:
    if comp['functional_zone'] == 'Motor':
        print(f"{comp['name']} -> {comp['function_description']}")
```

---

## Next Steps

1. Extract DiFuMo timeseries from CONN (after preprocessing)
2. Compute Motor-Motor connectivity (286 pairs)
3. Compute Motor-Cognitive connectivity (260 pairs)
4. Test Group × Time interaction for each pair
5. FDR correction across all tests
6. Compare Motor vs Cognitive cerebellar engagement

**Ready for implementation!**
