"""Tests that all user-facing AleError paths produce clean error messages."""
from __future__ import annotations
import textwrap
from pathlib import Path
import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _expect_error(
    src: str,
    fragment: str,
    tmp_path: Path,
    compile_fn,
    name: str = "test",
) -> None:
    """Compile *src*, assert failure and that *fragment* appears in stderr."""
    src_file = tmp_path / f"{name}.ale"
    src_file.write_text(textwrap.dedent(src))
    out_path = tmp_path / name
    rc, output = compile_fn(src_file, out_path, debug=False, tsan=False)
    assert rc != 0, f"Expected compilation failure but succeeded.\nOutput:\n{output}"
    assert fragment in output, (
        f"Expected error fragment {fragment!r} not found.\nOutput:\n{output}"
    )


# ---------------------------------------------------------------------------
# Undefined procedure
# ---------------------------------------------------------------------------

def test_error_undefined_procedure(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            foo()
        end procedure
        """,
        "call to undefined procedure 'foo'",
        tmp_path, compile_pseudo_fn,
    )


def test_error_undefined_procedure_in_create_threads(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable t := create_threads(2, nonexistent)
            join_threads(t, 2)
        end procedure
        """,
        "call to undefined procedure 'nonexistent'",
        tmp_path, compile_pseudo_fn,
    )


def test_error_create_threads_no_params(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure worker()
            print "hi"
        end procedure

        procedure main()
            mutable t := create_threads(2, worker)
            join_threads(t, 2)
        end procedure
        """,
        "must have at least one parameter",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# Declaration / assignment errors
# ---------------------------------------------------------------------------

def test_error_const_with_assign_op(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            const x := 5
            print `{x}`
        end procedure
        """,
        "constant 'x' must be declared with '='",
        tmp_path, compile_pseudo_fn,
    )


def test_error_mutable_with_equals_op(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable x = 5
            print `{x}`
        end procedure
        """,
        "mutable variable 'x' must be declared with ':='",
        tmp_path, compile_pseudo_fn,
    )


def test_error_assign_to_constant(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            const x = 5
            x := 10
        end procedure
        """,
        "cannot assign to constant 'x'",
        tmp_path, compile_pseudo_fn,
    )


