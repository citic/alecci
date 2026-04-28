from __future__ import annotations
from pathlib import Path
import pytest


EXAMPLES = {
    "hello": {
        "file": "hello.pseudo",
        "expect": ["Hello from main thread"],
    },
    "undefined_variable_scan": {
        "file": "undefined_variable_scan.ale",
        "expect": ["ERROR: Undefined variable 'a' in scan statement"],
    },
    "arrays": {
        "file": "arrays.pseudo",
        "expect": ["Reading array values:", "Array test completed successfully"],
    },
    "condition": {
        "file": "condition.pseudo",
        "expect": ["number is less than 5"],
    },
    "while": {
        "file": "while.pseudo",
        "expect": ["number is equal to 5"],
    },
    "functions": {
        "file": "functions.pseudo",
        "expect": ["Function calls test completed successfully"],
    },
    "mutex": {
        "file": "mutex.pseudo",
        "expect": ["Testing mutex operations", "Mutex test completed successfully"],
    },
    "barrier": {
        "file": "barrier.pseudo",
        "expect": [
            "Starting barrier test",
            "Barrier test completed",
            "Worker 0 before barrier",
            "Worker 1 before barrier",
            "Worker 2 before barrier",
            "Worker 0 after barrier",
            "Worker 1 after barrier",
            "Worker 2 after barrier",
        ],
    },
    "argument_parsing": {
        "file": "argument_parsing.pseudo",
        "args": ["foo", "123", "456"],
        "expect": ["Argument parsing test completed"],
    },
    "arguments": {
        "file": "arguments.pseudo",
        "args": ["21", "7"],
        "expect": ["Argument parsing test completed"],
    },
    "scan": {
        "file": "scan.ale",
        "stdin": "7 9\n3.14 2.71\nJohn Doe\n",
        "expect": [
            "Enter two integers:",
            "You entered a=7, b=9",
            "Enter two floating point numbers:",
            "You entered x=3.140000, y=2.710000",
            "Enter a first and last name:",
            "The full name would be John Doe",
        ],
    },
    "variant": {
        "file": "variant.pseudo",
        "expect": ["Test with 3: 5", "Test with 7: \"Hello\""],
    },
    "sleep": {
        "file": "sleep.pseudo",
        "expect": ["Sleep test start", "Sleep test end"],
    },
    "rand": {
        "file": "rand.pseudo",
        "expect": ["Rand test start", "Rand test end"],
    },
    "input_scan": {
        "file": "scan.ale",
        "stdin": "7 9\n3.14 2.71\nJohn Doe\n",
        "expect": [
            "Enter two integers:",
            "You entered a=7, b=9",
            "Enter two floating point numbers:",
            "You entered x=3.140000, y=2.710000",
            "Enter a first and last name:",
            "The full name would be John Doe",
        ],
    },
    "functions_return": {
        "file": "functions_return.alecci",
        "expect": [
            "Testing function returns",
            "add(5, 7) = 12",
            "factorial(5) = 120",
            "muladd(2, 3, 4) = 20",
            "Function returns test completed successfully",
        ],
    },
    "float": {
        "file": "float.pseudo",
        "expect": [
            "Float constants and variables work",
            "Addition: 10.5 + 3.2 = 13.7",
            "Multiplication with constant works",
            "Variable assignment works",
            "Mixed int/float operations work",
            "Scientific notation works",
            "Float test completed successfully",
        ],
    },
    "case": {
        "file": "case.ale",
        "stdin": "H\nO\nN\nX\n",
        "expect": [
            "Testing case statements",
            "code is two",
            "hydrogen",
            "oxygen",
            "nitrogen",
            "other",
            "Case test completed successfully",
        ],
    },
    "for_loop": {
        "file": "for_loop.ale",
        "expect": [
            "For loop test start",
            "sum 0..4 = 10",
            "count 1..10 = 10",
            "3x3 iterations = 9",
            "For loop test end",
        ],
    },
    "queue": {
        "file": "queue.ale",
        "expect": [
            "Queue test start",
            "size after 3 enqueues = 3",
            "dequeued: 10, 20, 30",
            "size after 3 dequeues = 0",
            "size after filling to capacity = 5",
            "sum of 1..5 = 15",
            "Queue test end",
        ],
    },
    "operators": {
        "file": "operators.ale",
        "expect": [
            "ARITHMETIC OPERATORS TEST",
            "10 + 5 = 15",
            "10.5 + 3.2 = 13.7",
            "20 - 8 = 12",
            "7 * 6 = 42",
            "20 / 4 = 5",
            "20 # 3 = 6",
            "17 # 5 = 3",
            "20 % 3 = 2",
            "2 ^ 3 = 8",
            "2.0 ^ 3 = 8",
            "20 mod 3 = 2",
            "17 mod 5 = 2",
            "20 mod 4 = 0",
            "COMPARISON OPERATORS TEST",
            "5 = 5 is 1",
            "5 != 6 is 1",
            "3 < 5 is 1",
            "7 > 3 is 1",
            "5 <= 5 is 1",
            "7 >= 3 is 1",
            "3.14 > 2.71 is 1",
            "LOGICAL OPERATORS TEST",
            "1 and 1 = 1",
            "1 or 0 = 1",
            "not 1 = 0",
            "BITWISE OPERATORS TEST",
            "12 & 10 = 8",
            "12 | 10 = 14",
            "12 xor 10 = 6",
            "~5 = -6",
            "5 << 2 = 20",
            "20 >> 2 = 5",
            "MIXED TYPE OPERATIONS TEST",
            "10 + 3.5 = 13.5",
            "10 * 3.5 = 35",
            "3.5 / 10 = 0.35",
            "10 > 3.5 is 1",
            "VARIANT OPERATIONS TEST",
            "variant: 10 + 5 = 15",
            "variant: 10 * 5 = 50",
            "variant: 1 and 0 = 0",
            "variant: 12 & 10 = 8",
            "All operator tests passed!",
        ],
    },
}


