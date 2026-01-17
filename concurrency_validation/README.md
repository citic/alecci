# Concurrency Validation Framework

A standalone testing framework for validating Alecci's ability to detect concurrency bugs using ThreadSanitizer (TSan).

## Quick Start

```bash
cd concurrency_validation
python3 test_runner.py --verbose
```

Results are saved to `results/concurrency_test_results_TIMESTAMP.csv`.

## Overview

This framework:
1. Discovers test cases from YAML configuration files (recursively in test_cases/ subdirectories)
2. Compiles Alecci source files with ThreadSanitizer enabled
3. Executes programs with timeout protection
4. Parses TSan output to identify specific concurrency issues
5. Validates detected issues against expected results
6. Generates CSV reports with detailed test outcomes

## Directory Structure

```
concurrency_validation/
├── test_runner.py              # Main test execution script
├── tsan_parser.py              # TSan output parser
├── README.md                   # This comprehensive guide
├── .gitignore                  # Git ignore rules
│
├── test_cases/                 # Test case definitions
│   ├── aggressive_race/        # Each test in its own folder
│   │   ├── aggressive_race.ale # Alecci source code
│   │   └── aggressive_race.yaml# Test configuration
│   ├── data_race_counter/
│   │   ├── data_race_counter.ale
│   │   └── data_race_counter.yaml
│   ├── mutex_destruction/
│   │   ├── mutex_destruction.ale
│   │   └── mutex_destruction.yaml
│   └── safe_counter/
│       ├── safe_counter.ale
│       └── safe_counter.yaml
│
├── results/                    # CSV test results (auto-generated)
│   └── concurrency_test_results_TIMESTAMP.csv
│
└── bin/                        # Compiled executables (auto-generated)
```

## Detected Issue Types

The framework can detect four types of concurrency bugs via ThreadSanitizer:

1. **`data_race`** - Unsynchronized access to shared memory
2. **`deadlock`** - Lock-order-inversion (potential deadlock)
3. **`mutex_destruction`** - Destroying a locked mutex
4. **`thread_leak`** - Threads not properly joined

## Command-Line Options

```bash
python3 test_runner.py [OPTIONS]

Options:
  --test-dir PATH      Directory containing test cases (default: ./test_cases)
  --output-csv PATH    Output CSV file path (default: auto-generated in results/)
  --verbose, -v        Print detailed progress information
```

### Examples

Run all tests with verbose output:
```bash
python3 test_runner.py --verbose
```

Run tests from custom directory:
```bash
python3 test_runner.py --test-dir /path/to/tests
```

Specify output CSV location:
```bash
python3 test_runner.py --output-csv my_results.csv
```

## Test Case Format

Each test case consists of two files in its own subdirectory within `test_cases/`:

### 1. Source File (`.ale`)

Standard Alecci source code, potentially containing concurrency bugs.

Example: `test_cases/data_race_counter/data_race_counter.ale`
```alecci
shared mutable counter := 0

procedure increment(thread_number as int)
    counter := counter + 1  // Race condition!
end procedure

procedure main(argc, argv)
    mutable threads := create_threads(4, increment)
    join_threads(threads)
end procedure
```

### 2. Configuration File (`.yaml`)

YAML file specifying test parameters (must be in same directory as .ale file):

Example: `test_cases/data_race_counter/data_race_counter.yaml`
```yaml
# Test case configuration
source: data_race_counter.ale

# Expected concurrency issues (list)
# Options: data_race, deadlock, mutex_destruction, thread_leak, none
expected_issues:
  - data_race

# Optional: Command-line arguments
args:
  - "arg1"
  - "arg2"

# Optional: File to use as stdin
stdin_file: input.txt

# Timeout in seconds (default: 10)
timeout: 10
```

#### Required Fields:
- **`source`**: Path to `.ale` file (relative to YAML file location)
- **`expected_issues`**: List of expected issue types, or `["none"]` if no issues expected

#### Optional Fields:
- **`args`**: List of command-line arguments to pass to the program
- **`stdin_file`**: Path to file containing stdin data (relative to YAML file)
- **`timeout`**: Maximum execution time in seconds (default: 10)

## Usage

### Basic Usage

Run all tests in the default test_cases/ directory:

```bash
cd concurrency_validation
python3 test_runner.py
```

### Command-Line Options

```bash
python3 test_runner.py [OPTIONS]

Options:
  --test-dir PATH      Directory containing test cases (default: ./test_cases)
  --output-csv PATH    Output CSV file path (default: auto-generated in results/)
  --verbose, -v        Print detailed progress information
```

### Examples

Run with verbose output:
```bash
python3 test_runner.py --verbose
```

Run tests from custom directory:
```bash
python3 test_runner.py --test-dir /path/to/tests
```

