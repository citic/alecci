# SCTBench — Alecci Translation

This directory contains Alecci translations of benchmarks from
[SCTBench](https://github.com/mc-imperial/sctbench), a suite of concurrent C and C# programs
used to evaluate schedule-driven concurrency testing tools.

## Source Structure

The original SCTBench repository organises programs into several subdirectories:

| Directory | Description |
|---|---|
| `concurrent-software-benchmarks/` | Small C programs (ESBMC/SV-COMP origin) |
| `inspect_examples/` | C example programs used by INSPECT |
| `chess/`, `chess-m/` | C# programs for the CHESS tool |
| `conc-bugs/` | Real-world C application bugs (bzip2 etc.) |
| `inspect_benchmarks/` | Complex C applications (bzip2, qsort) |
| `parsec-2.0/` | PARSEC parallel benchmark suite |
| `radbench/` | Radically concurrency-buggy programs |
| `splash2/` | SPLASH-2 parallel benchmark suite |

## Selected Benchmarks (42)

### Race benchmarks — TSan detects `data_race`

| File | Source | Bug type | Threads |
|---|---|---|---|
| `race01-yes.ale` | `inspect_examples/race01.c` | Data race | 2 |
| `micro_unprotected_2-yes.ale` | `concurrent-software-benchmarks/micro_2_ok.c` | Data race | 2 |
| `micro_unprotected_3-yes.ale` | `concurrent-software-benchmarks/micro_3_ok.c` | Data race | 3 |
| `micro_unprotected_10-yes.ale` | `concurrent-software-benchmarks/micro_10_ok.c` | Data race | 10 |
| `dpor_example3-yes.ale` | `inspect_examples/dpor-example3.c` | Data race (on a and b) | 3 |
| `reorder_3-yes.ale` | `concurrent-software-benchmarks/reorder_3_bad.c` | Data race (iSet=2, iCheck=1) | 3 |
| `reorder_4-yes.ale` | `concurrent-software-benchmarks/reorder_4_bad.c` | Data race (iSet=3, iCheck=1) | 4 |
| `reorder_5-yes.ale` | `concurrent-software-benchmarks/reorder_5_bad.c` | Data race (iSet=4, iCheck=1) | 5 |
| `reorder_10-yes.ale` | `concurrent-software-benchmarks/reorder_10_bad.c` | Data race (iSet=9, iCheck=1) | 10 |
| `reorder_20-yes.ale` | `concurrent-software-benchmarks/reorder_20_bad.c` | Data race (iSet=10, iCheck=10) | 20 |
| `wronglock_3-yes.ale` | `concurrent-software-benchmarks/wronglock_3_bad.c` | Data race (wrong mutex, 1+3 threads) | 4 |
| `wronglock-yes.ale` | `concurrent-software-benchmarks/wronglock_bad.c` | Data race (wrong mutex, 1+7 threads) | 8 |
| `din_phil2_sat-yes.ale` | `concurrent-software-benchmarks/din_phil2_sat.c` | Data race on `phil` + lock-order inversion | 2 |
| `din_phil3_sat-yes.ale` | `concurrent-software-benchmarks/din_phil3_sat.c` | Data race on `phil` + lock-order inversion | 3 |
| `din_phil4_sat-yes.ale` | `concurrent-software-benchmarks/din_phil4_sat.c` | Data race on `phil` + lock-order inversion | 4 |
| `din_phil5_sat-yes.ale` | `concurrent-software-benchmarks/din_phil5_sat.c` | Data race on `phil` + lock-order inversion | 5 |
| `din_phil6_sat-yes.ale` | `concurrent-software-benchmarks/din_phil6_sat.c` | Data race on `phil` + lock-order inversion | 6 |
| `din_phil7_sat-yes.ale` | `concurrent-software-benchmarks/din_phil7_sat.c` | Data race on `phil` + lock-order inversion | 7 |

### Deadlock benchmarks — TSan detects lock-order inversion

| File | Source | Bug type | Threads |
|---|---|---|---|
| `deadlock01_bad-no.ale` | `concurrent-software-benchmarks/deadlock01_bad.c` | Lock-order inversion (a→b vs b→a) | 2 |
| `din_phil2_unsat-no.ale` | `concurrent-software-benchmarks/din_phil2_unsat.c` | Lock-order inversion on fork mutexes | 2 |
| `din_phil3_unsat-no.ale` | `concurrent-software-benchmarks/din_phil3_unsat.c` | Lock-order inversion on fork mutexes | 3 |
| `din_phil4_unsat-no.ale` | `concurrent-software-benchmarks/din_phil4_unsat.c` | Lock-order inversion on fork mutexes | 4 |
| `din_phil5_unsat-no.ale` | `concurrent-software-benchmarks/din_phil5_unsat.c` | Lock-order inversion on fork mutexes | 5 |
| `din_phil6_unsat-no.ale` | `concurrent-software-benchmarks/din_phil6_unsat.c` | Lock-order inversion on fork mutexes | 6 |
| `din_phil7_unsat-no.ale` | `concurrent-software-benchmarks/din_phil7_unsat.c` | Lock-order inversion on fork mutexes | 7 |

### No-race benchmarks — TSan silent

| File | Source | Reason | Threads |
|---|---|---|---|
| `simple_mutex-no.ale` | `inspect_examples/simple1.c` | Correct mutex use | 2 |
| `stateful01-no.ale` | `concurrent-software-benchmarks/stateful01_ok.c` | Correct mutex use | 2 |
| `account-no.ale` | `concurrent-software-benchmarks/account_ok.c` | Correct single mutex | 3 |
| `lazy01-no.ale` | `concurrent-software-benchmarks/lazy01_bad.c` | Atomicity violation (no data race) | 3 |
| `stack-no.ale` | `concurrent-software-benchmarks/stack_bad.c` | Atomicity violation (no data race) | 2 |
| `twostage-no.ale` | `concurrent-software-benchmarks/twostage_bad.c` | Atomicity violation (no data race) | 3 |
| `twostage_100-no.ale` | `concurrent-software-benchmarks/twostage_100_bad.c` | Atomicity violation (no data race) | 100 |
| `dpor_example1-no.ale` | `inspect_examples/dpor-example1.c` | Correct concurrent hash table | 13 |
| `account_bad-no.ale` | `concurrent-software-benchmarks/account_bad.c` | Logic bug in assertion (not a race) | 3 |
| `sync01-no.ale` | `concurrent-software-benchmarks/sync01_ok.c` | Correct condvar producer-consumer | 2 |
| `sync01_inspect-no.ale` | `inspect_examples/sync01.c` | Correct condvar (1-thread variant) | 1 |
| `sync02-no.ale` | `concurrent-software-benchmarks/sync02_ok.c` | Correct condvar producer-consumer (N=20) | 2 |
| `arithmetic_prog-no.ale` | `concurrent-software-benchmarks/arithmetic_prog_ok.c` | Correct condvar accumulation (N=4) | 2 |
| `arithmetic_prog_bad-no.ale` | `concurrent-software-benchmarks/arithmetic_prog_bad.c` | Wrong assertion (dropped); no race (N=3) | 2 |
| `sync01_bad-no.ale` | `concurrent-software-benchmarks/sync01_bad.c` | Condvar deadlock (num never decremented); times out | 2 |
| `sync02_bad-no.ale` | `concurrent-software-benchmarks/sync02_bad.c` | Condvar deadlock (num starts at 2); times out | 2 |
| `carter01_bad-no.ale` | `concurrent-software-benchmarks/carter01_bad.c` | Potential mutex deadlock; TSan silent | 4 |

The four atomicity-violation benchmarks (`lazy01`, `stack`, `twostage`, `twostage_100`) are from
**known-buggy** SCTBench entries. Their bugs arise from multiple mutex-protected regions that
should execute atomically but do not; all memory accesses are under some mutex so TSan cannot
detect them. They are included to represent this class of beyond-data-race bug.

Note on naming: SCTBench uses `_ok` to mean "no assertion violation under tested schedules",
not "no data race". `micro_2_ok.c`, `micro_3_ok.c`, and `micro_10_ok.c` are in fact racy programs.

`account_bad-no.ale` (from `account_bad.c`) was previously excluded because its bug is a wrong
assertion formula — a logic error rather than a concurrency error. Since Alecci has no `assert`,
the formula cannot be expressed, but the program can still run and serves to document that TSan
is silent on logic bugs.

The condvar benchmarks require Alecci's `condvar` type and `cond_wait` / `cond_signal` /
`cond_broadcast` built-ins. The `_bad` condvar variants deadlock at runtime (condvar hang); TSan
cannot detect this class of bug so they are classified as `expected_issues: [none]` with a short
timeout.

The dining-philosopher `_unsat` variants acquire forks in different orders across threads while
serialised by a shared `esbmc_m` mutex (translating `__ESBMC_atomic_begin/end` from `common.inc`).
Despite the serialisation, TSan tracks the global lock-order graph and reports an inversion.
The `_sat` variants additionally have an unprotected `phil` increment after the serialised section,
producing both a data race and a lock-order-inversion warning.

## Benchmark Results

Results are labelled against the **source ground truth** from `buggy.txt` / `mapleRes.txt`.

| Outcome | Count | Notes |
|---|---|---|
| PASS | 30 | TSan detects exactly what the source says |
| UNEXPECTED | 11 | TSan reports more than the ground truth |
| MISS | 0 | — |
| MISS+UNEXPECTED | 1 | `din_phil2_sat`: data race missed, spurious deadlock reported |

**TSan false positives (lock-order-inversion):** All 12 unexpected/MISS+UNEXPECTED results arise
from TSan flagging lock-order-inversion on the dining philosopher fork mutexes. Because
`esbmc_m` serialises the entire fork-acquire/release block, no actual deadlock can occur — but
TSan still observes the two orderings (right→left vs left→right across threads) and fires.

- `din_phil{2..7}_unsat`: ground truth is *no bug*; TSan's lock-order-inversion is a false positive
- `din_phil{3..7}_sat`: ground truth is *data race on `phil`*; TSan detects both that and the spurious fork inversion (UNEXPECTED deadlock)
- `din_phil2_sat`: ground truth is *data race on `phil`*; with only 2 threads TSan misses the race but reports the spurious fork inversion (MISS+UNEXPECTED)

## Excluded Benchmarks

### Subdirectories excluded entirely

| Directory | Reason |
|---|---|
| `chess/`, `chess-m/` | C# programs; Alecci compiles only C/POSIX-thread semantics |
| `conc-bugs/` | Real application bugs (bzip2, Cherokee, etc.) — complex data structures, file I/O, signal handling; not translatable |
| `inspect_benchmarks/` | bzip2 and qsort — too complex |
| `parsec-2.0/` | Large parallel workloads (PARSEC suite) — complex data structures, file I/O, >1000 LOC each |
| `radbench/` | Real-world application bugs requiring full runtime stacks |
| `splash2/` | SPLASH-2 scientific benchmarks — complex shared data structures, thousands of lines |
| `safestack/` | Memory-safety tests unrelated to concurrency bugs |

### Individual files excluded from `concurrent-software-benchmarks/`

| File | Reason |
|---|---|
| `phase01_bad.c` | Uses `__ESBMC_atomic_begin()` / `__ESBMC_atomic_end()` with semantics beyond a simple mutex wrap |
| `token_ring_bad.c` | Uses `__ESBMC_atomic_begin()` / `__ESBMC_atomic_end()` with semantics beyond a simple mutex wrap |
| `bluetooth_driver_bad.c` | Complex state machine; uses multiple condition variables and linked list traversal |
| `circular_buffer_bad.c` | Uses condition variables for producer/consumer coordination with complex buffer management |
| `queue_bad.c` | Uses condition variables with dynamic linked-list queue — complex data structures |
| `fsbench_bad.c` | File-system benchmark — requires file I/O and kernel interfaces unavailable in Alecci |
| `ctrace-test.c` (inspect_examples) | Tracing library with sockets, linked lists, dynamic allocation, semaphores — far too complex for Alecci |

Previously excluded files that are now included:

| File | Now included as |
|---|---|
| `arithmetic_prog_ok.c` | `arithmetic_prog-no.ale` (condvar support added) |
| `arithmetic_prog_bad.c` | `arithmetic_prog_bad-no.ale` (condvar support added; assert omitted) |
| `sync01_ok.c` | `sync01-no.ale` |
| `sync01_bad.c` | `sync01_bad-no.ale` |
| `sync02_ok.c` | `sync02-no.ale` |
| `sync02_bad.c` | `sync02_bad-no.ale` |
| `sync01.c` (inspect_examples) | `sync01_inspect-no.ale` |
| `deadlock01_bad.c` | `deadlock01_bad-no.ale` |
| `carter01_bad.c` | `carter01_bad-no.ale` |
| `din_phil2_unsat.c` through `din_phil7_unsat.c` | `din_philN_unsat-no.ale` |
| `din_phil2_sat.c` through `din_phil7_sat.c` | `din_philN_sat-yes.ale` |
| `account_bad.c` | `account_bad-no.ale` |

## Running the Tests

```bash
/usr/bin/python3 concurrency_validation/test_runner.py \
  --test-dir concurrency_validation/alecci_benchmarks/SCTBench -j 4
```
