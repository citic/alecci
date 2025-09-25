from __future__ import annotations
from pathlib import Path
import pytest


EXAMPLES = {
    "hello": {
        "file": "hello.pseudo",
        "expect": ["Hello from main thread"],
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
        "file": "scan.pseudo",
        "stdin": "7 9\n",
        "expect": ["Enter two integers:", "You entered a=7, b=9"],
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
        "file": "scan.pseudo",
        "stdin": "7 9\n",
        "expect": ["Enter two integers:", "You entered a=7, b=9"],
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
