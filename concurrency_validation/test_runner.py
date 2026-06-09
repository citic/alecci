#!/usr/bin/env python3
# PYTHON_ARGCOMPLETE_OK
"""
Concurrency Validation Test Runner

Discovers test cases, compiles Alecci source files, executes them,
parses ThreadSanitizer output, and generates CSV reports.
"""

import argparse
import concurrent.futures
import csv
import os
import subprocess
import sys
import threading
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Import the TSan parser from the same directory
from tsan_parser import parse_tsan_output, get_detected_issue_list, format_issues_for_csv

try:
    import argcomplete
    from argcomplete.completers import DirectoriesCompleter, FilesCompleter
    _ARGCOMPLETE = True
except ImportError:
    _ARGCOMPLETE = False


class _NullContext:
    """No-op context manager used when no semaphore is provided."""
    def __enter__(self): return self
    def __exit__(self, *_): pass


def parse_alecci_warnings(compile_output: str) -> Dict:
    """
    Parse static warnings emitted by the alecci compiler itself.

    Currently detects:
      - deadlock : "deadlock warning: semaphore '...' ... never signalled"

    Returns a dict with boolean flags mirroring the tsan_result structure
    so it can be merged with TSan output easily.
    """
    import re
    return {
        'deadlock': bool(re.search(r'deadlock warning:', compile_output)),
    }


class TestCase:
    """Represents a single concurrency test case"""

    def __init__(self, yaml_path: Path, root_dir: Optional[Path] = None):
        self.yaml_path = yaml_path
        self.name = yaml_path.stem

        # dataset: first-level folder under root_dir (e.g. "ClassExamples")
        # benchmark: immediate parent folder of the YAML (e.g. "build_h2o")
        self.benchmark = yaml_path.parent.name
        if root_dir is not None:
            try:
                self.dataset = yaml_path.relative_to(root_dir).parts[0]
            except (ValueError, IndexError):
                self.dataset = self.benchmark
        else:
            self.dataset = self.benchmark

        # Load YAML configuration
        with open(yaml_path, 'r') as f:
            config = yaml.safe_load(f)

        self.expected_issues = config.get('expected_issues', ['none'])
        self.args = config.get('args', [])
        self.stdin_file = config.get('stdin_file', None)
        self.timeout = config.get('timeout', 10)
        self.max_runs = config.get('max_runs', 1)  # For non-deterministic tests

        # Resolve paths relative to YAML file location
        yaml_dir = yaml_path.parent
        # Auto-discover source file: same stem as yaml, .ale or .pseudo extension
        source_path = None
        for ext in ('.ale', '.pseudo'):
            candidate = yaml_dir / (yaml_path.stem + ext)
            if candidate.exists():
                source_path = candidate
                break
        if source_path is None:
            raise FileNotFoundError(
                f"No .ale or .pseudo source file found for {yaml_path}"
            )
        self.source_path = source_path
        if self.stdin_file:
            self.stdin_path = yaml_dir / self.stdin_file
        else:
            self.stdin_path = None

    @property
    def exe_name(self) -> str:
        """Unique executable name based on parent folder + stem (avoids collisions)."""
        return f"{self.yaml_path.parent.name}_{self.yaml_path.stem}"

    def __repr__(self):
        return f"TestCase({self.name}, source={self.source_path.name})"


class CsvResult:
    """A minimal result loaded from an existing CSV file (no TestCase needed)."""

    def __init__(self, row: Dict[str, str]):
        self.dataset   = row.get('dataset', '')
        self.benchmark = row.get('benchmark', '')
        self.test_name = row.get('test_name', '')
        self.status    = row.get('status', 'UNKNOWN')
        raw_exp = row.get('expected_issues', 'none')
        self.expected_issues = [x for x in raw_exp.split('|') if x] or ['none']
        raw_det = row.get('detected_issues', 'none')
        self.detected_issues = [x for x in raw_det.split('|') if x] or ['none']
        raw_miss = row.get('missed_issues', 'none')
        self.missed_issues = [] if raw_miss in ('none', '') else [x for x in raw_miss.split('|') if x]
        raw_unexp = row.get('unexpected_issues', 'none')
        self.unexpected_issues = [] if raw_unexp in ('none', '') else [x for x in raw_unexp.split('|') if x]