Specify output CSV location:
```bash
python3 test_runner.py --output-csv my_results.csv
```

## CSV Output Format

The generated CSV file contains the following columns:

| Column | Description |
|--------|-------------|
| `test_name` | Name of the test (from YAML filename) |
| `source_file` | Path to Alecci source file |
| `expected_issues` | Expected issues (pipe-separated: `data_race\|thread_leak`) |
| `detected_issues` | Actually detected issues (pipe-separated) |
| `status` | Test result: `PASS`, `FAIL`, or `COMPILE_FAIL` |
| `timeout_occurred` | Whether execution timed out (`yes`/`no`) |
| `execution_time_ms` | Execution time in milliseconds |
| `tsan_details` | Brief description of detected issues |
| `notes` | Additional information (e.g., reason for failure) |

### Status Values

- **`PASS`**: Detected issues match expected issues exactly
- **`FAIL`**: Mismatch between detected and expected issues
- **`COMPILE_FAIL`**: Source file failed to compile

### Example CSV Output

```csv
test_name,source_file,expected_issues,detected_issues,status,timeout_occurred,execution_time_ms,tsan_details,notes
data_race_counter,test_cases/data_race_counter.ale,data_race,data_race,PASS,no,245,data_race,
mutex_test,test_cases/mutex_test.ale,none,none,PASS,no,103,none,
deadlock_test,test_cases/deadlock_test.ale,deadlock,none,FAIL,yes,5002,none,Timeout may indicate undetected deadlock; Missing expected issues: deadlock
```

## Creating Test Cases

### Step 1: Create Test Directory

Create a new directory in `test_cases/` for your test:

```bash
mkdir test_cases/my_new_test
```

### Step 2: Write Alecci Source

Create an `.ale` file in your test directory:

**File: `test_cases/my_new_test/my_new_test.ale`**
```alecci
shared mutable data := 0

procedure worker(id as int)
    data := data + 1  // Unprotected access
end procedure

procedure main(argc, argv)
    mutable threads := create_threads(2, worker)
    join_threads(threads)
end procedure
```

### Step 3: Create YAML Configuration

Create matching `.yaml` file in the same directory:

**File: `test_cases/my_new_test/my_new_test.yaml`**
```yaml
source: my_new_test.ale
expected_issues:
  - data_race
timeout: 5
```

### Step 4: Run Tests

```bash
python3 test_runner.py --verbose
```

## Example Test Cases

The framework includes four example test cases:

### 1. Thread Leak (`aggressive_race`)

**File: `test_cases/aggressive_race/aggressive_race.ale`**
- Creates 8 threads
- Each does 10,000 counter increments
- Threads are created but may not be properly joined
- **Expected**: TSan detects thread leak ✓

### 2. Data Race Counter (`data_race_counter`)

**File: `test_cases/data_race_counter/data_race_counter.ale`**
```alecci
shared mutable counter := 0

procedure increment(thread_number as int)
    const iterations := 1000
    mutable i := 0
    while i < iterations do
        counter := counter + 1  // RACE!
        i := i + 1
    end while
end procedure

procedure main(argc, argv)
    mutable threads := create_threads(4, increment)
    join_threads(threads)
    print `Counter: {counter}`
end procedure
```

**File: `test_cases/data_race_counter/data_race_counter.yaml`**
```yaml
source: data_race_counter.ale
expected_issues:
  - data_race
timeout: 10
max_runs: 20  # Run up to 20 times to catch the race
```

**Note**: Data races are non-deterministic. TSan may not detect every race in every execution.

### 3. Safe Counter (`safe_counter`)

**File: `test_cases/safe_counter/safe_counter.ale`**
```alecci
shared mutable counter := 0
shared mutable counter_mutex := mutex()

procedure increment(thread_number as int)
    lock(counter_mutex)
    counter := counter + 1
    unlock(counter_mutex)
end procedure

procedure main(argc, argv)
    mutable threads := create_threads(4, increment)
    join_threads(threads)
    print `Counter: {counter}`
end procedure
```

**File: `test_cases/safe_counter/safe_counter.yaml`**
```yaml
source: safe_counter.ale
expected_issues:
  - none
timeout: 10
```

**Expected**: No concurrency issues (mutex protects shared data) ✓

### 4. Mutex Destruction (`mutex_destruction`)

**File: `test_cases/mutex_destruction/mutex_destruction.ale`**
```alecci
shared mutable counter := 0
shared mutable counter_mutex := mutex()

procedure worker(thread_id as int)
    lock(counter_mutex)
    counter := counter + 1
    // Deliberately forget to unlock before thread exits
    // This will cause the mutex to be destroyed while locked
end procedure

procedure main(argc, argv)
    print "Testing mutex destruction while locked..."
    
    // Create a single thread that locks the mutex
    mutable threads := create_threads(1, worker)
    
    // Wait for thread to complete
    join_threads(threads)
    
    print `Counter value: {counter}`
    print "Test completed"
end procedure
```

