#!/bin/bash
# Quick Start Guide for Test Suite

# Installation
echo "Installing pytest and dependencies..."
pip install pytest pytest-cov

# Run all tests with verbose output
echo "Running full test suite (143 tests)..."
cd /home/clivewong/proj/longevity
pytest tests/ -v

# Run specific test modules
echo "Running unit tests only (faster)..."
pytest tests/test_local_measures.py tests/test_lme_model.py tests/test_permutation_correction.py -v

# Run with coverage report
echo "Running with coverage..."
pytest tests/ --cov=script --cov-report=html --cov-report=term-missing

# Run critical tests for silent bug detection
echo "Running critical tests (silent bug detection)..."
pytest \
  tests/test_lme_model.py::TestLMESingularityHandling \
  tests/test_permutation_correction.py::TestPValueDistribution \
  tests/test_validation.py::TestNIfTIValidity \
  -v

# Show test statistics
echo "Collecting test statistics..."
pytest tests/ --co -q | tail -5
