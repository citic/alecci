from __future__ import annotations
from pathlib import Path
import pytest


EXAMPLES = {
    "fibonacci": {
        "file": "fibonacci.ale",
        "expect": [
            "Fibonacci test start",
            "fib(0) = 0",
            "fib(1) = 1",
            "fib(5) = 5",
            "fib(10) = 55",
            "fib_iter(10) = 55",
            "fib_iter(15) = 610",
            "gcd(48, 18) = 6",
            "gcd(100, 75) = 25",
            "Fibonacci test end",
        ],
    },
    "thread_counter": {
        "file": "thread_counter.ale",
        "expect": [
            "Counter test start",
            "Final counter = 40",
            "Counter test end",
        ],
    },
    "prod_cons_sem": {
        "file": "prod_cons_sem.ale",
        "expect": [
            "Producer-consumer test start",
            "Items consumed = 4",
            "Producer-consumer test end",
        ],
    },
    "barrier_pipeline": {
        "file": "barrier_pipeline.ale",
        "expect": [
            "Barrier pipeline test start",
            "Phase 1 sum = 14",
            "Phase 2 sum = 10",
            "Barrier pipeline test end",
        ],
    },
    "complex_math": {
        "file": "complex_math.ale",
        "expect": [
            "Math test start",
            "2^8 = 256",
            "sum of squares 1..5 = 55",
            "collatz(27) steps = 111",
            "multiples of 3 or 5 in 1..29 = 13",
            "Math test end",
        ],
    },
    "array_thread_scatter": {
        "file": "array_thread_scatter.ale",
        "expect": [
            "Array scatter test start",
            "results[0] = 0",
            "results[1] = 2",
            "results[2] = 6",
            "results[3] = 12",
            "Total = 20",
            "Array scatter test end",
        ],
    },
    "variant_mixed_ops": {
        "file": "variant_mixed_ops.ale",
        "expect": [
            "Variant mixed ops test start",
            "v after int ops = 15",
            "two",
            "arr[2] = 4",
            "arr[4] = 16",
            "Variant mixed ops test end",
        ],
    },
    "shared_multi_accum": {
        "file": "shared_multi_accum.ale",
        "expect": [
            "Shared multi-accumulator test start",
            "sum_of_ids = 6",
            "sum_of_products = 10",
            "Shared multi-accumulator test end",
        ],
    },
    "array_index_exprs": {
        "file": "array_index_exprs.ale",
        "expect": [
            "Array index expressions test start",
            "arr[0] = 0",
            "arr[1] = 10",
            "arr[2] = 1",
            "arr[3] = 9",
            "arr[6] = 9",
            "arr[7] = 7",
            "Total after doubling = 96",
            "Array index expressions test end",
        ],
    },
    "parallel_reduce": {
        "file": "parallel_reduce.ale",
        "expect": [
            "Parallel reduce test start",
            "Total = 36",
            "Parallel reduce test end",
        ],
    },
    "typed_params": {
        "file": "typed_params.ale",
        "expect": [
            "Typed params test start",
            'label = "alpha"',
            "ratio = 2.500000",
            "Typed params test end",
        ],
    },
    "deadlock_warning_if_branch": {
        "file": "deadlock_warning_if_branch.ale",
        "build_expect": [
            "deadlock warning",
            "semaphore 'permits'",
        ],
        "skip_run": True,
    },
    "record_init": {
        "file": "record_init.ale",
        "build_expect": [
            "error: 'record initialization' is not yet supported",
        ],
        "build_fail": True,
    },
    "debug_parser_output": {
        "file": "debug_parser_output.ale",
        "build_expect": [
            "Parsing code:",
            "Parse result:",
        ],
        "skip_run": True,
        "debug": True,
    },
}