**File: `test_cases/mutex_destruction/mutex_destruction.yaml`**
```yaml
source: mutex_destruction.ale
expected_issues:
  - mutex_destruction
timeout: 10
```

**Expected**: TSan detects mutex being destroyed while locked (undefined behavior) ✓

## Important Notes

### Data Race Detection
- **Non-deterministic**: Races may not occur in every execution
- Depends on actual thread interleaving
- False negatives are possible (race exists but not detected)
- For production validation, consider multiple runs or use `max_runs` parameter

### ThreadSanitizer Limitations
- Requires race to actually occur during execution
- Some benign races may be reported
- Overhead: 5-15x slowdown, 5-10x memory increase
- Best used in testing, not production

### Thread Leaks
- Occur when threads are created but not properly joined
- TSan reliably detects these issues

### Timeouts
- May indicate deadlock, but not always detected by TSan
- Could also be an infinite loop (not a concurrency bug)
- Increase timeout if program legitimately takes longer

## Dependencies

- **Python 3.7+**
- **PyYAML**: `pip install pyyaml`
- **Alecci compiler**: Must be installed and accessible via `python3 -m alecci`
- **Clang with TSan support**: ThreadSanitizer requires clang

## Troubleshooting

### "No module named 'alecci'"

Ensure the Alecci compiler is installed:
```bash
cd /path/to/alecci
pip install -e .
```

### "Compilation failed"

Check that:
1. Clang is installed: `clang --version`
2. Source file syntax is correct
3. ThreadSanitizer is supported on your platform (Linux/WSL)

### Tests timeout but no deadlock detected

This may indicate:
1. Actual deadlock that TSan didn't catch (rare)
2. Program is taking too long (increase timeout)
3. Infinite loop in code (not a concurrency bug)

### False negatives (race not detected)

ThreadSanitizer is not perfect:
- Some races may not manifest in a single run
- Race detection depends on actual thread interleaving
- Consider running programs multiple times or with stress testing
- Use `max_runs` parameter in YAML to run test multiple times



The test runner exits with:
- **Exit code 0**: All tests passed
- **Exit code 1**: One or more tests failed or didn't compile

Example GitHub Actions workflow:

```yaml
name: Concurrency Validation

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.x'
      - name: Install dependencies
        run: |
          pip install pyyaml
          pip install -e .
      - name: Run concurrency validation
        run: |
          cd concurrency_validation
          python3 test_runner.py --verbose
      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v2
        with:
          name: concurrency-test-results
          path: concurrency_validation/results/*.csv
```

## Framework Components

### TSan Parser (`tsan_parser.py`)
- Detects 4 types of concurrency bugs via regex pattern matching
- Extracts location information when available
- Returns structured results for validation

### Test Runner (`test_runner.py`)
- Recursively discovers `.yaml` test configurations in test_cases/
- Compiles Alecci sources with TSan enabled
- Executes with timeout protection
- Parses TSan output
- Validates against expected issues
- Generates CSV reports
- Exit codes: 0 (all passed) / 1 (failures)

## Dependencies

- **Python 3.7+**
- **PyYAML**: `pip install pyyaml`
- **Alecci compiler**: Must be installed and accessible via `python3 -m alecci`
- **Clang with TSan support**: ThreadSanitizer requires clang

## Troubleshooting

### "No module named 'alecci'"

Ensure the Alecci compiler is installed:
```bash
cd /path/to/alecci
pip install -e .
```

### "Compilation failed"

Check that:
1. Clang is installed: `clang --version`
2. Source file syntax is correct
3. ThreadSanitizer is supported on your platform (Linux/WSL)

### Tests timeout but no deadlock detected

This may indicate:
1. Actual deadlock that TSan didn't catch (rare)
2. Program is taking too long (increase timeout)
3. Infinite loop in code (not a concurrency bug)

### False negatives (race not detected)

ThreadSanitizer is not perfect:
- Some races may not manifest in a single run
- Race detection depends on actual thread interleaving
- Consider running programs multiple times or with stress testing
- Use `max_runs` parameter in YAML to run test multiple times

## Extending the Framework

### Adding New Issue Types

To detect additional TSan warnings:

1. Edit `tsan_parser.py`
2. Add new pattern in `parse_tsan_output()`
3. Update result dictionary
4. Add to `get_detected_issue_list()`

### Custom Test Runners

The framework can be imported as a module:

```python
from test_runner import TestCase, run_single_test
from pathlib import Path

test = TestCase(Path("my_test.yaml"))
result = run_single_test(test, Path("./bin"), verbose=True)
print(f"Status: {result.status}")
```

## License

This framework is part of the Alecci project.