def load_results_from_csv(csv_path: Path) -> List['CsvResult']:
    """Load test results from a previously written CSV, skipping summary rows."""
    results = []
    with open(csv_path, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            test_name = row.get('test_name', '')
            dataset   = row.get('dataset', '')
            # Skip separator / summary rows inserted by group_by_benchmark mode
            if test_name.startswith('===') or dataset.startswith('==='):
                continue
            if not test_name and not dataset:
                continue
            results.append(CsvResult(row))
    return results


class TestResult:
    """Stores the result of running a test case"""

    def __init__(self, test_case: TestCase):
        self.dataset   = test_case.dataset
        self.benchmark = test_case.benchmark
        self.test_name = test_case.name
        self.source_file = str(test_case.source_path)
        self.expected_issues = test_case.expected_issues
        self.detected_issues = []
        self.status = "UNKNOWN"
        self.timeout_occurred = False
        self.crash_occurred = False
        self.execution_time_ms = 0
        self.tsan_details = ""
        self.notes = ""
        self.compile_success = False
        self.missed_issues = []      # expected but not detected
        self.unexpected_issues = []  # detected but not expected

    def to_csv_row(self) -> Dict[str, str]:
        """Convert result to CSV row dictionary"""
        return {
            'dataset':   self.dataset,
            'benchmark': self.benchmark,
            'test_name': self.test_name,
            'source_file': self.source_file,
            'expected_issues': '|'.join(self.expected_issues),
            'detected_issues': '|'.join(self.detected_issues),
            'missed_issues': '|'.join(self.missed_issues) if self.missed_issues else 'none',
            'unexpected_issues': '|'.join(self.unexpected_issues) if self.unexpected_issues else 'none',
            'status': self.status,
            'timeout_occurred': 'yes' if self.timeout_occurred else 'no',
            'crash_occurred': 'yes' if self.crash_occurred else 'no',
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
            test_case = TestCase(yaml_file, root_dir=test_dir)
            test_cases.append(test_case)
        except Exception as e:
            print(f"Warning: Failed to load test case {yaml_file}: {e}", file=sys.stderr)
    
    return test_cases


def compile_test(
    test_case: TestCase,
    bin_dir: Path,
    verbose: bool = False,
    semaphore: Optional[threading.Semaphore] = None,
) -> Tuple[bool, str]:
    """
    Compile an Alecci source file.

    Args:
        test_case: TestCase to compile
        bin_dir: Directory for output executable
        verbose: Print compilation output
        semaphore: Optional semaphore to limit concurrent compilations

    Returns:
        Tuple of (success: bool, output: str)
    """
    exe_path = bin_dir / test_case.exe_name

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
        ctx = semaphore if semaphore is not None else _NullContext()
        with ctx:
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
        prog_stdout = result.stdout
        output = result.stdout + result.stderr
        
        return result.returncode, output, execution_time, False, prog_stdout
        
    except subprocess.TimeoutExpired as e:
        execution_time = (time.time() - start_time) * 1000
        prog_stdout = ""
        output = ""
        if e.stdout:
            decoded = e.stdout.decode('utf-8') if isinstance(e.stdout, bytes) else e.stdout
            prog_stdout += decoded
            output += decoded
        if e.stderr:
            decoded = e.stderr.decode('utf-8') if isinstance(e.stderr, bytes) else e.stderr
            output += decoded
        
        return -1, output, execution_time, True, prog_stdout
        
    except Exception as e:
        execution_time = (time.time() - start_time) * 1000
        return -1, f"Execution error: {str(e)}", execution_time, False, ""


def validate_results(
    test_case: TestCase, tsan_result: Dict, timeout_occurred: bool, crash_occurred: bool = False
) -> Tuple[str, str, List[str], List[str]]:
    """
    Validate test results against expected issues.

    Status values:
      PASS             – all expected found, nothing unexpected
      UNEXPECTED       – all expected found, but extra issues detected
      MISS             – some expected issues not found, nothing unexpected
      MISS+UNEXPECTED  – some expected not found AND extra issues detected

    Returns:
        Tuple of (status, notes, missed_issues, unexpected_issues)
    """
    detected = get_detected_issue_list(tsan_result)
    expected = test_case.expected_issues

    # SCTBench-style binary label: bug present or not
    if expected == ['bug']:
        real_detected = set(detected) - {'none'}
        # timeout = program hung = deadlock; crash = assert fired; TSan = race/deadlock
        bug_found = bool(real_detected) or crash_occurred or timeout_occurred
        notes = []
        if timeout_occurred:
            notes.append(f"Timeout after {test_case.timeout}s (likely deadlock)")
        if bug_found:
            return "PASS", "; ".join(notes), [], []
        else:
            notes.append("Bug not detected by TSan, crash, or timeout")
            return "MISS", "; ".join(notes), ['bug'], []

    # Strip the 'none' sentinel so we work with real issue types only
    real_expected = set(expected) - {'none'}
    real_detected = set(detected) - {'none'}

    missed     = sorted(real_expected - real_detected)
    unexpected = sorted(real_detected - real_expected)

    has_missing    = bool(missed)
    has_unexpected = bool(unexpected)

    if not has_missing and not has_unexpected:
        status = "PASS"
    elif not has_missing and has_unexpected:
        status = "UNEXPECTED"
    elif has_missing and not has_unexpected:
        status = "MISS"
    else:
        status = "MISS+UNEXPECTED"

    notes = []
    if missed:
        notes.append(f"Missing expected issues: {', '.join(missed)}")
    if unexpected:
        notes.append(f"Unexpected issues detected: {', '.join(unexpected)}")
    if timeout_occurred:
        notes.append(f"Execution timed out after {test_case.timeout}s")
        if 'deadlock' not in expected and 'deadlock' not in detected:
            notes.append("Timeout may indicate undetected deadlock")

    return status, "; ".join(notes), missed, unexpected


def run_single_test(
    test_case: TestCase,
    bin_dir: Path,
    verbose: bool = False,
    compile_semaphore: Optional[threading.Semaphore] = None,
    output_dir: Optional[Path] = None,
) -> TestResult:
    """
    Run a complete test: compile, execute, parse, validate.

    Args:
        test_case: TestCase to run
        bin_dir: Directory for compiled executables
        verbose: Print detailed progress
        compile_semaphore: Semaphore limiting concurrent compilations

    Returns:
        TestResult object
    """
    result = TestResult(test_case)

    if verbose:
        print(f"\nRunning test: {test_case.name}")
        print(f"  Source: {test_case.source_path}")
        print(f"  Expected issues: {test_case.expected_issues}")

    # Step 1: Compile
    compile_success, compile_output = compile_test(
        test_case, bin_dir, verbose, semaphore=compile_semaphore
    )
    result.compile_success = compile_success

    # Parse static warnings from compiler output regardless of compile success
    static_result = parse_alecci_warnings(compile_output)

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
    exe_path = bin_dir / test_case.exe_name
    
    # Determine if we need multiple runs (for non-deterministic race detection)
    max_runs = test_case.max_runs
    runs_with_detection = 0
    all_outputs = []
    last_prog_stdout = ""
    last_exec_time = 0
    last_timeout_occurred = False
    last_returncode = 0

    for run_number in range(max_runs):
        if verbose and max_runs > 1:
            print(f"  Run {run_number + 1}/{max_runs}...")
        
        returncode, output, exec_time, timeout_occurred, prog_stdout = run_test(test_case, exe_path, verbose and max_runs == 1)
        all_outputs.append(output)
        last_prog_stdout = prog_stdout
        last_exec_time = exec_time
        last_timeout_occurred = timeout_occurred
        last_returncode = returncode

        # Check if race was detected in this run
        tsan_result = parse_tsan_output(output)
        if tsan_result['data_race'] or tsan_result['deadlock'] or \
           tsan_result['mutex_destruction'] or tsan_result['thread_leak']:
            runs_with_detection += 1
        
        # For single runs or if we already detected the issue, stop early
        if max_runs == 1 or runs_with_detection > 0:
            break

    result.execution_time_ms = int(last_exec_time)
    result.timeout_occurred = last_timeout_occurred
    # TSan exits with code 66; any other non-zero exit (and no timeout) is a crash
    crash_occurred = not last_timeout_occurred and last_returncode != 0 and last_returncode != 66
    result.crash_occurred = crash_occurred

    # Save program stdout to output file if requested
    if output_dir is not None:
        out_file = output_dir / f"{test_case.exe_name}.txt"
        out_file.write_text(last_prog_stdout)
    
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
    
    # Step 3: Parse TSan output and merge with static compiler warnings
    tsan_result = parse_tsan_output(final_output)

    # Merge static detections into tsan_result
    if static_result['deadlock']:
        tsan_result['deadlock'] = True

    result.detected_issues = get_detected_issue_list(tsan_result)
    result.tsan_details = format_issues_for_csv(tsan_result['issues'])
    
    if verbose:
        print(f"  Detected issues: {result.detected_issues}")
    
    # Step 4: Validate
    status, notes, missed, unexpected = validate_results(test_case, tsan_result, last_timeout_occurred, crash_occurred)
    result.status = status
    result.notes = notes
    result.missed_issues = missed
    result.unexpected_issues = unexpected
    
    if verbose:
        print(f"  Status: {status}")
        if notes:
            print(f"  Notes: {notes}")
    
    return result


def _benchmark_status_counts(group: List[TestResult]) -> Dict[str, int]:
    return {
        'total':        len(group),
        'compile_fail': sum(1 for r in group if r.status == 'COMPILE_FAIL'),
        'pass':         sum(1 for r in group if r.status == 'PASS'),
        'unexpected':   sum(1 for r in group if r.status == 'UNEXPECTED'),
        'miss':         sum(1 for r in group if r.status == 'MISS'),
        'miss_unexp':   sum(1 for r in group if r.status == 'MISS+UNEXPECTED'),
    }


def _results_by_dataset(results: List[TestResult]) -> Dict[str, List[TestResult]]:
    groups: Dict[str, List[TestResult]] = {}
    for r in results:
        groups.setdefault(r.dataset, []).append(r)
    return dict(sorted(groups.items()))


def write_csv_report(
    results: List[TestResult],
    output_path: Path,
    group_by_benchmark: bool = False,
):
    """
    Write per-test results to CSV file.

    When *group_by_benchmark* is True the rows are sorted by benchmark,
    each benchmark section is preceded by a header row and followed by a
    per-benchmark summary row, and a final combined summary row appears at
    the end of the file.  Summary / header rows are identified by
    ``test_name`` values that start with ``===``.
    """
    fieldnames = [
        'dataset',
        'benchmark',
        'test_name',
        'source_file',
        'expected_issues',
        'detected_issues',
        'missed_issues',
        'unexpected_issues',
        'status',
        'timeout_occurred',
        'crash_occurred',
        'execution_time_ms',
        'tsan_details',
        'notes',
    ]

    def _summary_row(label: str, dname: str, counts: Dict[str, int]) -> Dict[str, str]:
        return {f: '' for f in fieldnames} | {
            'dataset':   dname,
            'test_name': label,
            'status': (
                f"PASS={counts['pass']}  MISS={counts['miss']}  "
                f"UNEXPECTED={counts['unexpected']}  "
                f"MISS+UNEXPECTED={counts['miss_unexp']}  "
                f"COMPILE_FAIL={counts['compile_fail']}  "
                f"total={counts['total']}"
            ),
        }

    with open(output_path, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        if group_by_benchmark:
            groups = _results_by_dataset(results)
            for dname, group in groups.items():
                # dataset header row
                writer.writerow(
                    {f: '' for f in fieldnames} | {'dataset': f'=== {dname} ==='}
                )
                for result in group:
                    writer.writerow(result.to_csv_row())
                writer.writerow(
                    _summary_row('=== DATASET SUMMARY ===', dname,
                                 _benchmark_status_counts(group))
                )
                writer.writerow({f: '' for f in fieldnames})  # blank separator

            # combined summary row at the end
            writer.writerow(
                _summary_row('=== COMBINED SUMMARY ===', 'ALL',
                             _benchmark_status_counts(results))
            )
        else:
            for result in results:
                writer.writerow(result.to_csv_row())

    print(f"Results written to:           {output_path}")


def write_detailed_csv_report(
    results: List[TestResult],
    output_path: Path,
    group_by_benchmark: bool = False,
):
    """
    Write a per-(test, issue_type) breakdown CSV.

    Each row represents one concurrency issue type that was either expected or
    detected in a given test.  Rows where the issue was neither expected nor
    detected are omitted.

    Outcome values:
      correct_detection  – expected and detected
      false_negative     – expected but NOT detected (tool missed it)
      unexpected         – NOT expected but detected (unlisted issue)

    When *group_by_benchmark* is True the rows are grouped by benchmark with
    separator and per-benchmark summary rows inserted between groups.
    """
    fieldnames = [
        'dataset',
        'benchmark',
        'test_name',
        'issue_type',
        'was_expected',
        'was_detected',
        'outcome',
    ]

    def _issue_rows(result: TestResult):
        if result.status == 'COMPILE_FAIL':
            return
        real_expected = set(result.expected_issues) - {'none'}
        real_detected = set(result.detected_issues) - {'none'}
        for issue_type in sorted(real_expected | real_detected):
            exp = issue_type in real_expected
            det = issue_type in real_detected
            if exp and det:
                outcome = 'correct_detection'
            elif exp:
                outcome = 'false_negative'
            else:
                outcome = 'unexpected'
            yield {
                'dataset':      result.dataset,
                'benchmark':    result.benchmark,
                'test_name':    result.test_name,
                'issue_type':   issue_type,
                'was_expected': 'yes' if exp else 'no',
                'was_detected': 'yes' if det else 'no',
                'outcome':      outcome,
            }

    def _group_issue_summary(dname: str, group: List[TestResult]) -> Dict[str, str]:
        correct = miss = unexpected = 0
        for r in group:
            for row in _issue_rows(r):
                if row['outcome'] == 'correct_detection':
                    correct += 1
                elif row['outcome'] == 'false_negative':
                    miss += 1
                else:
                    unexpected += 1
        return {f: '' for f in fieldnames} | {
            'dataset':   dname,
            'test_name': '=== DATASET SUMMARY ===',
            'outcome': (
                f"correct={correct}  false_negative={miss}  unexpected={unexpected}"
            ),
        }

    with open(output_path, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        if group_by_benchmark:
            groups = _results_by_dataset(results)
            all_correct = all_miss = all_unexpected = 0
            for dname, group in groups.items():
                writer.writerow(
                    {f: '' for f in fieldnames} | {'dataset': f'=== {dname} ==='}
                )
                for result in group:
                    for row in _issue_rows(result):
                        writer.writerow(row)
                summ = _group_issue_summary(dname, group)
                parts = dict(p.split('=') for p in summ['outcome'].split('  '))
                all_correct    += int(parts.get('correct', 0))
                all_miss       += int(parts.get('false_negative', 0))
                all_unexpected += int(parts.get('unexpected', 0))
                writer.writerow(summ)
                writer.writerow({f: '' for f in fieldnames})
            writer.writerow({f: '' for f in fieldnames} | {
                'dataset':   'ALL',
                'test_name': '=== COMBINED SUMMARY ===',
                'outcome': (
                    f"correct={all_correct}  "
                    f"false_negative={all_miss}  "
                    f"unexpected={all_unexpected}"
                ),
            })
        else:
            for result in results:
                for row in _issue_rows(result):
                    writer.writerow(row)

    print(f"Issue breakdown written to:   {output_path}")


def write_latex_table(results: List[TestResult], output_path: Path) -> None:
    """Generate a booktabs LaTeX table of TSan detection results by dataset and issue type.

    Rows are the datasets found in *results* (in discovery order).
    Columns are the five canonical issue types; a Total column group summarises each row.
    Each column group has three sub-columns: correctly identified, missed, unexpected.
    """
    ISSUE_TYPES = [
        ('data_race',          'Data Race'),
        ('deadlock',           'Deadlock'),
        ('thread_leak',        'Thread Leak'),
        ('mutex_destruction',  'Mutex Dest.'),
    ]

    # Collect per-(dataset, issue_type) counts preserving dataset order.
    from collections import defaultdict, OrderedDict
    datasets: 'OrderedDict[str, dict]' = OrderedDict()
    for r in results:
        if r.status == 'COMPILE_FAIL':
            continue
        ds = r.dataset
        if ds not in datasets:
            datasets[ds] = {it: {'correct': 0, 'missed': 0, 'unexpected': 0}
                            for it, _ in ISSUE_TYPES}
        real_expected = set(r.expected_issues) - {'none'}
        real_detected = set(r.detected_issues) - {'none'}
        for it, _ in ISSUE_TYPES:
            if it in real_expected and it in real_detected:
                datasets[ds][it]['correct'] += 1
            elif it in real_expected:
                datasets[ds][it]['missed'] += 1
            elif it in real_detected:
                datasets[ds][it]['unexpected'] += 1


    n_groups = len(ISSUE_TYPES) + 1  # +1 for Total
    n_cols   = 1 + n_groups * 3      # label col + 3 per group

    # Column spec: 'l' then groups of 'rrr' with @{\hspace{1.5em}} between them
    sep      = r'@{\hspace{1.5em}}'
    col_spec = 'l ' + f' {sep} '.join(['rrr'] * n_groups)

    # Header row 1: group labels
    header1_parts = [r'\multirow{2}{*}{\textbf{Suite}}']
    for i, (_, label) in enumerate(ISSUE_TYPES):
        fmt = r'@{\hspace{1.5em}}c' if i > 0 else 'c'
        header1_parts.append(f'\\multicolumn{{3}}{{{fmt}}}{{\\textbf{{{label}}}}}')
    header1_parts.append(r'\multicolumn{3}{@{\hspace{1.5em}}c}{\textbf{Total}}')

    # cmidrule spans: col 2-4, 5-7, 8-10, 11-13, 14-16, 17-19
    cmidrules = ''.join(
        f'\\cmidrule(lr){{{2+i*3}-{4+i*3}}}'
        for i in range(n_groups)
    )

    # Header row 2: sub-column labels
    header2_parts = ['']  # empty first cell (covered by \multirow)
    for i in range(n_groups):
        fmt = r'@{\hspace{1.5em}}r' if i > 0 else 'r'
        header2_parts.append(f'\\multicolumn{{1}}{{{fmt}}}{{Id}} & Miss. & Unexp.')

    # Data rows
    data_lines = []
    totals = {it: {'correct': 0, 'missed': 0, 'unexpected': 0} for it, _ in ISSUE_TYPES}
    for ds, issue_data in datasets.items():
        cells = []
        row_c = row_m = row_u = 0
        for it, _ in ISSUE_TYPES:
            c = issue_data[it]['correct']
            m = issue_data[it]['missed']
            u = issue_data[it]['unexpected']
            cells.append((c, m, u))
            row_c += c; row_m += m; row_u += u
            totals[it]['correct']    += c
            totals[it]['missed']     += m
            totals[it]['unexpected'] += u
        cells.append((row_c, row_m, row_u))
        cols = ' & '.join(f'{c:3} & {m:2} & {u:2}' for c, m, u in cells)
        data_lines.append(f'{ds:<14} & {cols} \\\\')

    # Total row
    total_cells = [(totals[it]['correct'], totals[it]['missed'], totals[it]['unexpected'])
                   for it, _ in ISSUE_TYPES]
    grand_c = sum(v['correct']    for v in totals.values())
    grand_m = sum(v['missed']     for v in totals.values())
    grand_u = sum(v['unexpected'] for v in totals.values())
    total_cells.append((grand_c, grand_m, grand_u))

    def _bold(n: int) -> str:
        return f'\\textbf{{{n}}}'

    total_col_lines = []
    for c, m, u in total_cells:
        total_col_lines.append(f'  & {_bold(c)} & {_bold(m)} & {_bold(u)}')

    legend = (
        r'\textit{Id}~=~correctly identified;\enspace'
        r'  \textit{Miss.}~=~missed;\enspace'
        r'  \textit{Unexp.}~=~unexpected detections (not expected but reported by TSan).'
    )

    lines = [
        f'% Auto-generated by test_runner.py -- do not edit by hand',
        r'% Requires: \usepackage{booktabs}, \usepackage{multirow}',
        r'',
        r'\begin{table*}[t]',
        r'\centering',
        r'\caption{Alecci detection results, by labeled issues.}',
        r'\label{tab:results}',
        r'\resizebox{\textwidth}{!}{%',
        f'\\begin{{tabular}}{{{col_spec}}}',
        r'\toprule',
        '  & '.join(header1_parts) + r' \\',
        cmidrules,
        '  & '.join(header2_parts) + r' \\',
        r'\midrule',
    ]
    lines += data_lines
    lines += [
        r'\midrule',
        r'\textbf{Total}',
    ]
    lines += total_col_lines
    lines += [
        r' \\',
        r'\bottomrule',
        f'\\multicolumn{{{n_cols}}}{{l}}{{\\footnotesize',
        f'  {legend}}} \\\\',
        r'\end{tabular}%',
        r'}',
        r'\end{table*}',
    ]

    output_path.write_text('\n'.join(lines) + '\n')
    print(f"LaTeX table written to:       {output_path}")


def write_latex_confusion_matrix(results: List, output_path: Path) -> None:
    """Generate a booktabs LaTeX confusion matrix.

    Each test is classified as:
      TP  – has expected issue(s) AND bug detected (TSan / crash / timeout)
      FN  – has expected issue(s) AND bug NOT detected
      FP  – no expected issues   AND bug detected
      TN  – no expected issues   AND no bug detected

    Grouping: binary-labelled rows (bug/none) are grouped by benchmark name;
    typed-labelled rows are grouped by dataset.  This handles mixed result
    lists (e.g. labeled benchmarks + SCTBench) correctly.
    """
    from collections import OrderedDict

    def _group_key(r) -> str:
        # SCTBench has a flat structure: dataset = the yaml filename (ends with .yaml)
        if r.dataset.endswith('.yaml'):
            return r.benchmark
        return r.dataset

    counts: 'OrderedDict[str, dict]' = OrderedDict()
    for r in results:
        if r.status == 'COMPILE_FAIL':
            continue
        key = _group_key(r)
        if key not in counts:
            counts[key] = {'TP': 0, 'FP': 0, 'FN': 0, 'TN': 0}
        actual_pos = bool(set(r.expected_issues) - {'none'})
        if actual_pos:
            if r.status == 'PASS':
                counts[key]['TP'] += 1
            else:
                counts[key]['FN'] += 1
        else:
            if r.status in ('UNEXPECTED', 'MISS+UNEXPECTED'):
                counts[key]['FP'] += 1
            else:
                counts[key]['TN'] += 1

    def _fmt(num: int, denom: int) -> str:
        return f'{num/denom:.2f}' if denom else '--'

    def _accuracy(c): return _fmt(c['TP'] + c['TN'], c['TP'] + c['FP'] + c['FN'] + c['TN'])
    def _recall(c):   return _fmt(c['TP'], c['TP'] + c['FN'])
    def _f1(c):       return _fmt(2*c['TP'], 2*c['TP'] + c['FP'] + c['FN'])

    # Column spec: [TP FN] sep [FP TN] sep [Total] sep [Accuracy Recall F1]
    sep      = r'@{\hspace{1.5em}}'
    col_spec = f'l rr {sep} rr {sep} r {sep} rrr'

    totals = {'TP': 0, 'FP': 0, 'FN': 0, 'TN': 0}
    data_lines = []
    for key, c in counts.items():
        for k in totals:
            totals[k] += c[k]
        n = c['TP'] + c['FP'] + c['FN'] + c['TN']
        data_lines.append(
            f'{key:<14} & {c["TP"]:3} & {c["FN"]:3} & {c["FP"]:3} & {c["TN"]:3}'
            f' & {n:3} & {_accuracy(c)} & {_recall(c)} & {_f1(c)} \\\\'
        )

    nt = sum(totals.values())
    def _b(v): return f'\\textbf{{{v}}}'
    total_line = (
        f'\\textbf{{Total}}'
        f' & {_b(totals["TP"])} & {_b(totals["FN"])}'
        f' & {_b(totals["FP"])} & {_b(totals["TN"])}'
        f' & {_b(nt)}'
        f' & {_b(_accuracy(totals))} & {_b(_recall(totals))} & {_b(_f1(totals))} \\\\'
    )

    lines = [
        '% Auto-generated by test_runner.py -- do not edit by hand',
        r'\begin{table}[t]',
        r'\centering',
        r'\caption{Confusion matrix for TSan detection by test suite.}',
        r'\label{tab:confusion}',
        f'\\begin{{tabular}}{{{col_spec}}}',
        r'\toprule',
        r'\textbf{Suite} & \textbf{TP} & \textbf{FN} & \textbf{FP} & \textbf{TN}'
        r' & \textbf{Total} & \textbf{Accuracy} & \textbf{Recall} & \textbf{F1} \\',
        r'\midrule',
    ]
    lines += data_lines
    lines += [r'\midrule']
    if len(counts) > 1:
        lines += [total_line]
    lines += [
        r'\bottomrule',
        r'\end{tabular}',
        r'\end{table}',
    ]

    output_path.write_text('\n'.join(lines) + '\n')
    print(f"Confusion matrix written to:   {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run concurrency validation tests for Alecci programs"
    )
    parser.add_argument(
        '--from-csv',
        type=Path,
        nargs='+',
        metavar='CSV',
        default=None,
        help=(
            'Skip running tests; load results from one or more existing CSV files '
            'and regenerate LaTeX outputs.  Multiple files are merged (useful for '
            'combining labeled and SCTBench results into a single confusion matrix).'
        ),
    )
    test_dir_arg = parser.add_argument(
        '--test-dir',
        type=Path,
        default=Path(__file__).parent / 'test_cases',
        help='Directory containing test cases (default: ./test_cases)'
    )
    output_csv_arg = parser.add_argument(
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
    parser.add_argument(
        '--jobs',
        '-j',
        type=int,
        default=os.cpu_count()//2 or 1,
        metavar='N',
        help='Number of tests to run in parallel (default: number of CPU cores / 2)'
    )
    save_output_arg = parser.add_argument(
        '--save-output',
        type=Path,
        nargs='?',
        const=Path(''),  # sentinel: use default path
        default=None,
        metavar='DIR',
        help='Save each program\'s stdout to DIR/<test>.txt (default dir: results/outputs/<timestamp>/)'
    )
    parser.add_argument(
        '--output-latex',
        type=Path,
        default=None,
        metavar='FILE',
        help='Write a booktabs LaTeX results table to FILE (default: results/tsan_results_table.tex)',
    )
    parser.add_argument(
        '--output-latex-cm',
        type=Path,
        default=None,
        metavar='FILE',
        help='Write a booktabs LaTeX confusion matrix to FILE (default: results/tsan_confusion_matrix.tex)',
    )
    parser.add_argument(
        '--group-by-benchmark',
        action='store_true',
        help=(
            'Treat each first-level sub-folder of --test-dir as a named benchmark. '
            'CSV output will include separator rows, per-benchmark summary rows, '
            'and a final combined summary row. '
            'The console summary will also show per-benchmark breakdowns.'
        )
    )

    if _ARGCOMPLETE:
        test_dir_arg.completer = DirectoriesCompleter()
        output_csv_arg.completer = FilesCompleter(['csv'])
        save_output_arg.completer = DirectoriesCompleter()
        argcomplete.autocomplete(parser)

    args = parser.parse_args()

    results_dir = Path(__file__).parent / 'results'
    results_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # --from-csv mode: load existing CSVs, regenerate LaTeX, then exit.
    # ------------------------------------------------------------------
    if args.from_csv:
        all_results: List[CsvResult] = []
        for csv_path in args.from_csv:
            csv_path = csv_path.resolve()
            print(f"Loading results from: {csv_path}")
            all_results.extend(load_results_from_csv(csv_path))
        print(f"Loaded {len(all_results)} result(s) total")

        has_typed_labels = any(
            set(r.expected_issues) - {'none', 'bug'}
            for r in all_results
            if r.status != 'COMPILE_FAIL'
        )
        if has_typed_labels:
            latex_path = args.output_latex or results_dir / 'tsan_results_table.tex'
            write_latex_table(all_results, latex_path)

        latex_cm_path = args.output_latex_cm or results_dir / 'confusion_matrix.tex'
        write_latex_confusion_matrix(all_results, latex_cm_path)
        return

    # ------------------------------------------------------------------
    # Normal mode: discover, compile, run tests, then write CSV + LaTeX.
    # ------------------------------------------------------------------

    # Setup paths
    test_dir = args.test_dir.resolve()
    bin_dir = Path(__file__).parent / 'bin'

    # Ensure directories exist
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Resolve output directory for program stdout
    output_dir: Optional[Path] = None
    if args.save_output is not None:
        if args.save_output == Path(''):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = results_dir / f"outputs_{timestamp}"
        else:
            output_dir = args.save_output.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Program outputs will be saved to: {output_dir}")

    # Discover test cases
    print(f"Discovering test cases in: {test_dir}")
    test_cases = discover_test_cases(test_dir)

    if not test_cases:
        print(f"No test cases found in {test_dir}")
        sys.exit(1)

    print(f"Found {len(test_cases)} test case(s)")
    print(f"Running with {args.jobs} parallel job(s)")
    if args.verbose and args.jobs > 1:
        print("Note: verbose output may be interleaved when running in parallel")

    # Limit concurrent compilations to avoid resource contention
    # (PLY + llvmlite + clang are memory-heavy; running too many in parallel
    # causes failures even though each is an isolated subprocess)
    _compile_sem = threading.Semaphore(max(1, args.jobs // 2))

    # Run all tests in parallel, but print results in discovery order.
    # _next_to_print tracks whose turn it is; each thread waits on _print_cv
    # until all lower-indexed tests have printed, then prints and notifies.
    _print_cv = threading.Condition()
    _next_to_print = [0]  # mutable int via list so the closure can update it
    ordered_results: List[Optional[TestResult]] = [None] * len(test_cases)
    total = len(test_cases)

    def _run(idx: int, test_case: TestCase) -> None:
        result = run_single_test(
            test_case, bin_dir, args.verbose, compile_semaphore=_compile_sem,
            output_dir=output_dir,
        )
        ordered_results[idx] = result
        if not args.verbose:
            if test_case.dataset != test_case.benchmark:
                label = f"{test_case.dataset}/{test_case.benchmark}/{test_case.name}"
            else:
                label = f"{test_case.dataset}/{test_case.name}"
            with _print_cv:
                # Wait until all earlier tests have printed
                _print_cv.wait_for(lambda: _next_to_print[0] == idx)
                print(f"  [{idx + 1}/{total}] {label}... {result.status}")
                _next_to_print[0] += 1
                _print_cv.notify_all()

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [
            executor.submit(_run, i, tc)
            for i, tc in enumerate(test_cases)
        ]
        for future in concurrent.futures.as_completed(futures):
            future.result()  # re-raise any exception

    results: List[TestResult] = ordered_results  # type: ignore[assignment]

    # Generate output CSV path if not specified
    if args.output_csv:
        output_csv = args.output_csv
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_csv = results_dir / f"concurrency_test_results_{timestamp}.csv"

    # Write main CSV report
    write_csv_report(results, output_csv, group_by_benchmark=args.group_by_benchmark)

    # Write detailed issue-breakdown CSV alongside the main report (separate path)
    stem = output_csv.stem
    breakdown_stem = stem.replace('concurrency_test_results', 'issue_breakdown')
    if breakdown_stem == stem:
        breakdown_stem = f"issue_breakdown_{stem}"
    breakdown_csv = output_csv.parent / f"{breakdown_stem}.csv"
    write_detailed_csv_report(results, breakdown_csv, group_by_benchmark=args.group_by_benchmark)

    # Determine whether any results use specific issue-type labels (not bug/none)
    has_typed_labels = any(
        set(r.expected_issues) - {'none', 'bug'}
        for r in results
        if r.status != 'COMPILE_FAIL'
    )

    # Write LaTeX results table only when issue-type labels are present
    if has_typed_labels:
        latex_path = args.output_latex or results_dir / 'tsan_results_table.tex'
        write_latex_table(results, latex_path)

    # Write LaTeX confusion matrix (single-run mode; combined via --from-csv)
    if args.output_latex_cm:
        write_latex_confusion_matrix(results, args.output_latex_cm)

    # ------------------------------------------------------------------ summary
    from collections import defaultdict

    def _is_binary_mode(group: List[TestResult]) -> bool:
        """True when all expected labels are 'bug' or 'none' (SCTBench-style)."""
        return all(
            set(r.expected_issues) <= {'bug', 'none'}
            for r in group
            if r.status != 'COMPILE_FAIL'
        )

    def _print_status_block(group: List[TestResult], indent: str = ""):
        n_total       = len(group)
        n_compile     = sum(1 for r in group if r.status == "COMPILE_FAIL")
        n_pass        = sum(1 for r in group if r.status == "PASS")
        n_unexpected  = sum(1 for r in group if r.status == "UNEXPECTED")
        n_miss        = sum(1 for r in group if r.status == "MISS")
        n_miss_unexp  = sum(1 for r in group if r.status == "MISS+UNEXPECTED")
        print(f"{indent}Total:          {n_total}")
        print(f"{indent}Compile failed: {n_compile}")
        print()

        if _is_binary_mode(group):
            # SCTBench-style: show a binary bug/none breakdown
            buggy   = [r for r in group if r.status != 'COMPILE_FAIL' and 'bug'  in r.expected_issues]
            correct = [r for r in group if r.status != 'COMPILE_FAIL' and 'none' in r.expected_issues]
            n_bug_detected  = sum(1 for r in buggy   if r.status == 'PASS')
            n_bug_missed    = sum(1 for r in buggy   if r.status in ('MISS', 'MISS+UNEXPECTED'))
            n_true_neg      = sum(1 for r in correct if r.status == 'PASS')
            n_false_pos     = sum(1 for r in correct if r.status in ('UNEXPECTED', 'MISS+UNEXPECTED'))
            w = 40
            print(f"{indent}Buggy programs   (expected: bug):  {len(buggy):>3}")
            print(f"{indent}  {'Detected [PASS]':<{w}} {n_bug_detected:>3}")
            print(f"{indent}  {'Missed   [MISS]':<{w}} {n_bug_missed:>3}")
            print(f"{indent}Correct programs (expected: none): {len(correct):>3}")
            print(f"{indent}  {'Clean            [PASS]':<{w}} {n_true_neg:>3}")
            print(f"{indent}  {'False positives  [UNEXPECTED]':<{w}} {n_false_pos:>3}")
        else:
            w = 45
            print(f"{indent}Detection outcomes:")
            print(f"{indent}  {'All expected found, none unexpected [PASS]':<{w}} {n_pass}")
            print(f"{indent}  {'All expected found + extra detected  [UNEXPECTED]':<{w}} {n_unexpected}")
            print(f"{indent}  {'Missed expected issues               [MISS]':<{w}} {n_miss}")
            print(f"{indent}  {'Missed expected + extras detected    [MISS+UNEXPECTED]':<{w}} {n_miss_unexp}")

            issue_stats: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {'expected': 0, 'detected': 0, 'missed': 0, 'unexpected': 0}
            )
            for r in group:
                if r.status == 'COMPILE_FAIL':
                    continue
                for t in (set(r.expected_issues) - {'none'}):
                    issue_stats[t]['expected'] += 1
                for t in (set(r.detected_issues) - {'none'}):
                    issue_stats[t]['detected'] += 1
                for t in r.missed_issues:
                    issue_stats[t]['missed'] += 1
                for t in r.unexpected_issues:
                    issue_stats[t]['unexpected'] += 1

            if issue_stats:
                print()
                print(f"{indent}Breakdown by concurrency issue type:")
                col = max(len(t) for t in issue_stats) + 2
                print(f"{indent}  {'Issue type':<{col}}  {'Expected':>8}  {'Detected':>8}  {'Missed':>6}  {'Unexp.':>6}")
                print(f"{indent}  {'-'*col}  {'--------':>8}  {'--------':>8}  {'------':>6}  {'------':>6}")
                for issue_type in sorted(issue_stats):
                    s = issue_stats[issue_type]
                    print(
                        f"{indent}  {issue_type:<{col}}  {s['expected']:>8}  {s['detected']:>8}"
                        f"  {s['missed']:>6}  {s['unexpected']:>6}"
                    )

        return n_compile, n_miss, n_miss_unexp, n_unexpected

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    if args.group_by_benchmark:
        groups = _results_by_dataset(results)
        for dname, group in groups.items():
            print(f"\n--- Dataset: {dname} ---")
            _print_status_block(group, indent="  ")
        print("\n" + "=" * 60)
        print("COMBINED RESULTS")
        print("=" * 60)

    compile_fail, miss, miss_unexp, unexpected = _print_status_block(results)

    print("=" * 60)

    # Non-zero exit if any test did not fully pass
    if compile_fail > 0 or miss > 0 or miss_unexp > 0 or unexpected > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
