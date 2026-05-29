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

## Selected Benchmarks (21)

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

`micro_unprotected_10-yes.ale` and `dpor_example3-yes.ale` were overlooked in the original
selection. They follow the same patterns as the existing micro and dpor benchmarks.

## Benchmark Results

All 21 benchmarks pass the test runner (21/21). The 12 data-race benchmarks are consistently
detected by TSan; the 9 no-race benchmarks produce no false positives.

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
| `arithmetic_prog_bad.c` / `arithmetic_prog_ok.c` | Uses `pthread_cond_wait` / `pthread_cond_signal` — Alecci has no condition variables |
| `sync01_bad.c` / `sync01_ok.c` | Uses condition variables |
| `sync02_bad.c` / `sync02_ok.c` | Uses condition variables |
| `deadlock01_bad.c` | Intentional deadlock via mismatched lock ordering; requires condition variables to exercise meaningfully |
| `din_phil2_sat.c` through `din_phil7_sat.c` | Dining philosophers with condition variables |
| `phase01_bad.c` | Uses `__ESBMC_atomic_begin()` / `__ESBMC_atomic_end()` — model-checker intrinsics with no POSIX equivalent |
| `token_ring_bad.c` | Uses `__ESBMC_atomic_begin()` / `__ESBMC_atomic_end()` |
| `bluetooth_driver_bad.c` | Complex state machine; uses multiple condition variables and linked list traversal |
| `circular_buffer_bad.c` | Uses condition variables for producer/consumer coordination |
| `queue_bad.c` | Uses condition variables |
| `account_bad.c` | ~~Logic bug in assertion formula, not a concurrency bug~~ — now included as `account_bad-no.ale`; Alecci has no `assert` so the formula cannot be expressed, but the program can run and TSan is correctly silent |
| `carter01_bad.c` | Reader-writer deadlock pattern with two interleaved mutexes; potential deadlock only, not a data race — deadlocks are not detectable by TSan and cannot be provoked from Alecci without condition variables |
| `fsbench_bad.c` | File-system benchmark — requires file I/O and kernel interfaces unavailable in Alecci |
| `ctrace-test.c` (inspect_examples) | Tracing library with sockets, linked lists, dynamic allocation, semaphores — far too complex for Alecci |
| `sync01.c` (inspect_examples) | Uses condition variables |

## Running the Tests

```bash
/usr/bin/python3 concurrency_validation/test_runner.py \
  --test-dir concurrency_validation/alecci_benchmarks/SCTBench -j 4
```