def _compile_and_run_complex(
    name: str,
    example: dict,
    repo_root: Path,
    bin_dir: Path,
    compile_pseudo_fn,
    run_exe_fn,
) -> str:
    src = repo_root / "examples" / "complex_tests" / example["file"]
    out = bin_dir / Path(example["file"]).with_suffix("").name
    rc, build_out = compile_pseudo_fn(src, out, debug=False, tsan=False)
    assert rc == 0, f"[BUILD FAIL] {name}\n{build_out}"
    rc, run_out = run_exe_fn(out, args=example.get("args"), stdin=example.get("stdin"))
    assert rc == 0, f"[RUN FAIL] {name}\n{run_out}"
    for needle in example["expect"]:
        assert needle in run_out, (
            f"[ASSERT FAIL] {name} missing: {needle!r}\nFull output:\n{run_out}"
        )
    return run_out


def _compile_complex_only(
    name: str,
    example: dict,
    repo_root: Path,
    bin_dir: Path,
    compile_pseudo_fn,
) -> str:
    src = repo_root / "examples" / "complex_tests" / example["file"]
    out = bin_dir / Path(example["file"]).with_suffix("").name
    rc, build_out = compile_pseudo_fn(src, out, debug=example.get("debug", False), tsan=False)
    assert rc == 0, f"[BUILD FAIL] {name}\n{build_out}"
    for needle in example.get("build_expect", []):
        assert needle in build_out, (
            f"[ASSERT FAIL] {name} missing build output: {needle!r}\nFull build output:\n{build_out}"
        )
    return build_out


def test_complex_fibonacci(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "fibonacci", EXAMPLES["fibonacci"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] fibonacci")


def test_complex_thread_counter(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "thread_counter", EXAMPLES["thread_counter"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] thread_counter")


def test_complex_prod_cons_sem(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "prod_cons_sem", EXAMPLES["prod_cons_sem"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] prod_cons_sem")


def test_complex_barrier_pipeline(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "barrier_pipeline", EXAMPLES["barrier_pipeline"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] barrier_pipeline")


def test_complex_math(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "complex_math", EXAMPLES["complex_math"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] complex_math")


def test_complex_array_thread_scatter(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "array_thread_scatter", EXAMPLES["array_thread_scatter"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] array_thread_scatter")


def test_complex_variant_mixed_ops(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "variant_mixed_ops", EXAMPLES["variant_mixed_ops"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] variant_mixed_ops")


def test_complex_shared_multi_accum(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "shared_multi_accum", EXAMPLES["shared_multi_accum"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] shared_multi_accum")


def test_complex_array_index_exprs(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "array_index_exprs", EXAMPLES["array_index_exprs"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] array_index_exprs")


def test_complex_parallel_reduce(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "parallel_reduce", EXAMPLES["parallel_reduce"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] parallel_reduce")


def test_complex_typed_params(repo_root: Path, bin_dir: Path, compile_pseudo_fn, run_exe_fn, capsys):
    _compile_and_run_complex(
        "typed_params", EXAMPLES["typed_params"], repo_root, bin_dir, compile_pseudo_fn, run_exe_fn
    )
    print("[PASS] typed_params")


def test_complex_deadlock_warning_if_branch(repo_root: Path, bin_dir: Path, compile_pseudo_fn, capsys):
    _compile_complex_only(
        "deadlock_warning_if_branch", EXAMPLES["deadlock_warning_if_branch"], repo_root, bin_dir, compile_pseudo_fn
    )
    print("[PASS] deadlock_warning_if_branch")


def test_complex_record_init(repo_root: Path, bin_dir: Path, compile_pseudo_fn, capsys):
    example = EXAMPLES["record_init"]
    src = repo_root / "examples" / "complex_tests" / example["file"]
    out = bin_dir / Path(example["file"]).with_suffix("").name
    rc, build_out = compile_pseudo_fn(src, out, debug=False, tsan=False)
    assert rc != 0, f"[SHOULD FAIL] record_init was expected to fail but succeeded"
    for needle in example.get("build_expect", []):
        assert needle in build_out, (
            f"[ASSERT FAIL] record_init missing error text: {needle!r}\nFull build output:\n{build_out}"
        )
    print("[PASS] record_init")


def test_complex_debug_parser_output(repo_root: Path, bin_dir: Path, compile_pseudo_fn, capsys):
    _compile_complex_only(
        "debug_parser_output", EXAMPLES["debug_parser_output"], repo_root, bin_dir, compile_pseudo_fn
    )
    print("[PASS] debug_parser_output")
