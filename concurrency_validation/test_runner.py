#!/usr/bin/env python3
"""
Concurrency Validation Test Runner

Discovers test cases, compiles Alecci source files, executes them,
parses ThreadSanitizer output, and generates CSV reports.
"""

import argparse
import csv
import os
import subprocess
import sys
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Import the TSan parser from the same directory
from tsan_parser import parse_tsan_output, get_detected_issue_list, format_issues_for_csv


class TestCase:
    """Represents a single concurrency test case"""
    
    def __init__(self, yaml_path: Path):
        self.yaml_path = yaml_path
        self.name = yaml_path.stem
        
        # Load YAML configuration
        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f)
        
        self.source = config.get('source', '')
        self.expected_issues = config.get('expected_issues', ['none'])
        self.args = config.get('args', [])
        self.stdin_file = config.get('stdin_file', None)
        self.timeout = config.get('timeout', 10)
        self.max_runs = config.get('max_runs', 1)  # For non-deterministic tests
        
        # Resolve paths relative to YAML file location
        test_dir = yaml_path.parent
        self.source_path = test_dir / self.source
        if self.stdin_file:
            self.stdin_path = test_dir / self.stdin_file
        else:
            self.stdin_path = None
    
    def __repr__(self):
        return f"TestCase({self.name}, source={self.source})"


class TestResult:
    """Stores the result of running a test case"""
    
    def __init__(self, test_case: TestCase):
        self.test_name = test_case.name
        self.source_file = str(test_case.source_path)
        self.expected_issues = test_case.expected_issues
        self.detected_issues = []
        self.status = "UNKNOWN"
        self.timeout_occurred = False
        self.execution_time_ms = 0
        self.tsan_details = ""
        self.notes = ""
        self.compile_success = False
    
    def to_csv_row(self) -> Dict[str, str]:
        """Convert result to CSV row dictionary"""
        return {
            'test_name': self.test_name,
            'source_file': self.source_file,
            'expected_issues': '|'.join(self.expected_issues),
            'detected_issues': '|'.join(self.detected_issues),
            'status': self.status,
            'timeout_occurred': 'yes' if self.timeout_occurred else 'no',
            'execution_time_ms': str(self.execution_time_ms),
            'tsan_details': self.tsan_details.replace('\n', ' ').replace(',', ';'),
            'notes': self.notes.replace('\n', ' ').replace(',', ';')
        }


def discover_test_cases(test_dir: Path) -> List[TestCase]:
    """
    Discover all test cases in the given directory (recursively).
    
    Args:
        test_dir: Directory containing .yaml test configurations
        
    Returns:
        List of TestCase objects
    """
    test_cases = []
    
    # Recursively search for .yaml files in all subdirectories
    for yaml_file in sorted(test_dir.rglob("*.yaml")):
        try:
            test_case = TestCase(yaml_file)
            test_cases.append(test_case)
        except Exception as e:
            print(f"Warning: Failed to load test case {yaml_file}: {e}", file=sys.stderr)
    
    return test_cases


def compile_test(test_case: TestCase, bin_dir: Path, verbose: bool = False) -> Tuple[bool, str]:
    """
    Compile an Alecci source file.
    
    Args:
        test_case: TestCase to compile
        bin_dir: Directory for output executable
        verbose: Print compilation output
        
    Returns:
        Tuple of (success: bool, output: str)
    """
    exe_path = bin_dir / test_case.name
    
    # Build compilation command
    # Use python3 -m alecci to compile with TSan enabled by default
    cmd = [
        sys.executable,
        '-m',
        'alecci',
        str(test_case.source_path),
        '-o',
        str(exe_path)
    ]
    
    if verbose:
        print(f"  Compiling: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30  # Compilation timeout
        )
        
        output = result.stdout + result.stderr
        
        if verbose and output:
            print(f"  Compilation output: {output}")
        
        # Check if executable was created
        if exe_path.exists():
            return True, output
        else:
            return False, output + "\nExecutable not created"
            
    except subprocess.TimeoutExpired:
        return False, "Compilation timeout"
    except Exception as e:
        return False, f"Compilation error: {str(e)}"


