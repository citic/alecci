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
