"""
Longevity Neuroimaging Pipeline Test Suite

Comprehensive test suite for statistical pipeline validation using synthetic data.

Test Modules:
- test_local_measures.py: fALFF and ReHo computation
- test_seed_connectivity.py: Seed-based connectivity analysis
- test_lme_model.py: Linear mixed effects modeling
- test_permutation_correction.py: Multiple comparison correction
- test_integration.py: End-to-end pipeline tests
- test_validation.py: Output file validation

See README.md for detailed documentation.
"""

__version__ = '1.0.0'
__author__ = 'Longevity Neuroimaging Project'

# Fixtures and utilities are defined in conftest.py
# They are automatically available to pytest when running tests
# No need to import them here
