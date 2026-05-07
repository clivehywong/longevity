#!/usr/bin/env python3
"""
Comprehensive validation script for neuroimaging connectivity pipeline.

Validates:
1. All required script files exist and are executable
2. Test suite completeness and pass status
3. Output directory structure consistency
4. Configuration and documentation completeness
5. Implementation checklist verification
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Any


class PipelineValidator:
    """Validates the connectivity pipeline implementation."""

    def __init__(self, repo_root: str = None):
        """Initialize validator with repository root."""
        self.repo_root = Path(repo_root or os.getcwd())
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "repo_root": str(self.repo_root),
            "checks": {},
            "summary": {},
        }

    def run_all_validations(self) -> Dict[str, Any]:
        """Run all validation checks."""
        print("🔍 Starting connectivity pipeline validation...\n")

        # Core validations
        self.check_script_files()
        self.check_test_suite()
        self.check_output_structure()
        self.check_documentation()
        self.check_configuration()
        self.check_implementation_status()

        # Generate summary
        self._generate_summary()

        return self.results

    def check_script_files(self) -> None:
        """Validate all required script files exist and are executable."""
        print("1️⃣ Checking script files...")

        required_scripts = {
            "Core Connectivity": [
                "compute_local_measures.py",
                "seed_based_connectivity.py",
                "compute_network_connectivity.py",
                "functional_connectivity_analysis.py",
                "group_analysis_statistics.py",
            ],
            "Utilities": [
                "config_loader.py",
                "prepare_metadata.py",
                "extract_timeseries.py",
            ],
            "Workflows": [
                "master_full_connectivity_workflow.sh",
                "test_local_measures.sh",
            ],
            "Data Management": [
                "validate_bids_names.py",
                "qa_check_images.py",
            ],
        }

        results = {}
        for category, scripts in required_scripts.items():
            category_results = []
            for script in scripts:
                script_path = self.repo_root / "script" / script
                exists = script_path.exists()
                is_executable = os.access(script_path, os.X_OK) if exists else False
                size = script_path.stat().st_size if exists else 0

                category_results.append({
                    "name": script,
                    "exists": exists,
                    "executable": is_executable,
                    "size_bytes": size,
                })

            results[category] = {
                "total": len(scripts),
                "found": sum(1 for s in category_results if s["exists"]),
                "scripts": category_results,
            }

        self.results["checks"]["scripts"] = results
        self._print_check_result("Scripts", results)

    def check_test_suite(self) -> None:
        """Validate test suite completeness and run tests."""
        print("\n2️⃣ Checking test suite...")

        test_dir = self.repo_root / "tests"
        test_files = list(test_dir.glob("test_*.py"))
        total_tests = 0

        # Count tests by parsing pytest
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_dir), "--collect-only", "-q"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=30,
            )
            # Parse output to extract test count
            output = result.stdout + result.stderr
            for line in output.split("\n"):
                if "collected" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == "collected" and i + 1 < len(parts):
                            try:
                                total_tests = int(parts[i + 1])
                            except (ValueError, IndexError):
                                pass
        except Exception as e:
            print(f"⚠️ Could not collect tests: {e}")

        # Try to run a quick subset of tests
        test_status = "unknown"
        test_output = ""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_dir), "-x", "-q", "--tb=no"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=300,
            )
            test_output = result.stdout + result.stderr
            test_status = "passed" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            test_status = "timeout"
            test_output = "Tests timed out after 5 minutes"
        except Exception as e:
            test_status = "error"
            test_output = str(e)

        results = {
            "test_files": len(test_files),
            "test_files_list": [f.name for f in test_files],
            "total_tests": total_tests,
            "status": test_status,
            "output_sample": test_output[:500] if test_output else "No output",
        }

        self.results["checks"]["tests"] = results
        self._print_check_result("Tests", results)

    def check_output_structure(self) -> None:
        """Validate output directory structure."""
        print("\n3️⃣ Checking output structure...")

        expected_dirs = [
            ("results/local_measures", "Local measures outputs"),
            ("results/connectivity", "Connectivity matrices"),
            ("results/connectivity/subject_fc_matrices", "Subject FC matrices"),
            ("results/connectivity/visualizations", "Visualizations"),
            ("results/group_analysis", "Group-level statistics"),
        ]

        results = {}
        for dir_path, description in expected_dirs:
            full_path = self.repo_root / dir_path
            exists = full_path.exists()
            is_dir = full_path.is_dir() if exists else False
            contents = []

            if exists and is_dir:
                try:
                    contents = [f.name for f in full_path.iterdir()][:10]
                except Exception:
                    contents = ["error reading contents"]

            results[dir_path] = {
                "description": description,
                "exists": exists,
                "is_directory": is_dir,
                "sample_contents": contents,
            }

        self.results["checks"]["output_structure"] = results
        self._print_check_result("Output Structure", results)

    def check_documentation(self) -> None:
        """Validate documentation files."""
        print("\n4️⃣ Checking documentation...")

        doc_files = [
            ("README.md", "Project README"),
            ("QUICK_START.md", "Quick start guide"),
            ("IMPLEMENTATION_CHECKLIST.md", "Implementation checklist"),
            ("TESTS_VERIFICATION.md", "Test verification report"),
            ("TEST_SUITE_SUMMARY.md", "Test suite summary"),
            ("docs/NETWORK_CONNECTIVITY_ANALYSIS.md", "Network connectivity guide"),
        ]

        results = {}
        for doc_path, description in doc_files:
            full_path = self.repo_root / doc_path
            exists = full_path.exists()
            size = full_path.stat().st_size if exists else 0
            has_content = size > 100 if exists else False

            results[doc_path] = {
                "description": description,
                "exists": exists,
                "size_bytes": size,
                "has_content": has_content,
            }

        self.results["checks"]["documentation"] = results
        self._print_check_result("Documentation", results)

    def check_configuration(self) -> None:
        """Validate configuration files."""
        print("\n5️⃣ Checking configuration...")

        config_files = [
            ("pytest.ini", "Pytest configuration"),
            (".github/workflows/", "GitHub Actions workflows"),
        ]

        results = {}
        for config_path, description in config_files:
            full_path = self.repo_root / config_path
            exists = full_path.exists()

            if exists:
                if full_path.is_file():
                    size = full_path.stat().st_size
                    results[config_path] = {
                        "description": description,
                        "exists": True,
                        "is_directory": False,
                        "size_bytes": size,
                    }
                elif full_path.is_dir():
                    contents = list(full_path.glob("*"))
                    results[config_path] = {
                        "description": description,
                        "exists": True,
                        "is_directory": True,
                        "file_count": len(contents),
                        "sample_files": [c.name for c in contents[:5]],
                    }
            else:
                results[config_path] = {
                    "description": description,
                    "exists": False,
                }

        self.results["checks"]["configuration"] = results
        self._print_check_result("Configuration", results)

    def check_implementation_status(self) -> None:
        """Check implementation status from checklist."""
        print("\n6️⃣ Checking implementation status...")

        checklist_path = self.repo_root / "IMPLEMENTATION_CHECKLIST.md"
        results = {
            "checklist_exists": checklist_path.exists(),
            "items_verified": [],
        }

        if checklist_path.exists():
            try:
                with open(checklist_path, "r") as f:
                    content = f.read()

                # Count checkmarks
                checked = content.count("[x]")
                unchecked = content.count("[ ]")

                results["items_verified"] = {
                    "completed": checked,
                    "pending": unchecked,
                    "total": checked + unchecked,
                }

                # Extract key sections
                sections = {}
                for line in content.split("\n"):
                    if line.startswith("## "):
                        section_name = line.replace("## ", "").strip()
                        sections[section_name] = section_name in content

                results["sections"] = sections
            except Exception as e:
                results["error"] = str(e)

        self.results["checks"]["implementation_status"] = results
        self._print_check_result("Implementation Status", results)

    def _generate_summary(self) -> None:
        """Generate validation summary."""
        checks = self.results["checks"]
        summary = {
            "total_checks": len(checks),
            "passed": 0,
            "warnings": 0,
            "issues": [],
            "timestamp": datetime.now().isoformat(),
        }

        # Analyze scripts
        script_check = checks.get("scripts", {})
        for category, data in script_check.items():
            if isinstance(data, dict) and "scripts" in data:
                found = data.get("found", 0)
                total = data.get("total", 0)
                if found == total:
                    summary["passed"] += 1
                else:
                    summary["warnings"] += 1
                    summary["issues"].append(
                        f"{category}: {found}/{total} scripts found"
                    )

        # Analyze tests
        test_check = checks.get("tests", {})
        if test_check.get("status") == "passed":
            summary["passed"] += 1
        else:
            summary["warnings"] += 1
            status = test_check.get("status", "unknown")
            summary["issues"].append(f"Test suite status: {status}")

        # Analyze output structure
        output_check = checks.get("output_structure", {})
        found_dirs = sum(1 for d in output_check.values() if d.get("exists"))
        if found_dirs == len(output_check):
            summary["passed"] += 1
        else:
            summary["warnings"] += 1
            summary["issues"].append(
                f"Output structure: {found_dirs}/{len(output_check)} directories found"
            )

        # Analyze documentation
        doc_check = checks.get("documentation", {})
        found_docs = sum(1 for d in doc_check.values() if d.get("exists"))
        if found_docs == len(doc_check):
            summary["passed"] += 1
        else:
            summary["warnings"] += 1
            summary["issues"].append(
                f"Documentation: {found_docs}/{len(doc_check)} files found"
            )

        self.results["summary"] = summary

    def _print_check_result(self, check_name: str, results: Dict) -> None:
        """Print formatted check result."""
        if isinstance(results, dict):
            if "exists" in results:
                status = "✅" if results["exists"] else "❌"
                print(f"  {status} {check_name}")
            elif "status" in results:
                status = "✅" if results["status"] == "passed" else "⚠️"
                print(f"  {status} {check_name}: {results['status']}")
            elif "total" in results or "found" in results:
                total = results.get("total", 0)
                found = results.get("found", 0)
                status = "✅" if found == total else "⚠️"
                print(f"  {status} {check_name}: {found}/{total}")

    def save_report(self, output_path: str) -> str:
        """Save validation results to JSON report."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            json.dump(self.results, f, indent=2, default=str)

        print(f"\n✅ Validation report saved to: {output_file}")
        return str(output_file)


