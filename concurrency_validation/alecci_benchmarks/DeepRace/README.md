# DeepRace — Alecci Translation Summary

## Overview

DeepRace is a benchmark suite derived from real student/course programs collected from
GitHub. Programs are labeled by whether they contain a data race.

**Source:** [Github](https://github.com/tehranixyz/DeepRace)  
**Total source files:** 180 C programs across 3 categories × 2 labels  
**Translated to Alecci:** 62 benchmarks (30 — no race, 32 — race)

---

## Directory Structure

```
DeepRace/
├── OMP_Critical/          OpenMP programs using #pragma omp critical
│   ├── with_datarace/     (30 sources → 19 translated)
│   └── without_datarace/  (30 sources → 14 translated)
├── OMP_Private/           OpenMP programs with shared/private variables
│   ├── with_datarace/     (30 sources → 8 translated)
│   └── without_datarace/  (30 sources → 9 translated)
└── POSIX_Lock_Primitives/ pthreads programs with mutex usage
    ├── with_datarace/     (30 sources → 4 translated)
    └── without_datarace/  (30 sources → 8 translated)
```

---

## Translated Benchmarks

### OMP_Critical / with_datarace — 19 translated

| Alecci file | Source file | Race pattern |
|---|---|---|
| `shared-increment-nolock-yes.ale` | 05_omp_crit_-_main.c | `x = x+1` in parallel, no critical |
| `matrix-sum-nolock-yes.ale` | dynamic2_-_main.c | Parallel for, `suma := suma + a[k]` no lock |
| `monte-carlo-nolock-yes.ale` | 5.40_-_main.c | `total_points := total_points + 1` no lock |
| `array-max-nolock2-yes.ale` | a_-_main.c | Parallel for, `max := a[i]` no lock |
| `array-total-nolock-yes.ale` | array_total_-_main.c | Parallel for, `total := total + a[i]` no lock |
| `float-pi-worksharing-nolock-yes.ale` | Calculo_PI_em_paralelo_WorkSharing_-_main.c | `pi := pi + soma * step` no lock |
| `shared-threadnum-nolock-yes.ale` | conditional_-_main.c | `thread_num := thread_number` no lock |
| `firstprivate-sum-nolock-yes.ale` | datasharing_-_main.c | `m := m + s` no lock across threads |
| `matrix-sum-nolock-yes.ale` | dynamic2_-_main.c | Array reduction no lock |
| `exemple_OMP_22` → `shared-a-pfor-yes.ale` | exemple_OMP_22_-_main.c | `a := i + 1` shared, no lock |
| `float-pi-nolock-yes.ale` | exercise_3_-_main.c | Cyclic PI, `pi := pi + s * step` no lock |
| `fib-array-race-yes.ale` | fibomp_-_main.c | `fib[i] := fib[i-1] + fib[i-2]` loop-carried |
| `for-sum-nolock-yes.ale` | for_-_main.c | `sum := sum + i` no lock |
| `fetch-increment-nolock-yes.ale` | for_dynamic_-_main.c | Work-stealing counter `gi` without lock |
| `global-max-nolock-yes.ale` | global_max_-_main.c | Parallel max, no lock |
| `hitung-nolock-yes.ale` | hitung_-_main.c | Shared counter no lock |
| `shared-i-nolock-yes.ale` | hola_-_main.c | 5 threads write `i := thread_number` no lock |
| `count-incdec-nolock-yes.ale` | hw8_p1a_-_main.c | Odd/even threads inc/dec `count` no lock |
| `float-pi2-nolock-yes.ale` | intepar2_-_main.c | Float PI, 100000 steps, no lock |
| `sum-private-nolock-yes.ale` | mapexpCritical_-_main.c | `total := total + private_sum` no lock |

### OMP_Critical / without_datarace — 14 translated

| Alecci file | Source file | Synchronisation pattern |
|---|---|---|
| `critical-id-no.ale` | 2.hello_-_main.c | lock; `id := thread_number`; unlock |
| `float-pi-cyclic-no.ale` | 5_pi_smp_critical_-_main.c | Cyclic PI, local `s`, mutex merge |
| `determinant-no.ale` | determ_-_main.c | 2 threads compute diagonals, mutex merge |
| `float-pi-padded-no.ale` | helloWorldParallel_Atomic_-_main.c | Block PI, per-thread local sum, mutex merge |
| `float-pi-inline-no.ale` | intel_pi_-_main.c | Parallel for, per-iteration lock around sum |
| `min-max-avg-mutex-no.ale` | lab2_openmp_-_main.c | Lock around min/max/avg update |
| `array-max-critical2-no.ale` | omp12_-_main.c | Parallel for, conditional lock on max |
| `float-pi-partial-no.ale` | pi1_-_main.c | Parallel for, local `partial_sum`, mutex merge |
| `pi-integral-mutex-no.ale` | pi_computation_-_main.c | PI with mutex-protected accumulation |
| `global-max-mutex-no.ale` | q6_-_main.c | Double-checked max with critical |
| `combined-array-count-no.ale` | simple_combined_pfor_-_main.c | Array fill + counter, mutex protected |
| `product-mutex-no.ale` | VarCompPrivModificado_-_main.c | `s := s * (id+1)` with critical |
| `float-pi-syncintegrate-no.ale` | sync-integrate_-_main.c | Cyclic PI, local sum, mutex merge |
| `reduction-mutex-no.ale` | sum_padded_-_main.c | Padded reduction with mutex |

### OMP_Private / with_datarace — 8 translated

| Alecci file | Source file | Race pattern |
|---|---|---|
| `float-pi-noreduction-yes.ale` | PiReduction_-_main.c | 4 threads, `sum := sum + ...` no lock |
| `shared-x-pfor-yes.ale` | array_sum_-_main.c | `x := c[i] * 10`, shared `x`, no lock |
| `isum-nolock-yes.ale` | data_range2_-_main.c | `isum := isum + i` no lock |
| `for-work-sharing_` → `shared-tid-pfor-yes.ale` | for-work-sharing_-_main.c | `tid := thread_number` no lock |
| `shared-x-nolock2-yes.ale` | lec4_-_main.c | 3 threads write `x := thread_number` no lock |
| `shared-myid-yes.ale` | (existing) | Shared myid write without lock |
| `shared-tmp-yes.ale` | (existing) | Shared tmp variable race |
| `shared-x-yes.ale` | (existing) | Shared `x` write race |

### OMP_Private / without_datarace — 9 translated

| Alecci file | Source file | Correctness pattern |
|---|---|---|
| `local-myid-no.ale` | 1.1-hello_-_main.c | Each thread writes to `result[myid]` (unique slot) |
| `barrier-y-z-no.ale` | barrier1_-_main.c | Thread 0 sets `y`, thread 1 sets `z`, barrier, then read |
| `examQuestion` → `local-max-per-thread-no.ale` | examQuestion_-_main.c | Each thread owns `local_max[thread_number]` |
| `for-loop_` → `array-add-pfor-no.ale` | for-loop_-_main.c | `c[i] := a[i] + b[i]`, independent iterations |
| `hello_for_` → `local-myid-pfor-no.ale` | hello_for_-_main.c | Parallel for, `result[i]` — unique per iteration |
| `looptest_1_` → `array-negate-no.ale` | looptest_1_-_main.c | `x[i] := 0 - y[i]`, independent |
| `array-fill-tid-no.ale` | (existing) | Array filled with thread ID (unique per slot) |
| `local-tmp-no.ale` | (existing) | Per-thread local temporary |
| `local-vars-no.ale` | (existing) | Fully local variables, no sharing |

### POSIX_Lock_Primitives / with_datarace — 10 translated

| Alecci file | Source file | Race / issue |
|---|---|---|
| `counter-nolock-yes.ale` | (existing) | Counter increment without lock |
| `flag-nolock-yes.ale` | (existing) | Shared flag write without lock |
| `global-sum-nolock-yes.ale` | (existing) | Sum accumulation without lock |
| `histogram-nolock-yes.ale` | (existing) | Histogram bucket update without lock |
| `canibais-cond-yes.ale` | `130024902_problema_canibais.c` | Cook writes `porcoes := 10` outside `acordar` mutex |
| `two-thread-flag-cond-no.ale` | `TwoThreadLoop.c` | Mislabeled in original — all accesses under lock, no race |
| `unisex-bathroom-cond-yes.ale` | `universidad.c` | `espera_mujeres`/`espera_hombres` incremented under per-sex mutex, decremented under `bano_mutex` |
| `wait-all-cond-yes.ale` | `wait4mult.c` | Workers created but not joined; main exits after condvar wait → thread_leak |
| `readwrite-cond-yes.ale` | `zuoye3.c` | Both threads check `n0 < 200` in outer while without holding mutex |
| `count-threshold-cond-yes.ale` | `threads_cond_mutex.c` | `watch_count` checks `count < 15` in outer while without mutex |

### POSIX_Lock_Primitives / without_datarace — 15 translated

| Alecci file | Source file | Correctness / issue |
|---|---|---|
| `counter-mutex-no.ale` | (existing) | Counter increment with mutex |
| `counter-mutex2-no.ale` | `W9mutex1.c` | 2 threads, counter++ once each with mutex |
| `counter-mutex3-no.ale` | `withmutex.c` | 4 threads, counter++ 100× with mutex |
| `counter-mutex4-no.ale` | `muxtex_anpham.c` | 2 threads, counter++ once with mutex |
| `bucket-sum-mutex-no.ale` | `dana.c` *(see note)* | 7 threads, `sum_rest[bucket]` with mutex |
| `array-sum-mutex-no.ale` | (existing) | Array sum with mutex |
| `global-sum-mutex-no.ale` | (existing) | Global sum accumulation with mutex |
| `scatter-add-mutex-no.ale` | (existing) | Scatter-add with mutex protection |
| `bounded-buffer-cond-no.ale` | `05bounded.c` | Classic bounded buffer (size 4, 30 items) with `more`/`less` condvars |
| `count-threshold-cond-no.ale` | `06_thread_cond_var.c` | 1 watcher + 2 incrementers, COUNT_LIMIT=12; watcher holds mutex before while |
| `count-threshold-outer-cond-yes.ale` | `11-14UseConditionVariable.c` | Mislabeled in original — outer `while count < 7` reads count without mutex |
| `circular-buffer-cond-no.ale` | `ThreadSynCondition.c` | Circular buffer (4 slots), 20 items + sentinel; `notempty`/`notfull` condvars |
| `ping-pong-cond-no.ale` | `ping_pong.c` | Two-thread alternation via single mutex+condvar, 5 rounds |
| `flag-signal-cond-yes.ale` | `x.c` | Two waiters, one `cond_signal` — only one wakes; other stays blocked → thread_leak |
| `count-threshold-4t-cond-no.ale` | `thread_with_conditions.c` | 3 incrementers + 1 watcher, COUNT_LIMIT=12; all under mutex |

> **Note on `dana.c`:** This file is in the `POSIX_Lock_Primitives/with_datarace/` folder but contains
> correct per-bucket mutex synchronisation. It appears mislabeled in the original dataset.
> The Alecci translation is placed in `without_datarace/` with the correct `expected_issues: [none]` label.

### Known Alecci compiler / runtime bugs found during translation

**Bug 1 — `pthread_cond_destroy` called while a thread is blocked in `pthread_cond_wait`**
Files: `flag-signal-cond-yes.ale`, and potentially any program where threads remain blocked at main exit.

`_cleanup_concurrency_primitives` unconditionally calls `pthread_cond_destroy` for every `condvar` declared in `main`. If a thread is still blocked inside `cond_wait` when cleanup runs, calling `pthread_cond_destroy` is undefined behaviour (POSIX) and in glibc causes the destroy call to block indefinitely, hanging the process. The same class of bug was previously found with `pthread_barrier_destroy`.

**Bug 2 — `readwrite-cond-yes.ale` deadlocks faithfully**
File: `readwrite-cond-yes.ale`

The original `zuoye3.c` contains a logical deadlock: if the writer thread advances `n0` to ≥ 200 and exits its loop while the reader thread is blocked inside `cond_wait(cond1)`, the reader will never be woken (no thread is left to signal `cond1`). The Alecci translation faithfully reproduces this bug, causing the program to time out rather than completing.

---

## Skipped Benchmarks

### Reasons for skipping

**1. Two-dimensional arrays** — Alecci supports only 1D arrays. Any benchmark using `a[i][j]` syntax or representing a matrix as a 2D C array cannot be directly translated.

Affected files (examples):
- `OMP_Critical/with_datarace`: `104_-_main.c` (matrix multiply), `c_neighbor_-_main.c` (stencil), `7_-_main.c` (k-means with `points[100000][2]`), `eo_-_main.c` (2D float arrays)
- `OMP_Critical/without_datarace`: `exercise_4_-_main.c`, `histogramaSerie_-_main.c` (`IMA[1000][1000]`), `1braj_-_main.c` (n-body with `pos[1000][2]`)
- `OMP_Private/with_datarace`: `ex6_-_main.c`, `sum2matrix_-_main.c`, `mmOMP_-_main.c`, `CA1_2_-_main.c`, `stencil9_-_main.c`
- `OMP_Private/without_datarace`: `matrix2loops_-_main.c`, `matrix_part1_-_main.c`, `18_for_wait_-_main.c`, `collapse-1_-_main.c`

**2. Structs and pointer arithmetic** — Alecci has no struct type or pointer type. Benchmarks using struct fields or pointer-indexed arrays are not translatable.

Affected files (examples):
- `con_q_-_main.c`, `stack_-_main.c` (linked lists with `nodo *next`)
- `concurrent_prims_-_main.c` (Prim's MST with `prim_data` struct)
- `ejercicio_-_main.c` (k-means with `punto` struct)
- `omparalelo_-_main.c` (genetic algorithm with `numero_t *`)
- `POSIX/with_datarace`: linked list files (`01_condition.c`, `01_job-queue-mutex.c`, `threads_mutex.c`, etc.)
- `POSIX/without_datarace`: multiple files using `node *`, `job_t *`, etc.

**3. Condition variables** — Alecci now supports `condvar()`, `cond_wait(cv, mutex)`, `cond_signal(cv)`, and `cond_broadcast(cv)`. Most POSIX condition variable programs can now be translated. The remaining skips in this category are due to linked lists or structs (see reason 2), not condition variables themselves.

Previously skipped, now translated:
- `POSIX/with_datarace`: `130024902_problema_canibais.c`, `TwoThreadLoop.c`, `universidad.c`, `wait4mult.c`, `zuoye3.c`, `threads_cond_mutex.c`
- `POSIX/without_datarace`: `05bounded.c`, `06_thread_cond_var.c`, `11-14UseConditionVariable.c`, `ThreadSynCondition.c`, `ping_pong.c`, `x.c`, `thread_with_conditions.c`

Still skipped (linked list / struct dependency, not condition variable):
- `POSIX/with_datarace`: `01_condition.c` (linked list with struct Node), `zad8.c` (linked list monitor)
- `POSIX/without_datarace`: `02_condition_modify.c` (linked list with struct Node), `active.c` (declares condvar but uses busy-wait; condition variable unused), `timedwait.c` (uses `pthread_cond_timedwait` with `clock_gettime` — no Alecci equivalent)

**4. External math functions** — `sin`, `cos`, `sqrt`, `pow`, `rand` are not available in Alecci's standard library.

Affected files:
- `eo_-_main.c` (k-means: `sqrt(pow(...))`)
- `7_-_main.c` (k-means: `get_distance`)
- `ziggurat_openmp_original_-_test01.c` (random number generators)
- `HW3ParallelCorrelationFunc2_2_-_main.c` (`log10`, `pow`)
- `fft_openmp_-_main.c` (complex FFT)

**5. Interactive stdin** — `scanf` for runtime input is not supported by the Alecci runtime.

Affected files:
- `11_-_main.c`, `11MultiThreadedFibonacciSeries_-_main.c` (enter n via scanf)
- `concurrent_prims_-_main.c` (enter number of nodes via stdin)
- `12.prims_-_main.c` (enter cost matrix via stdin)
- `trapezoidal_-_main.c` (enter thread count via stdin)

**6. `#pragma omp sections` directive** — Alecci has no sections directive. Work must be partitioned manually with `if thread_number = N`.

Affected files:
- `ex11_-_main.c`, `examen2_5_-_main.c`
- `OMP_Private/with_datarace`: `ej2openmpsections_-_main.c`
- `OMP_Private/without_datarace`: `03_omp_section_-_main.c`, `17_sections_-_main.c`

**7. `pthread_mutex_trylock`** — Non-blocking trylock is not in Alecci's mutex API.

Affected files:
- `POSIX/without_datarace`: `02-altruista.c`

**8. File I/O and network** — `fopen`, `fscanf`, socket operations are not available.

Affected files:
- `sushuthreads_-_main.c` (writes to `result` file)
- `POSIX/without_datarace`: `udp_server.c`

**9. Complex algorithms unsuitable for direct translation** — Some files implement full algorithms (FFT, Mandelbrot, n-body, genetic algorithms, Sieve of Eratosthenes) whose complexity or external function dependencies make faithful translation impractical.

Affected files:
- `fft_openmp_-_main.c`, `mandelbrotpar_-_main.c`, `mandel_workedout_-_main.c`
- `nbodymp_-_main.c`, `ziggurat_openmp_original_-_test01.c`
- `omparalelo_-_main.c`, `pe50par_-_main.c`, `prime-openmp2_-_main.c`

**10. Print-only / no shared mutable state** — A few programs run parallel threads that only call `printf`, with no shared variable to race on.

Affected files:
- `helloworld_-_main.c` (just prints "hello from thread N" with critical)
- `omp-crit_-_main.c` (only prints `x`, minimal shared state)
- `VarCompPrivModificado_-_main.c` (times threads via `omp_get_wtime`, no race to detect) → *translated to product-mutex-no.ale since it does compute a product*
- `hiomp_-_main.c`, `examen_dynamic_-_main.c` (print only)

**11. Mislabeled and skipped to preserve ground truth** — Some files in `with_datarace/` contain correct synchronisation and were NOT translated as racy benchmarks:

- `OMP_Private/with_datarace/omp_criatm_-_main.c`: Both `x = x+1` and `count++` are correctly protected (first with critical, second with atomic). Skipped to avoid a false negative.
- `POSIX/with_datarace/02mutexex.c`: Implements correct mutex usage despite being in the with_datarace folder. Skipped.

**12. Dynamic memory / pointer indirection** — `malloc`/`calloc` with pointer arithmetic.

Affected files:
- `POSIX/with_datarace`: `01_job-queue-mutex.c`, `10_producelink.c`, multiple linked-list files
- `outter_-_main.c` (dynamic array allocation with pointer)
- `laplace_-_main.c` (malloc for grid)

---

## Summary

| Subdirectory | Source files | Translated | Skipped |
|---|---|---|---|
| OMP_Critical/with_datarace | 30 | 19 | 11 |
| OMP_Critical/without_datarace | 30 | 14 | 16 |
| OMP_Private/with_datarace | 30 | 8 | 22 |
| OMP_Private/without_datarace | 30 | 9 | 21 |
| POSIX_Lock_Primitives/with_datarace | 30 | 10 | 20 |
| POSIX_Lock_Primitives/without_datarace | 30 | 15 | 15 |
| **Total** | **180** | **75** | **105** |

### Primary skip reasons by subdirectory

| Subdirectory | Top skip reasons |
|---|---|
| OMP_Critical/with_datarace | 2D arrays, stdin, sections directive, complex algorithms |
| OMP_Critical/without_datarace | 2D arrays, linked lists, complex algorithms, print-only |
| OMP_Private/with_datarace | 2D arrays, sections, task parallelism, complex numerical kernels |
| OMP_Private/without_datarace | 2D arrays, sections, task parallelism, complex algorithms |
| POSIX/with_datarace | Condition variables, linked lists, complex data structures |
| POSIX/without_datarace | Condition variables, linked lists, trylock, file I/O |
