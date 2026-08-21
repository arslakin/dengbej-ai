#!/usr/bin/env python3
"""
Run all Dengbej AI backend test suites.

Each Lambda's tests/ directory uses sys.path manipulation to import from its
parent. This script runs pytest per-directory to avoid cross-Lambda module
collisions (all Lambdas share the filename `lambda_function.py`).

Usage:
    python run_tests.py           # Run all suites
    python run_tests.py -v        # Verbose
    python run_tests.py --quick   # Stop on first failure
"""

import subprocess
import sys
from pathlib import Path

TEST_SUITES = [
    "backend/daily_audio/tests",
    "backend/news_api/tests",
    "backend/news_ingester/tests",
    "backend/program_classifier/tests",
    "backend/program_generator/tests",
    "backend/todays_five_curator/tests",
    "backend/todays_five_processor/tests",
]

ROOT = Path(__file__).parent


def main():
    extra_args = sys.argv[1:]
    quick = "--quick" in extra_args
    if quick:
        extra_args.remove("--quick")

    total_passed = 0
    total_failed = 0
    results = []

    for suite in TEST_SUITES:
        suite_path = ROOT / suite
        if not suite_path.exists():
            results.append((suite, "SKIP", "directory not found"))
            continue

        cmd = [sys.executable, "-m", "pytest", str(suite_path), "--tb=short"] + extra_args
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))

        # Parse pass/fail count from output
        last_line = result.stdout.strip().split("\n")[-1] if result.stdout else ""

        if result.returncode == 0:
            results.append((suite, "PASS", last_line))
            # Extract count
            import re
            match = re.search(r"(\d+) passed", last_line)
            if match:
                total_passed += int(match.group(1))
        else:
            results.append((suite, "FAIL", last_line))
            total_failed += 1
            if quick:
                print(f"\n  FAIL: {suite}")
                print(result.stdout[-500:] if result.stdout else "")
                print(result.stderr[-300:] if result.stderr else "")
                break

    # Summary
    print("\n" + "=" * 60)
    print("DENGBEJ AI — Test Results")
    print("=" * 60)
    for suite, status, detail in results:
        icon = "✓" if status == "PASS" else ("⊘" if status == "SKIP" else "✗")
        print(f"  {icon} {suite.split('/')[-2]:<25} {detail}")
    print("-" * 60)
    print(f"  Total passed: {total_passed}")
    if total_failed:
        print(f"  Suites with failures: {total_failed}")
    print("=" * 60)

    return 1 if total_failed else 0


if __name__ == "__main__":
    sys.exit(main())