def create_markdown_report(validator: PipelineValidator, output_path: str) -> str:
    """Create a markdown report from validation results."""
    results = validator.results
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Connectivity Pipeline Validation Report",
        "",
        f"**Generated**: {results['timestamp']}",
        f"**Repository**: {results['repo_root']}",
        "",
        "## Summary",
        "",
    ]

    summary = results.get("summary", {})
    if summary:
        lines.extend([
            f"- **Total Checks**: {summary.get('total_checks', 0)}",
            f"- **Passed**: {summary.get('passed', 0)}",
            f"- **Warnings**: {summary.get('warnings', 0)}",
            "",
        ])

        if summary.get("issues"):
            lines.append("### Issues Found")
            for issue in summary["issues"]:
                lines.append(f"- {issue}")
            lines.append("")

    # Detailed checks
    checks = results.get("checks", {})

    if "scripts" in checks:
        lines.append("## Script Files")
        for category, data in checks["scripts"].items():
            if isinstance(data, dict):
                lines.append(f"\n### {category}")
                found = data.get("found", 0)
                total = data.get("total", 0)
                status = "✅" if found == total else "⚠️"
                lines.append(f"{status} {found}/{total} found")

    if "tests" in checks:
        lines.append("\n## Test Suite")
        test_check = checks["tests"]
        lines.extend([
            f"- Test Files: {test_check.get('test_files', 0)}",
            f"- Total Tests: {test_check.get('total_tests', 0)}",
            f"- Status: **{test_check.get('status', 'unknown').upper()}**",
            "",
        ])

    if "output_structure" in checks:
        lines.append("## Output Directory Structure")
        output_check = checks["output_structure"]
        for dir_path, data in output_check.items():
            status = "✅" if data.get("exists") else "❌"
            lines.append(f"{status} `{dir_path}` - {data.get('description', '')}")

    if "documentation" in checks:
        lines.append("\n## Documentation")
        doc_check = checks["documentation"]
        for doc_path, data in doc_check.items():
            status = "✅" if data.get("exists") else "❌"
            size = data.get("size_bytes", 0)
            size_str = f" ({size:,} bytes)" if size > 0 else ""
            lines.append(f"{status} `{doc_path}`{size_str}")

    if "implementation_status" in checks:
        lines.append("\n## Implementation Status")
        impl_check = checks["implementation_status"]
        if "items_verified" in impl_check:
            items = impl_check["items_verified"]
            lines.extend([
                f"- Completed: {items.get('completed', 0)}",
                f"- Pending: {items.get('pending', 0)}",
                f"- Total: {items.get('total', 0)}",
            ])

    lines.extend([
        "",
        "---",
        "**Validation Script**: `script/validate_connectivity_pipeline.py`",
    ])

    with open(output_file, "w") as f:
        f.write("\n".join(lines))

    print(f"✅ Markdown report saved to: {output_file}")
    return str(output_file)


def main():
    """Main entry point."""
    repo_root = os.getcwd()
    if len(sys.argv) > 1:
        repo_root = sys.argv[1]

    validator = PipelineValidator(repo_root)

    # Run validations
    results = validator.run_all_validations()

    # Save reports
    json_report = validator.save_report("validation_reports/pipeline_validation.json")
    md_report = create_markdown_report(
        validator, "validation_reports/pipeline_validation.md"
    )

    # Print summary
    print("\n" + "=" * 60)
    print("VALIDATION COMPLETE")
    print("=" * 60)
    summary = results.get("summary", {})
    print(f"\nTotal Checks: {summary.get('total_checks', 0)}")
    print(f"Passed: {summary.get('passed', 0)}")
    print(f"Warnings: {summary.get('warnings', 0)}")

    if summary.get("issues"):
        print("\nIssues:")
        for issue in summary["issues"]:
            print(f"  ⚠️ {issue}")

    print(f"\nReports saved:")
    print(f"  - JSON: {json_report}")
    print(f"  - Markdown: {md_report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