def run_test(test_case: TestCase, exe_path: Path, verbose: bool = False) -> Tuple[int, str, float, bool]:
    """
    Run a compiled test executable.
    
    Args:
        test_case: TestCase to run
        exe_path: Path to compiled executable
        verbose: Print execution details
        
    Returns:
        Tuple of (returncode: int, output: str, time_ms: float, timeout_occurred: bool)
    """
    cmd = [str(exe_path)] + test_case.args
    
    if verbose:
        print(f"  Running: {' '.join(cmd)}")
    
    # Read stdin if specified
    stdin_data = None
    if test_case.stdin_path and test_case.stdin_path.exists():
        with open(test_case.stdin_path, 'r') as f:
            stdin_data = f.read()
    
    # Note: TSan options are now embedded in the compiled binary via tsan_options.c
    # No need to set TSAN_OPTIONS environment variable
    
    start_time = time.time()
    timeout_occurred = False
    
    try:
        result = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=test_case.timeout
        )
        
        execution_time = (time.time() - start_time) * 1000  # Convert to ms
        output = result.stdout + result.stderr
        
        return result.returncode, output, execution_time, False
        
    except subprocess.TimeoutExpired as e:
        execution_time = (time.time() - start_time) * 1000
        output = ""
        if e.stdout:
            output += e.stdout.decode('utf-8') if isinstance(e.stdout, bytes) else e.stdout
        if e.stderr:
            output += e.stderr.decode('utf-8') if isinstance(e.stderr, bytes) else e.stderr
        
        return -1, output, execution_time, True
        
    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        return -1, f"Execution error: {str(e)}", execution_time, False


def validate_results(test_case: TestCase, tsan_result: Dict, timeout_occurred: bool) -> Tuple[str, str]:
    """
    Validate test results against expected issues.
    
    Args:
        test_case: TestCase being validated
        tsan_result: Parsed TSan output
        timeout_occurred: Whether execution timed out
        
    Returns:
        Tuple of (status: str, notes: str)
    """
    detected = get_detected_issue_list(tsan_result)
    expected = test_case.expected_issues
    
    # Normalize expected issues
    if not expected or expected == ['none']:
        expected_set = set(['none'])
    else:
        expected_set = set(expected)
    
    detected_set = set(detected)
    
    notes = []
    
    # Check for matches
    if expected_set == detected_set:
        status = "PASS"
    else:
        status = "FAIL"
        
        # Add details about mismatch
        missing = expected_set - detected_set
        unexpected = detected_set - expected_set
        
        if missing:
            notes.append(f"Missing expected issues: {', '.join(missing)}")
        if unexpected:
            notes.append(f"Unexpected issues detected: {', '.join(unexpected)}")
    
    # Handle timeout
    if timeout_occurred:
        notes.append(f"Execution timed out after {test_case.timeout}s")
        if 'deadlock' not in expected and 'deadlock' not in detected:
            notes.append("Timeout may indicate undetected deadlock")
    
    return status, "; ".join(notes)