def _compile_and_run(name: str, example: dict, repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn) -> str:
    # Resolve example file allowing either .pseudo or .alecci
    src = repo_root / "examples" / "basic_tests" / example["file"]
    if not src.exists():
        p = Path(example["file"]) if not isinstance(example["file"], Path) else example["file"]
        base = p.with_suffix("").name
        alt_pseudo = repo_root / "examples" / "basic_tests" / f"{base}.pseudo"
        alt_alecci = repo_root / "examples" / "basic_tests" / f"{base}.alecci"
        alt_ale = repo_root / "examples" / "basic_tests" / f"{base}.ale"
        if alt_alecci.exists():
            src = alt_alecci
        elif alt_pseudo.exists():
            src = alt_pseudo
        elif alt_ale.exists():
            src = alt_ale
    out = bin_dir / Path(example["file"]).with_suffix("").name
    rc, build_out = compile_pseudo_fn(src, out, debug=True, tsan=False)
    assert rc == 0, f"[BUILD FAIL] {name}\n{build_out}"
    rc, run_out = run_exe_fn(out, args=example.get("args"), stdin=example.get("stdin"))
    assert rc == 0, f"[RUN FAIL] {name}\n{run_out}"
    for needle in example["expect"]:
        assert needle in run_out, f"[ASSERT FAIL] {name} missing: {needle}\nFull output:\n{run_out}"
    return run_out


def test_example_hello(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("hello", EXAMPLES["hello"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] hello")


def test_example_arrays(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("arrays", EXAMPLES["arrays"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] arrays")


def test_example_condition(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("condition", EXAMPLES["condition"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] condition")


def test_example_while(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("while", EXAMPLES["while"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] while")


def test_example_functions(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("functions", EXAMPLES["functions"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] functions")


def test_example_mutex(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("mutex", EXAMPLES["mutex"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] mutex")


def test_example_barrier(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("barrier", EXAMPLES["barrier"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] barrier")


def test_example_arguments(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("arguments", EXAMPLES["arguments"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] arguments")


def test_example_scan(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("scan", EXAMPLES["scan"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] scan")


def test_example_variant(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("variant", EXAMPLES["variant"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] variant")

def test_example_sleep(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("sleep", EXAMPLES["sleep"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] sleep")

def test_example_rand(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("rand", EXAMPLES["rand"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    # Ensure no errors were reported by the example
    assert "ERROR" not in out, f"[ASSERT FAIL] rand printed an error\nFull output:\n{out}"
    print("[PASS] rand")


def test_example_input_scan(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("input_scan", EXAMPLES["input_scan"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] input_scan")


def test_example_functions_return(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("functions_return", EXAMPLES["functions_return"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] functions_return")


def test_example_float(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("float", EXAMPLES["float"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] float")


def test_example_operators(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("operators", EXAMPLES["operators"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] operators")


def test_example_for_loop(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("for_loop", EXAMPLES["for_loop"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] for_loop")


def test_example_queue(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("queue", EXAMPLES["queue"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] queue")


def test_example_case(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    out = _compile_and_run("case", EXAMPLES["case"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn)
    print("[PASS] case")


def test_example_undefined_variable_scan(repo_root: Path, bin_dir: Path, compile_pseudo_fn, capsys):
    """Test that undefined variables in scan statements produce proper semantic errors."""
    example = EXAMPLES["undefined_variable_scan"]
    src = repo_root / "examples" / "basic_tests" / example["file"]
    out = bin_dir / Path(example["file"]).with_suffix("").name
    
    # This should fail to compile
    rc, build_out = compile_pseudo_fn(src, out, debug=False, tsan=False)
    assert rc != 0, f"[BUILD FAIL] undefined_variable_scan should have failed compilation but succeeded\n{build_out}"
    
    # Check that the error message contains the expected semantic error with line number
    assert "semantic error: undefined variable 'a' in scan statement" in build_out, \
        f"[ASSERT FAIL] undefined_variable_scan missing expected error message\nFull output:\n{build_out}"
    
    # Verify it includes a line number
    assert ":2:1:" in build_out or ":2:" in build_out, \
        f"[ASSERT FAIL] undefined_variable_scan missing line number in error\nFull output:\n{build_out}"
    
    print("[PASS] undefined_variable_scan")
