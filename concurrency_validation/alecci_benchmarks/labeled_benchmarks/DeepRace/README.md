# DeepRace — Alecci Translation Summary

## Overview

DeepRace is a benchmark suite derived from real student/course programs collected from
GitHub. Programs are labeled by whether they contain a data race.

**Source:** [Github](https://github.com/tehranixyz/DeepRace)  
**Total source files:** 180 C programs across 3 categories × 2 labels  
**Translated to Alecci:** 96 benchmarks (50 — no race, 46 — race)

---

## Directory Structure

```
DeepRace/
├── OMP_Critical/          OpenMP programs using #pragma omp critical
│   ├── with_datarace/     (30 sources → 24 translated)
│   └── without_datarace/  (30 sources → 20 translated)
├── OMP_Private/           OpenMP programs with shared/private variables
│   ├── with_datarace/     (30 sources → 9 translated)
│   └── without_datarace/  (30 sources → 14 translated)
└── POSIX_Lock_Primitives/ pthreads programs with mutex usage
    ├── with_datarace/     (30 sources → 13 translated)
    └── without_datarace/  (30 sources → 16 translated)
```

---

## Translated Benchmarks

### OMP_Critical / with_datarace — 24 translated

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
| `matrix-mul-k-race-yes.ale` | 104_-_main.c | Matrix multiply a[4×2]×b[2×6] (1D-flattened), shared inner-loop `k` races across 3 threads |
| `kmeans-race-yes.ale` | eo_-_main.c | K-means (2 centroids, 10 points); float arrays flattened; sum1/sum2/len1/len2 raced without critical |
| `parallel-increment-yes.ale` | 05_omp_crit_-_main.c | 4 threads each increment shared `x` once without protection; write-vs-write race |
| `parallel-max-nolock-yes.ale` | omp12_-_main.c | Parallel max over fixed array; check and update are separate (TOCTOU), no atomic — race on `max_val` |
| `shared-local-accumulate-yes.ale` | datasharing_-_main.c | Each thread accumulates locally then merges into shared `m` without a critical — race on merge |

### OMP_Critical / without_datarace — 20 translated

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
| `fibonacci-critical-no.ale` | fibo_-_main.c | Fibonacci via mutex-serialised while loop; first thread runs all n iterations, others exit immediately; stdin for n |
| `histogramaSerie_-_main.ale` | histogramaSerie_-_main.c | Parallel histogram of 100×100 matrix (values 0-255); each bucket increment under mutex; hmin/imin printed |
| `hello-atomic-no.ale` | helloworld_-_main.c | 2 threads each print their ID inside an `atomic do` block; no shared mutable state beyond the atomic serialisation |
| `parallel-increment-atomic-no.ale` | 05_omp_crit_-_main.c | 4 threads increment shared `x` once each, protected by `atomic do`; no race |
| `parallel-max-atomic-no.ale` | omp12_-_main.c | Parallel max over fixed array; `atomic do` covers both check and update — no TOCTOU |
| `shared-local-accumulate-no.ale` | datasharing_-_main.c | Each thread accumulates locally then merges into shared `m` via `atomic do`; no race |

### OMP_Private / with_datarace — 9 translated

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
| `matrix-add-shared-yes.ale` | ex6_-_main.c | A[6×10]+B[6×10]=C[6×10] (1D-flattened), shared `id/sid/eid` race across 6 threads |

### OMP_Private / without_datarace — 14 translated

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
| `two-pfor-fill-no.ale` | fig4.12-two-for-loops_-_main.c | Two sequential parallel fors: fill a[9]:=i then b[9]:=2·a[i]; barrier prevents race |
| `digit-square-pow-no.ale` | 9.ved_-_main.c | Computes N² via digit decomposition using pow(10,k); one thread per digit, mutex-guarded accumulation; stdin for N |
| `18_for_wait_-_main.ale` | 18_for_wait_-_main.c | Two sequential parallel fors: upper triangle `a[i][j]=i+j` (j≥i) then lower triangle `a[i][j]=i-j` (j<i); disjoint writes, implicit barrier |
| `matrix_part1_-_main.ale` | matrix_part1_-_main.c | Matrix multiply C=A×B; `parallel for i` distributes rows of C; inner j,k loops serial; each thread writes distinct c[i][j] |
| `matrix2loops_-_main.ale` | matrix2loops_-_main.c | Phase 1: `parallel for i` zeroes c; Phase 2: serial i + `parallel for j` computes row of C; row proxy for outer i; no race on distinct c[row][j] |

### POSIX_Lock_Primitives / with_datarace — 13 translated

| Alecci file | Source file | Race / issue |
|---|---|---|
| `counter-nolock-yes.ale` | (existing) | Counter increment without lock |
| `flag-nolock-yes.ale` | (existing) | Shared flag write without lock |
| `global-sum-nolock-yes.ale` | (existing) | Sum accumulation without lock |
| `histogram-nolock-yes.ale` | (existing) | Histogram bucket update without lock |
| `bucket-sum-mutex-no.ale` | `dana.c` | 7 threads, `sum_rest[bucket]` with mutex; TSan may miss |
| `canibais-cond-yes.ale` | `130024902_problema_canibais.c` | Cook writes `porcoes := 10` outside `acordar` mutex |
| `two-thread-flag-cond-no.ale` | `TwoThreadLoop.c` | All accesses under lock; TSan may miss the declared race |
| `unisex-bathroom-cond-yes.ale` | `universidad.c` | `espera_mujeres`/`espera_hombres` incremented under per-sex mutex, decremented under `bano_mutex` |
| `wait-all-cond-yes.ale` | `wait4mult.c` | Workers not joined; main exits after condvar wait |
| `readwrite-cond-yes.ale` | `zuoye3.c` | Both threads check `n0 < 200` in outer while without holding mutex |
| `count-threshold-cond-yes.ale` | `threads_cond_mutex.c` | `watch_count` checks `count < 15` in outer while without mutex |
| `histogram-rand-no.ale` | `assiOS.c` | 5-thread stride histogram, rand init; all under mutex; TSan may miss |
| `ticket-counter-no.ale` | `11_mutex.c` | 2 threads sell 100 tickets under mutex; TSan may miss |

### POSIX_Lock_Primitives / without_datarace — 16 translated

| Alecci file | Source file | Correctness / issue |
|---|---|---|
| `counter-mutex-no.ale` | (existing) | Counter increment with mutex |
| `counter-mutex2-no.ale` | `W9mutex1.c` | 2 threads, counter++ once each with mutex |
| `counter-mutex3-no.ale` | `withmutex.c` | 4 threads, counter++ 100× with mutex |
| `counter-mutex4-no.ale` | `muxtex_anpham.c` | 2 threads, counter++ once with mutex |
| `array-sum-mutex-no.ale` | (existing) | Array sum with mutex |
| `global-sum-mutex-no.ale` | (existing) | Global sum accumulation with mutex |
| `scatter-add-mutex-no.ale` | (existing) | Scatter-add with mutex protection |
| `bounded-buffer-cond-no.ale` | `05bounded.c` | Classic bounded buffer (size 4, 30 items) with `more`/`less` condvars |
| `count-threshold-cond-no.ale` | `06_thread_cond_var.c` | 1 watcher + 2 incrementers, COUNT_LIMIT=12; watcher holds mutex before while |
| `count-threshold-outer-cond-yes.ale` | `11-14UseConditionVariable.c` | Outer `while count < 7` reads count outside mutex; TSan reports unexpected race |
| `circular-buffer-cond-no.ale` | `ThreadSynCondition.c` | Circular buffer (4 slots), 20 items + sentinel; `notempty`/`notfull` condvars |
| `ping-pong-cond-no.ale` | `ping_pong.c` | Two-thread alternation via single mutex+condvar, 5 rounds |
| `flag-signal-cond-yes.ale` | `x.c` | Two waiters, one `cond_signal`; TSan reports unexpected thread_leak |
| `count-threshold-4t-cond-no.ale` | `thread_with_conditions.c` | 3 incrementers + 1 watcher, COUNT_LIMIT=12; all under mutex |
| `lock-order-no.ale` | `01-trava_dupla.c` | ABBA lock-order inversion; TSan reports unexpected deadlock |
| `lock-order-rand-no.ale` | `04-random_sleep.c` | ABBA lock-order inversion with rand sleep jitter; TSan reports unexpected deadlock |

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

**1. Two-dimensional arrays** — 2D arrays can be flattened: `a[i][j]` becomes `a[i*cols + j]` in a 1D Alecci array. Remaining skips in this category are blocked by a secondary reason (external functions, complex/buggy algorithms, or runtime support gaps like `clock_t`).

Skipped (secondary blocker):
- `OMP_Critical/with_datarace`: `c_neighbor_-_main.c` (gettimeofday struct + heavy init loop), `7_-_main.c` (undefined helpers `populate_points`/`get_distance`; stdin)
- `OMP_Critical/without_datarace`: `exercise_4_-_main.c` (triple nested init + gettimeofday struct), `1braj_-_main.c` (uninitialized `k` makes inner while dead; rand(); clock_t)
- `OMP_Private/with_datarace`: `sum2matrix_-_main.c` (same race pattern as ex6, not adding), `mmOMP_-_main.c` (same shared-tid race pattern as existing benchmarks), `stencil9_-_main.c` (fabs/fmax/clock_gettime)
- `OMP_Private/without_datarace`: `collapse-1_-_main.c` (abort + pow)

**2. Structs and pointer arithmetic** — Alecci now supports user-defined record types (`record … of … end record`), so simple value-type structs can be modelled. However, all struct-using benchmarks in this suite also require pointer arithmetic, `malloc`/`free`, or `*next` linked list traversal which Alecci still cannot express. No DeepRace benchmark was unlocked by record support alone.

Affected files (examples):
- `con_q_-_main.c`, `stack_-_main.c` (linked lists with `nodo *next` — pointer chaining required)
- `concurrent_prims_-_main.c` (Prim's MST with `prim_data` struct — also needs stdin and complex algorithm)
- `ejercicio_-_main.c` (k-means with `punto` struct — also needs `malloc`, `sqrt`, `rand`)
- `omparalelo_-_main.c` (genetic algorithm with `numero_t *` — pointer arithmetic required)
- `POSIX/with_datarace`: linked list files (`01_condition.c`, `01_job-queue-mutex.c`, `threads_mutex.c`, etc.) — all require `malloc`+`*next` chaining
- `POSIX/without_datarace`: multiple files using `node *`, `job_t *`, etc. — same

**3. Condition variables** — Alecci supports `condvar()`, `cond_wait(cv, mutex)`, `cond_signal(cv)`, and `cond_broadcast(cv)`. Remaining skips in this category are due to linked lists or structs (see reason 2), not condition variables.

Skipped (linked list / struct dependency):
- `POSIX/with_datarace`: `01_condition.c` (linked list with struct Node), `zad8.c` (linked list monitor)
- `POSIX/without_datarace`: `02_condition_modify.c` (linked list with struct Node), `active.c` (declares condvar but uses busy-wait; condition variable unused), `timedwait.c` (uses `pthread_cond_timedwait` with `clock_gettime` — no Alecci equivalent)

**4. External math functions** — Alecci provides `sqrt(x)`, `abs(x)` (int and float), `pow(x, y)` (int and float), and `rand([max])`. Missing: `sin`, `cos`, `log`, `log10`, `fmax`, `floor`.

Skipped:
- `ziggurat_openmp_original_-_test01.c` (complex random number generators — algorithm too complex)
- `HW3ParallelCorrelationFunc2_2_-_main.c` (`log10`, `cos`, `sin`, file I/O — beyond scope)
- `fft_openmp_-_main.c` (complex FFT — trig functions)
- `1braj_-_main.c` (n-body: rand() for init; clock_t for timing; complex nested loop structure)

**5. Interactive stdin** — Alecci supports `scan \`prompt {var}\`` and the test suite pipes `stdin_file` to the program. Remaining skips have secondary blockers beyond stdin.

Skipped:
- `11_-_main.c` (uses `fib()` function not defined in the file)
- `11MultiThreadedFibonacciSeries_-_main.c` (complex nested parallel structure)
- `concurrent_prims_-_main.c` (Prim's MST — complex linked list + stdin)
- `12.prims_-_main.c` (enter cost matrix — file I/O structure)
- `trapezoidal_-_main.c` (uses `f(x)` and `gettimeofday_sec()` — undefined functions)
- `7_-_main.c` (k-means: `populate_points()` and `get_distance()` undefined; stdin)

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

**11. Programs skipped from `with_datarace/` where translation would produce no TSan-detectable issue** — The original dataset is taken as ground truth; these files are skipped rather than translated as false negatives, because the concurrency pattern cannot be faithfully expressed in Alecci in a way TSan would detect.

- `OMP_Private/with_datarace/omp_criatm_-_main.c`: Both `x = x+1` and `count++` are protected by OpenMP atomic/critical directives that Alecci does not support natively. Skipped.
- `POSIX/with_datarace/02mutexex.c`: Uses `pthread_mutex_trylock` (not in Alecci's API). Skipped.

**12. Dynamic memory / pointer indirection** — `malloc`/`calloc` with pointer arithmetic.

Affected files:
- `POSIX/with_datarace`: `01_job-queue-mutex.c`, `10_producelink.c`, multiple linked-list files
- `outter_-_main.c` (dynamic array allocation with pointer)
- `laplace_-_main.c` (malloc for grid)

---

## Summary

| Subdirectory | Source files | Translated | Skipped |
|---|---|---|---|
| OMP_Critical/with_datarace | 30 | 24 | 6 |
| OMP_Critical/without_datarace | 30 | 20 | 10 |
| OMP_Private/with_datarace | 30 | 9 | 21 |
| OMP_Private/without_datarace | 30 | 14 | 16 |
| POSIX_Lock_Primitives/with_datarace | 30 | 13 | 17 |
| POSIX_Lock_Primitives/without_datarace | 30 | 16 | 14 |
| **Total** | **180** | **96** | **84** |

### Primary skip reasons by subdirectory

| Subdirectory | Top skip reasons |
|---|---|
| OMP_Critical/with_datarace | undefined helper functions, sections directive, complex algorithms, gettimeofday/clock_t |
| OMP_Critical/without_datarace | linked lists, complex algorithms, print-only, gettimeofday/clock_t |
| OMP_Private/with_datarace | sections directive, complex numerical kernels |
| OMP_Private/without_datarace | sections directive, complex algorithms (abort + pow) |
| POSIX/with_datarace | linked lists / dynamic memory, complex data structures |
| POSIX/without_datarace | linked lists / dynamic memory, trylock, file I/O |