def test_error_assign_to_constant_array(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            const arr = array(5, 0)
            arr[0] := 99
        end procedure
        """,
        "cannot assign to constant array 'arr'",
        tmp_path, compile_pseudo_fn,
    )


def test_error_undefined_array_in_assignment(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            ghost[0] := 5
        end procedure
        """,
        "undefined array 'ghost'",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# Control flow
# ---------------------------------------------------------------------------

def test_error_break_outside_loop(tmp_path, compile_pseudo_fn):
    # break must be followed by 'while' or 'for' in the grammar
    _expect_error(
        """
        procedure main()
            break while
        end procedure
        """,
        "'break' used outside of a loop",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# Array constructor
# ---------------------------------------------------------------------------

def test_error_array_too_few_args(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable a as array := array(5)
        end procedure
        """,
        "'array()' requires at least 2 arguments",
        tmp_path, compile_pseudo_fn,
    )


def test_error_array_non_constant_size(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable n := 5
            mutable a as array := array(n, 0)
        end procedure
        """,
        "array size must be a constant integer",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# Thread operations
# ---------------------------------------------------------------------------

def test_error_join_thread_wrong_argc(tmp_path, compile_pseudo_fn):
    # create_thread needs the required argument (0 here); then join_thread gets 2 args
    _expect_error(
        """
        procedure task(n as int)
            print "hi"
        end procedure

        procedure main()
            mutable t := create_thread(task, 0)
            mutable extra := 0
            join_thread(t, extra)
        end procedure
        """,
        "join_thread() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


def test_error_undefined_thread_array(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            join_threads(nonexistent, 2)
        end procedure
        """,
        "undefined thread array 'nonexistent'",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# Synchronisation primitive constructors
# ---------------------------------------------------------------------------

def test_error_semaphore_wrong_argc(tmp_path, compile_pseudo_fn):
    # Typed declarations short-circuit arg checking; call as a standalone expression instead
    _expect_error(
        """
        procedure main()
            semaphore(1, 2)
        end procedure
        """,
        "semaphore() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


def test_error_barrier_wrong_argc(tmp_path, compile_pseudo_fn):
    # Typed declarations short-circuit arg checking; call as a standalone expression instead
    _expect_error(
        """
        procedure main()
            barrier(3, 4)
        end procedure
        """,
        "barrier() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


def test_error_barrier_wait_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable b as barrier := barrier(1)
            mutable extra := 0
            barrier_wait(b, extra)
        end procedure
        """,
        "barrier_wait() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


def test_error_cond_wait_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable cv as condvar := condvar()
            cond_wait(cv)
        end procedure
        """,
        "cond_wait() requires exactly 2 arguments",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# Queue operations
# ---------------------------------------------------------------------------

def test_error_enqueue_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable q as queue := queue(5)
            enqueue(q)
        end procedure
        """,
        "enqueue() requires exactly 2 arguments",
        tmp_path, compile_pseudo_fn,
    )


def test_error_dequeue_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable q as queue := queue(5)
            mutable extra := 0
            mutable x := dequeue(q, extra)
        end procedure
        """,
        "dequeue() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


def test_error_queue_size_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable q as queue := queue(5)
            mutable extra := 0
            const sz = queue_size(q, extra)
        end procedure
        """,
        "queue_size() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


def test_error_queue_capacity_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable q as queue := queue(5)
            mutable extra := 0
            const cap = queue_capacity(q, extra)
        end procedure
        """,
        "queue_capacity() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


def test_error_undefined_queue_variable(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            enqueue(ghost_queue, 5)
        end procedure
        """,
        "undefined queue variable 'ghost_queue'",
        tmp_path, compile_pseudo_fn,
    )


def test_error_variable_not_a_queue(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable x := 5
            enqueue(x, 10)
        end procedure
        """,
        "is not a queue",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# Math functions
# ---------------------------------------------------------------------------

def test_error_sqrt_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable r := sqrt(4, 9)
        end procedure
        """,
        "sqrt() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


def test_error_abs_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable r := abs(1, 2)
        end procedure
        """,
        "abs() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


def test_error_pow_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable r := pow(2)
        end procedure
        """,
        "pow() requires exactly 2 arguments",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# rand / sleep / seed
# ---------------------------------------------------------------------------

def test_error_rand_too_many_args(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable r := rand(1, 10, 100)
        end procedure
        """,
        "rand() requires 0, 1 or 2 arguments",
        tmp_path, compile_pseudo_fn,
    )


def test_error_sleep_no_args(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            sleep()
        end procedure
        """,
        "sleep() requires 1 or 2 arguments",
        tmp_path, compile_pseudo_fn,
    )


def test_error_sleep_bad_unit(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            sleep(1, "hours")
        end procedure
        """,
        "unknown sleep() unit 'hours'",
        tmp_path, compile_pseudo_fn,
    )


def test_error_seed_removed(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            seed(42)
        end procedure
        """,
        "seed() is no longer needed",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# int() conversion
# ---------------------------------------------------------------------------

def test_error_int_wrong_argc(tmp_path, compile_pseudo_fn):
    _expect_error(
        """
        procedure main()
            mutable x := int(5, 6)
        end procedure
        """,
        "int() requires exactly 1 argument",
        tmp_path, compile_pseudo_fn,
    )


# ---------------------------------------------------------------------------
# Verify errors include a line number
# ---------------------------------------------------------------------------

def test_error_includes_line_number(tmp_path, compile_pseudo_fn):
    """AleError should include '(line N)' in the output."""
    src = textwrap.dedent("""
        procedure main()
            foo()
        end procedure
    """)
    src_file = tmp_path / "lineno_test.ale"
    src_file.write_text(src)
    out_path = tmp_path / "lineno_test"
    rc, output = compile_pseudo_fn(src_file, out_path, debug=False, tsan=False)
    assert rc != 0
    assert "(line " in output, (
        f"Expected '(line N)' in error output.\nOutput:\n{output}"
    )