def run_single_test(test_case: TestCase, bin_dir: Path, verbose: bool = False) -> TestResult:
    """
    Run a complete test: compile, execute, parse, validate.
    
    Args:
        test_case: TestCase to run
        bin_dir: Directory for compiled executables
        verbose: Print detailed progress
        
    Returns:
        TestResult object
    """
    result = TestResult(test_case)
    
    if verbose:
        print(f"\nRunning test: {test_case.name}")
        print(f"  Source: {test_case.source_path}")
        print(f"  Expected issues: {test_case.expected_issues}")
    
    # Step 1: Compile
    compile_success, compile_output = compile_test(test_case, bin_dir, verbose)
    result.compile_success = compile_success
    
    if not compile_success:
        result.status = "COMPILE_FAIL"
        result.notes = "Compilation failed"
        result.tsan_details = compile_output[:500]  # Truncate
        if verbose:
            print(f"  ❌ Compilation failed")
        return result
    
    if verbose:
        print(f"  ✓ Compilation successful")
    
    # Step 2: Execute (possibly multiple times for race detection)
    exe_path = bin_dir / test_case.name
    
    # Determine if we need multiple runs (for non-deterministic race detection)
    max_runs = test_case.max_runs
    runs_with_detection = 0
    all_outputs = []
    
    for run_number in range(max_runs):
        if verbose and max_runs > 1:
            print(f"  Run {run_number + 1}/{max_runs}...")
        
        returncode, output, exec_time, timeout_occurred = run_test(test_case, exe_path, verbose and max_runs == 1)
        all_outputs.append(output)
        
        # Check if race was detected in this run
        tsan_result = parse_tsan_output(output)
        if tsan_result['data_race'] or tsan_result['deadlock'] or \
           tsan_result['mutex_destruction'] or tsan_result['thread_leak']:
            runs_with_detection += 1
        
        # For single runs or if we already detected the issue, stop early
        if max_runs == 1 or runs_with_detection > 0:
            result.execution_time_ms = int(exec_time)
            result.timeout_occurred = timeout_occurred
            break
    
    # Use the last output (or the one with detection) for analysis
    final_output = all_outputs[-1] if runs_with_detection == 0 else \
                   next((out for out in all_outputs if 'ThreadSanitizer' in out), all_outputs[-1])
    
    if verbose:
        if max_runs > 1:
            print(f"  ✓ Completed {len(all_outputs)} run(s), detected in {runs_with_detection}")
        print(f"  ✓ Execution completed (rc={returncode}, time={exec_time:.1f}ms)")
        if len(final_output) > 0 and ("ThreadSanitizer" in final_output or "WARNING" in final_output):
            print(f"  TSan Output Preview:")
            for line in final_output.split('\n')[:30]:  # Show first 30 lines
                if line.strip():
                    print(f"    {line}")
    
    # Step 3: Parse TSan output
    tsan_result = parse_tsan_output(final_output)
    result.detected_issues = get_detected_issue_list(tsan_result)
    result.tsan_details = format_issues_for_csv(tsan_result['issues'])
    
    if verbose:
        print(f"  Detected issues: {result.detected_issues}")
    
    # Step 4: Validate
    status, notes = validate_results(test_case, tsan_result, timeout_occurred)
    result.status = status
    result.notes = notes
    
    if verbose:
        print(f"  Status: {status}")
        if notes:
            print(f"  Notes: {notes}")
    
    return result


def write_csv_report(results: List[TestResult], output_path: Path):
    """
    Write test results to CSV file.
    
    Args:
        results: List of TestResult objects
        output_path: Path for output CSV file
    """
    fieldnames = [
        'test_name',
        'source_file',
        'expected_issues',
        'detected_issues',
        'status',
        'timeout_occurred',
        'execution_time_ms',
        'tsan_details',
        'notes'
    ]
    
    with open(output_path, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for result in results:
            writer.writerow(result.to_csv_row())
    
    print(f"\nResults written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run concurrency validation tests for Alecci programs"
    )
    parser.add_argument(
        '--test-dir',
        type=Path,
        default=Path(__file__).parent / 'test_cases',
        help='Directory containing test cases (default: ./test_cases)'
    )
    parser.add_argument(
        '--output-csv',
        type=Path,
        default=None,
        help='Output CSV file path (default: results/concurrency_test_results_TIMESTAMP.csv)'
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Print detailed progress information'
    )
    
    args = parser.parse_args()
    
    # Setup paths
    test_dir = args.test_dir.resolve()
    bin_dir = Path(__file__).parent / 'bin'
    results_dir = Path(__file__).parent / 'results'
    
    # Ensure directories exist
    bin_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    
    # Discover test cases
    print(f"Discovering test cases in: {test_dir}")
    test_cases = discover_test_cases(test_dir)
    
    if not test_cases:
        print(f"No test cases found in {test_dir}")
        sys.exit(1)
    
    print(f"Found {len(test_cases)} test case(s)")
    
    # Run all tests
    results = []
    for test_case in test_cases:
        result = run_single_test(test_case, bin_dir, args.verbose)
        results.append(result)
    
    # Generate output CSV path if not specified
    if args.output_csv:
        output_csv = args.output_csv
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_csv = results_dir / f"concurrency_test_results_{timestamp}.csv"
    
    # Write CSV report
    write_csv_report(results, output_csv)
    
    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    compile_failed = sum(1 for r in results if r.status == "COMPILE_FAIL")
    
    print(f"Total:          {len(results)}")
    print(f"Passed:         {passed}")
    print(f"Failed:         {failed}")
    print(f"Compile Failed: {compile_failed}")
    print("="*60)
    
    # Exit with error code if any tests failed
    if failed > 0 or compile_failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
