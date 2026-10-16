# Alecci benchmark translation review

Review of every Alecci benchmark that is derived from a C source, checking that the `.ale`
file is a *complete* translation of the original C program (all threads / parallel regions,
shared state, synchronisation, control flow, assertions and printed output), using
`shared-a-pfor-yes.ale` as the reference for what "incomplete" looked like.

C sources used: `/home/bulat/tesis/alecci-tests/{DeepRace,dataracebench-master,sctbench}`.

## 1. Scope

| Suite | `.ale` files | Reviewed | Rewritten / edited | Already complete |
|---|---|---|---|---|
| DeepRace (OMP_Critical, OMP_Private, POSIX_Lock_Primitives) | 96 | 96 | 91 (incl. the example you fixed) | 5 |
| DataRaceBench (N1, N2, N3, N7, Y1, Y2, Y3) | 60 | 60 | 56 | 4 |
| SCTBench | 48 | 48 | 37 | 11 |
| ClassExamples (`build_h2o`, `dancing_pairs`, …) | 56 | not reviewed | – | – |

ClassExamples are not translations of C: their source is student pseudocode / Alecci already
(`alecci-tests/taskc`), so there is nothing to compare them against.

Method per file: locate the C source (header comment, DRB number, SCTBench name), diff behaviour
against the `.ale`, rewrite where it was incomplete, compile with the repo compiler
(TSan on) and run it, then run the whole suite through `concurrency_validation/test_runner.py`
and compare against the existing `results/*.csv`.

## 2. What "incomplete" meant in practice

The same defects repeat across the suites:

1. **Output dropped** – `printf` results, prompts, final sums, `Success!/Fail!`, trace lines.
2. **Only the racy fragment kept** – outer loops (100 test rounds, `j = 1..16` thread counts),
   extra parallel regions, second/third programs (`shared-myid-yes` merges three C files),
   serial reference passes, `master`/`single`/`barrier` constructs.
3. **Different data than the C** – int arrays instead of `double`, invented initial values
   (`a[i] = i` where C leaves zeros, `i + 1` where C has a literal matrix), wrong thread counts
   (3 instead of 4, 4 instead of 10, 2 incrementers instead of 3).
4. **Different algorithm** – e.g. `pi-integral-mutex-no` / `reduction-mutex-no` summed integers
   instead of computing π; `global-sum-*`, `counter-nolock-yes`, `flag-nolock-yes` were generic
   patterns unrelated to the C file they cite; `matrix-mul-k-race-yes` used `/` (true division) for
   a row index; `DRB060` used `c[i][k] += a[i][j]*b[j][k]` instead of the C index pattern.
5. **Assertions removed** – about 25 SCTBench translations dropped `assert(...)` because of the
   outdated note "Alecci has no assert"; asserts exist now and were restored.
6. **Input via stdin / argv ignored** – `scanf`, `atoi(argv[1])`, optional `iSet/iCheck` parameters.

## 3. Conventions used in the rewritten files

* Every deviation is documented in the file header (`Deviations:` lines) and nothing silent is left.
* `#pragma omp parallel` (no `for`) → `create_threads(N, worker)` + `join_threads`; default team = **4**.
* `omp for` inside a region → static block split computed in the worker; `reduction(+:x)` →
  private partial sum combined under a mutex (or barrier + mutex where the C has implicit barriers);
  `master`/`single` → `thread_number = 0` (or a first-arrival flag where winner matters);
  `critical` → mutex, `critical(A)/critical(B)` → two mutexes, `atomic` → `atomic do`.
* Multi-dimensional arrays are flattened (`a[i][j]` → `a[i*N+j]`).
* Timing code (`omp_get_wtime`, `time()`, `gettimeofday`) is dropped; `srand()` is dropped;
  `rand() % n` → `rand(n)`; `exp(x)` → `pow(2.718281828459045, x)`.
* `scanf` → `scan`, with a new `*.txt` + `stdin_file:` in the yaml (same mechanism
  `fibonacci-critical-no` already used). New files: `fib-array-race-yes.txt`,
  `monte-carlo-nolock-yes.txt`, `float-pi-noreduction-yes.txt`, `matrix2loops_-_main.txt`.
* Problem sizes are only reduced where the original is infeasible under TSan or hits the
  compiler limits listed below; each reduction is stated in the header.
* Where the C source loops forever (`while(1)`, `while (TRUE)`) the translation is bounded
  (`canibais`, `DRB191`) so the program terminates; stated in the header.

## 4. Compiler / tooling findings (these shaped some translations)

**Update:** findings 1–3 are fixed on `main` (commits `6c6f55c`, `ca3e4fd`, `362c893`). The benchmarks that had been scaled down for finding 3 were restored to the C sizes (`DRB037/038` 1000×1000, `DRB062` N=1000, `DRB190` 1000 packages, `counter-mutex-no`/`counter-mutex3-no` 1000 rounds, `float-pi-cyclic-no` 100000 steps, `shared-tmp-yes`/`local-tmp-no` p=8..14); `float-pi-padded-no` went from 40 000 to 400 000 steps (the C has 200 000 000, TSan cost). `DRB031/032` stay at 100×100 (TSan no longer reports the race at 400×400+). Yaml timeouts of the slower ones were raised. The table below describes the behaviour *before* the fixes.


| # | Finding | Effect |
|---|---|---|
| 1 | `shared mutable a := array(n, v)` only honours an **integer literal** `n`; any other expression silently gives a **10-element** array (`_resolve_shared_array_size`, `compiler.py:771`). | Earlier attempts with `array(size, …)` segfaulted. `var` DRB variants therefore use a literal capacity and clamp `len` to it. |
| 2 | The initial value of `array(n, v)` is **ignored** (zeros for shared arrays, garbage for locals). Shared float arrays need a *float literal* in `array(n, 0.0)`; otherwise the array is `int`. | Old translations such as `array(1000, 1)` summed zeros. Arrays are now filled explicitly. |
| 3 | Loop temporaries are `alloca`'d **inside loop bodies** (~85 bytes per iteration), so stack grows with iteration count. A single-thread `while` of ≈90 000 iterations, 1000 `create_threads`/`parallel for` calls in a loop, or the polling loops of `DRB190` (1000 packages) overflow the 8 MB stack → SIGSEGV. | `float-pi-cyclic-no` (50 000 steps), `counter-mutex*-no` (100 rounds), `DRB037/038/062` (100 rows), `DRB190` (100 packages). **Worth fixing in the compiler.** |
| 4 | Reassigning a thread-array variable (`threads := create_threads(...)` a second time) fails with a type error. | Distinct variable names per region (`isum-nolock-yes`). |
| 5 | `thread`, `by` are reserved words; `enqueue`/`dequeue` clash with built-ins. | Renamed (`queue_enqueue`, …, `tid`). |
| 6 | `print "text"` (and any string variable) prints the **quotes**; only backtick templates print bare text. | Output-only; `.github/copilot-instructions.md` says plain strings print plainly. |
| 7 | `README.md` of SCTBench and several file headers said "Alecci has no assert"; `assert` is implemented (failing assert → `SIGABRT`, exit 134). | README and headers corrected. |
| 8 | TSan stops reporting the chunk-boundary race of `DRB031/032` for matrices ≥ ~400×400 (100×100 and 200×200 report it). | Kept 100×100 (C is 1000×1000). |

## 5. Benchmarks whose label and the C source disagree

Translated faithfully, these keep the C semantics **or** the dataset label; the conflict is
documented in each file. They are for you to decide on – I did not change any `expected_issues`.

| File | Label | What the C does | What the `.ale` does |
|---|---|---|---|
| `bucket-sum-mutex-no`, `histogram-rand-no`, `ticket-counter-no`, `two-thread-flag-cond-no` (POSIX/with_datarace) | `data_race` | every shared access is lock-protected | race-free translation (pre-existing MISS) |
| `float-pi-inline-no` (intel_pi) | none | `omp parallel` + plain `for`: all threads run the loop on shared `i`, `x` → racy | modelled as a work-shared `parallel for` (race-free) |
| `array-max-critical2-no`, `parallel-max-atomic-no` (omp12) | none | `max < a[i]` tested **outside** the critical section (TOCTOU) | test moved inside the lock/atomic |
| `histogramaSerie_-_main` | none | `histo[IMA[i][j]]++` unprotected (the `histop` copy is unused) | mutex-protected increment |
| `din_phil5/6/7_sat-yes` | bug | `++phil` is inside `__ESBMC_atomic_begin/end` (protected); bug is the `assert(0)` | `phil` protected + assert (now only lock-order inversion is reported; was data race + inversion). `din_phil7_sat` has 3 `begin`s and 1 `end` in C → modelled as balanced sections |
| `float-pi-noreduction-yes` | data_race | `sum` *does* have `reduction`; the races are on shared `id/ini/fin/x/i` | race kept on those variables (yaml comment corrected) |
| `lock-order-no`, `lock-order-rand-no` | none | ABBA with `sleep(1)` between the locks | now deadlocks like the C (before, no sleep so it usually finished) |
| `wait-all-cond-yes` | data_race | threads never joined | TSan reports thread leak, not data race (pre-existing) |
| `DRB140-reduction-barrier-orig-yes` | data_race | master write vs reduction | TSan misses it (pre-existing MISS, same in the faithful translation) |


## 6. Regression against the existing result CSVs

`concurrency_validation/test_runner.py` (system `python3`, which has PyYAML; the repo `.venv` does not)
was run on `labeled_benchmarks/` (212 tests, 20 runs where `max_runs` is set) and on `SCTBench/`
(48 tests), and compared with `results/labeled_results.csv` / `results/sct_results.csv`.

Despite ~180 rewritten files, **only 8 statuses/detections changed (2 of them in ClassExamples files I did not edit)** (the CSVs in `results/` were *not* overwritten;
the new CSVs are in the session scratchpad):

| Test | Expected | Before | After | Why |
|---|---|---|---|---|
| `count-threshold-cond-yes` | data_race | PASS (race) | **MISS** | The old translation unlocked inside the `while` so `count < 15` was read unlocked many times. The C source keeps the mutex held across iterations; its only unlocked read is the first one, which is ordered before the incrementers in practice. Faithful translation ⇒ 0/20 detections. |
| `lock-order-no`, `lock-order-rand-no` | none | UNEXPECTED (TSan lock-order inversion) | PASS (timeout, nothing reported) | With the C's `sleep(1)` between the two locks the program really deadlocks, and TSan only reports an inversion when the second lock is *acquired*, so it stays silent. Remove the `sleep(...)` calls to get the old behaviour. |
| `din_phil5/6/7_sat-yes` | bug | PASS [data_race+deadlock] | PASS [deadlock] | `++phil` is inside the ESBMC atomic section in the C source; the old translation made it racy. Now also aborts on `assert(0)`. |
| `lazy01-no` | bug | MISS | PASS (assert abort) | `thread3`'s `assert(0)` restored. |
| `twostage_100-no` | bug | MISS | PASS [data_race] | Real race on `data1Value` read under the wrong lock in `funcA`; detected in this run (TSan is non-deterministic). |
| `build_h2o/0005`, `0008` (ClassExamples, **not edited**) | – | – | flipped | `mutex_destruction` is reported non-deterministically; unrelated to this review. |

Side effects: `float-pi-padded-no` and `float-pi-syncintegrate-no` stopped crashing (the old versions overflowed the stack),
`readwrite-cond-yes` no longer times out (8.7 s → 1.8 s), `lock-order-no` now times out (see above).
Overall: PASS 198 → 199, MISS 10 → 12, UNEXPECTED 3 → 0 (labeled); SCTBench PASS 35 → 37, MISS 7 → 5.

## 8. Things I did not touch / suggested follow-ups

* `expected_issues` in every yaml (only comments were edited, plus `stdin_file:` for the four new input files).
* `results/*.csv`, `*.tex` and the plots – they are now stale for the rows listed in section 6.
* `concurrency_validation/muestreo_revision/` contains copies of 11 benchmarks from the review sample
  (`shared-a-pfor-yes`, `fetch-increment-nolock-yes`, `isum-nolock-yes`, `counter-mutex-no`,
  `DRB010/020/169`, `wronglock-yes`, `din_phil3_sat-yes`, `din_phil6_unsat-no`, `circular-buffer-cond-no`);
  those copies are now outdated versions.
* Compiler issues from section 4 (silent 10-element default for non-literal shared array sizes, ignored
  `array()` initial value, per-iteration `alloca` stack growth, quoted string prints) would be worth
  fixing or documenting in `.github/copilot-instructions.md`.
* `README.md` of `SCTBench` was updated where it claimed there is no `assert`, and for the `din_phil*_sat`
  description.

## 7. Per-file changes

Legend: **U** = rewritten/edited, **OK** = already a complete translation, left unchanged. "C source" is the file under `alecci-tests`.


### DeepRace/OMP_Critical/with_datarace

| File | C source | Status | Change |
|---|---|---|---|
| `array-max-nolock2-yes` | a_-_main.c | U | added max=-1 init, rand fill, final print "is max" |
| `array-total-nolock-yes` | array_total_-_main.c | U | was single-region 4-thread toy; now j=1..16 thread loop, per-thread my_sum, total reset/print; size 20M->20k; timing dropped; array fill explicit (array() init ignored) |
| `count-incdec-nolock-yes` | hw8_p1a_-_main.c | U | added 100-test outer loop, count reset, result print (1 per line) |
| `fetch-increment-nolock-yes` | for_dynamic_-_main.c | U | A[20] (was 100), added nthreads print, master, i>=20 break semantic; work(i) modelled i*2 |
| `fib-array-race-yes` | fibomp_-_main.c | U | was parallel for (no race semantics of C); now 2 threads each run whole loop, scan n (new stdin file fib-array-race-yes.txt + yaml stdin_file), fib[100], prints |
| `firstprivate-sum-nolock-yes` | datasharing_-_main.c | U | added master nt, Success/Fail check |
| `float-pi-nolock-yes` | exercise_3 | U | shared step/num_steps, x=(i+0.5)*step cyclic, pi print; steps 10M->100k |
| `float-pi-worksharing-nolock-yes` | Calculo_PI.. | U | was parallel-for per-iteration soma (wrong); now per-thread soma over block of omp for + pi+=soma*step; 1M->100k; NUM_THREADS=4 assumed |
| `float-pi2-nolock-yes` | intepar2 | U | shared step, i=id; i+=nthrds, print pi |
| `for-sum-nolock-yes` | for_ | U | added print of sum (timing dropped) |
| `global-max-nolock-yes` | global_max | U | rewritten: 10-element data, per-thread localMax/tid, omp for, prints, globalMax compare outside lock |
| `hitung-nolock-yes` | hitung | U | 10 threads (was 4 over 100), prints |
| `kmeans-race-yes` | eo | U | dis1/dis2 int (C), cV init, loop cond as in C via dist(), per-iter and FINAL prints |
| `matrix-mul-k-race-yes` | 104 | U | i/6 -> i#6 (true division bug), added a/b/c printing, parallel-for fills, shared tid, private sum |
| `matrix-sum-nolock-yes` | dynamic2 | U | 13x13 float matrix (was int i+j), serial sum, trace prints, a[j][i] column access |
| `monte-carlo-nolock-yes` | 5.40 | U | real Monte Carlo (rand points, scan amountOfPoints, pi print) new stdin file monte-carlo-nolock-yes.txt |
| `parallel-increment-yes` | 05_omp_crit | OK | OK unchanged |
| `shared-a-pfor-yes` | exemple_OMP_22 | – | your reference example (already fixed before this review) |
| `shared-i-nolock-yes` | hola | U | prints in worker and final prints |
| `shared-increment-nolock-yes` | 05_omp_crit | U | was parallel for 100 iterations; now 4 threads x=x+1 as in C |
| `shared-local-accumulate-yes` | datasharing | U | added master nt and Success/Fail |
| `shared-threadnum-nolock-yes` | conditional | U | 2 threads, n=20, i=1..n, prints |
| `sum-private-nolock-yes` | mapexpCritical | U | 3 phases (x fill, z=exp(x^2) via pow, per-thread private_sum), N 1M->10k |
| `parallel-max-nolock-yes` | omp12 | U | faithful omp12 with the `omp critical` removed (this file is the race-injected variant of the `without_datarace` benchmark): 300 random elements, `% 7` filter, `base_max`, prints; yaml comment fixed |

### DeepRace/OMP_Critical/without_datarace

| File | C source | Status | Change |
|---|---|---|---|
| `array-max-critical2-no` | omp12 | U | 300 rand elems, mod 7, base_max, prints; check+update both under lock (C checks outside critical => would race; label none) |
| `combined-array-count-no` | simple_combined_pfor | U | added 100 a[i] prints + count print |
| `critical-id-no` | 2.hello | U | added the Hello/world print inside the lock |
| `determinant-no` | determ | U | random n=2 matrix + print, critical around [j,k] print and product, Thread prints, Suma posi |
| `float-pi-cyclic-no` | 5_pi_smp_critical | U | 1 thread (omp_set_num_threads(1)), shared step, pi print; 50000 steps (stack-growth bug) |
| `float-pi-inline-no` | intel_pi | U | kept parallel-for adaptation (C `omp parallel` + plain for would race on shared i,x) ; pi print, steps 1e9->1e5. LABEL CONFLICT noted |
| `float-pi-padded-no` | helloWorldParallel_Atomic | U | added serial pass, 3.0 constant, per-thread Steps/NumThreads prints, two Pi prints; 200M->40k steps |
| `float-pi-partial-no` | pi1 | U | per-thread partial_sum over omp-for block (was per-iteration), h*sum, print; 1e9->1e5 |
| `float-pi-syncintegrate-no` | sync-integrate | U | shared step, thread0 sets actual_num_threads, prints; 1e7->1e5 |
| `global-max-mutex-no` | global_max | U | full rewrite as in with_datarace + critical restored |
| `hello-atomic-no` | helloworld | OK | OK unchanged |
| `fibonacci-critical-no` | fibo_-_main.c | OK | already a complete translation (stdin `n`, critical loop); unchanged |
| `histogramaSerie_-_main` | histogramaSerie | U | IMA 1000x1000->100x100 rand, matrix print, per-thread histop + critical merge, hmin/imin, B/C/SPM scan, prints |
| `min-max-avg-mutex-no` | lab2_openmp | U | 3 rand arrays (a,b,c=(a+b)/2), print arrays, avg, nthreads |
| `parallel-increment-atomic-no` | 05_omp_crit | OK | OK unchanged (fix variant with atomic + assert) |
| `parallel-max-atomic-no` | omp12 | U | 300 rand elements etc; atomic block around check+update; assert max = base_max |
| `pi-integral-mutex-no` | sync-integrate | U | was sum of ints; now full pi (duplicate of syncintegrate) |
| `product-mutex-no` | VarCompPrivModificado | U | per-thread id, prints inside lock |
| `reduction-mutex-no` | pi1 | U | was sum of ints; now full pi1 (duplicate of float-pi-partial-no) |
| `shared-local-accumulate-no` | datasharing | U | added master nt + Success/Fail (atomic + assert kept) |

### DeepRace/OMP_Private/with_datarace

| File | C source | Status | Change |
|---|---|---|---|
| `float-pi-noreduction-yes` | PiReduction | U | scan n (new stdin file), 6 threads (NH), shared id/ini/fin/x/i (the real races), sum = reduction (mutex combine), prints; yaml comment corrected |
| `isum-nolock-yes` | data_range2 | U | was 1 block; now all 10 blocks (race in block 1; firstprivate/lastprivate; 7 reductions; ordered prints) |
| `matrix-add-shared-yes` | ex6 | U | A=i+j, B=2i+2j (was i / 2i flat), Nid, shared i/j, verification + True/False print |
| `shared-myid-yes` | 3 C files | U | was 1 toy; now all three programs (hello-single, for-work-sharing cyclic chunks, single_master w/ barrier & 3 regions) |
| `shared-tid-pfor-yes` | for-work-sharing | U | cyclic chunk-2 schedule, tid print, n=10 (was 100-iteration tid write) |
| `shared-tmp-yes` | outter | U | was trivial temp write; now prefix-sum on shared s_seq/sequence/aux; p 8..14 -> 3..9; pow->shift; prints |
| `shared-x-nolock2-yes` | lec4 | U | 4 threads (was 3), x/y/z init, Hello print |
| `shared-x-pfor-yes` | array_sum | U | j=1..10 outer loop, 5 parallel-for loops (was 1), a/c arrays, 10M->2000; timings dropped |
| `shared-x-yes` | lec4 | U | was parallel for x:=thread_number; now create_threads(4) + Hello (same translation as shared-x-nolock2-yes) |

### DeepRace/OMP_Private/without_datarace

| File | C source | Status | Change |
|---|---|---|---|
| `18_for_wait_-_main` | 18_for_wait | OK | OK (scaled 20000->100 already documented; two parallel-for equal to two omp-for) |
| `array-add-pfor-no` | for-loop | U | float arrays a=b=i*1.0 (was ints), chunk var |
| `array-fill-tid-no` | fill | U | 32 elements (was 100), float array, print loop |
| `array-negate-no` | looptest_1 | U | '#' print per iteration, x/y print loop, "All Done" |
| `barrier-y-z-no` | barrier1 | U | block (not cyclic) omp for, print of x |
| `digit-square-pow-no` | 9.ved | U | prints (Number, digits, per-thread lines, summation), atomic tsum (was mutex), int division via #, prompt |
| `local-max-per-thread-no` | examQuestion | U | array[0..4] values + zero rest, local_min too, `initialized` private flag, global reduction, 2 prints |
| `local-myid-no` | 1.1-hello | U | hello print (was result array) |
| `local-myid-pfor-no` | hello_for | U | 16-iteration print |
| `local-tmp-no` | outter | U | private-version of prefix-sum program (was trivial tmp) |
| `local-vars-no` | for-loop | U | same as array-add-pfor-no (float arrays) |
| `matrix2loops_-_main` | matrix2loops | U | dim via scan (new stdin file + yaml stdin_file), rand fill, threads with barriers like the omp for, messages; dim limit 10000->100 |
| `matrix_part1_-_main` | matrix_part1 | U | manual id/part/offset partitioning (thread 0 idle, last takes remainder), scaled A[20][10]..., print loop |
| `two-pfor-fill-no` | fig4.12 | U | single/loop prints added |

### DeepRace/POSIX_Lock_Primitives/with_datarace

| File | C source | Status | Change |
|---|---|---|---|
| `bucket-sum-mutex-no` | dana.c | U | per-bucket mutex array, rand numbers, prints (was single mutex, deterministic x). NOTE yaml expects data_race but C is race-free (dataset mislabel, already noted in file) |
| `canibais-cond-yes` | canibais | U | porcao mutex, prints, `if` as in C, cook prints, sleeps ratio 1:5; bounded meals kept (C loops forever) |
| `count-threshold-cond-yes` | threads_cond_mutex | U | prints, thread ids 1,2,3, C's lock/unlock structure in watch_count |
| `counter-nolock-yes` | muxtex_anpham.c | U | was 4 threads x 1000 increments (not from C); now 2-thread functionC without mutex + Hello/Exit prints; yaml comment |
| `flag-nolock-yes` | TwoThreadLoop.c | U | was 2 threads writing flag; now the A/B printing loops with lock+cond removed; yaml comment |
| `global-sum-nolock-yes` | 02_printf_g_thread.c | U | was 4-thread partial sums (unrelated); now g_num++/-- threads without mutex + prints; yaml |
| `histogram-nolock-yes` | assiOS.c | U | was i mod 5 counts; now 10000 random inputs, 5 stride threads, no mutex, prints; yaml |
| `histogram-rand-no` | assiOS.c | U | added input / Thread Started / Count / Total prints. NOTE dataset label data_race vs race-free translation |
| `readwrite-cond-yes` | zuoye3.c | U | `if` instead of `while` for cond checks (as C), 20ms pause instead of 500ms, print format as C |
| `ticket-counter-no` | 11_mutex.c | U | two handlers (handle1/2) with thread ids, usleep(500) as 500us, C-style unlock structure, "sale tickets" print; removed invented "no end" prints. NOTE dataset label data_race vs race-free translation |
| `two-thread-flag-cond-no` | TwoThreadLoop.c | U | A/B rows printed as whole strings (was per-char prints with print("A")). NOTE dataset label data_race vs race-free translation |
| `unisex-bathroom-cond-yes` | universidad.c | U | all prints; sleeps scaled /5; sleep(5) + 8 late-arrival random threads (were missing); sale/entrar procedures |
| `wait-all-cond-yes` | wait4mult.c | U | thread start/finish/exit prints, main prints; removed time print |

### DeepRace/POSIX_Lock_Primitives/without_datarace

| File | C source | Status | Change |
|---|---|---|---|
| `array-sum-mutex-no` | 010_mutex_array_sum | U | 5 threads x 100 elems (was 4x125), special values at 203/440, local max/min, 3 mutexes, 3 prints |
| `bounded-buffer-cond-no` | 05bounded | U | message chars as ASCII codes, producer/consumer waiting/executing/exiting prints, consumer started first |
| `circular-buffer-cond-no` | ThreadSynCondition | U | sentinel -1 (was 999), Get as function, Producer/Consumer prints in C format |
| `count-threshold-4t-cond-no` | thread_with_conditions | U | all prints, watcher locks before the loop (C structure), final print |
| `count-threshold-cond-no` | 06_thread_cond_var | U | all prints, update inside loop as C, thread ids; final print |
| `count-threshold-outer-cond-yes` | 11-14UseConditionVariable | U | prints; main joins inc threads, signals, joins watcher |
| `counter-mutex-no` | withmutex.c | U | outer round loop (1000 -> 100 because of stack growth), reset counter each round; was a single 4x1000 run |
| `counter-mutex3-no` | withmutex.c | U | same (was 4 x 100 single run) |
| `counter-mutex2-no` | W9mutex1.c | U | added Counter value print |
| `counter-mutex4-no` | muxtex_anpham.c | U | Hello/Exit + Counter value prints |
| `flag-signal-cond-yes` | x.c | U | puts() messages for all 3 threads and "end test"; waiter threads as in C (threadfn1/3). (a single manual run also showed a TSan report about the main thread destroying the mutex/condvar while a waiter is still blocked; the regression status did not change) |
| `global-sum-mutex-no` | 02_printf_g_thread.c | U | was unrelated 4-thread partial sums (no C source identified); now mutex version of g_num++/-- threads with prints |
| `lock-order-no` | 01-trava_dupla | U | sleep between locks (100ms), prints, 5 iterations, unlock order as C, "Fim de programa!" (program now deadlocks like the C) |
| `lock-order-rand-no` | 04-random_sleep | U | same as above plus random pre-sleep |
| `ping-pong-cond-no` | ping_pong.c | U | READY enum (was ints 0/1), "ping(n) -> " format, thread structure as C |
| `scatter-add-mutex-no` | tp5_2.c | U | real 10x4 matrix and vector literals (was i+1 values), SALUT print, result print |

### DataRaceBench

| File | C source | Status | Change |
|---|---|---|---|
| `DRB001` | (see header) | U | len constant, printf a[500] |
| `DRB002` | (see header) | U | len 1000 (was 500) + argv override clamped to literal array capacity |
| `DRB003` | (see header) | U | double 0.5 init (was int 1), printf a[10][10] |
| `DRB004` | (see header) | U | len 20 (was 10) float 0.5, argv override |
| `DRB016` | (see header) | U | printf x |
| `DRB017` | (see header) | U | len 100 (was 200), argv override, printf |
| `DRB018` | (see header) | U | printf output[500] |
| `DRB019` | (see header) | U | inLen 1000 (was 200), argv override, printf |
| `DRB029` | (see header) | U | printf a[50] |
| `DRB030` | (see header) | U | len 100 (was 200) + argv |
| `DRB031` | (see header) | U | b doubles 0.5 (was int 1), printf; size 100x100 kept (TSan stops reporting from ~400x400, C is 1000x1000) |
| `DRB032` | (see header) | U | float 0.5, argv; size 100 |
| `DRB033` | (see header) | U | printf a[1001] |
| `DRB034` | (see header) | U | len 2000 (was 4000) with len/2 bound + argv |
| `DRB035` | (see header) | U | printf a[50] |
| `DRB036` | (see header) | U | len 100 (was 500) + argv |
| `DRB037` | (see header) | U | global double zeros (was int i*100+j), print b[50][50]; size 100 (C 1000: each parallel-for call keeps thread array on stack) |
| `DRB038` | (see header) | U | float, argv (len default 100 vs C 1000) |
| `DRB039` | (see header) | U | removed invented a[i]=i init (C leaves uninitialised), printf a[500] |
| `DRB040` | (see header) | U | len 1000 (was 500) + argv, no invented init |
| `DRB075` | (see header) | U | was parallel for 4 iterations w/ dummy copy; now 4 threads, thread0 writes, others print numThreads |
| `DRB169` | (see header) | U | double arrays, N const, final r1 print loop |
| `DRB009` | (see header) | U | printf x |
| `DRB010` | (see header) | U | len from argv (default 10000), printf |
| `DRB020` | (see header) | U | file was named orig but translates the _var C: len 100 + argv, a[i]=i init |
| `DRB021` | (see header) | U | was 1D int array; now float u[100][100]=0.5, temp private, float sum, printf |
| `DRB022` | (see header) | U | float 0.5 values, temp private, argv, printf (was int 1s) |
| `DRB023` | (see header) | U | sections as 2 threads (not a 2-thread parallel for), printf i |
| `DRB028` | (see header) | U | printf a[50] |
| `DRB111` | (see header) | U | a=i/2.0, b=i/3.0, c=i/7.0 doubles (were ints), printf c[50] |
| `DRB191` | (see header) | U | separate critical names A/B, prints "Produced!/Consumed!", r busy loop; loops bounded to 100 (C is while(1)) |
| `DRB011` | (see header) | U | init block, printf numNodes2 |
| `DRB012` | (see header) | U | len 100 (was 50) + argv |
| `DRB140` | (see header) | U | was parallel for with mutex'd a += i (not the C); now master a=0, omp-for-reduction (static blocks, mutex combine), barrier, single print "Sum is". Still MISS in TSan (as baseline) |
| `DRB045/046/047` | (see header) | OK | OK unchanged (DRB047: char array modelled as int array) |
| `DRB053` | (see header) | U | double zero-initialised matrix (was int array) |
| `DRB054` | (see header) | U | double b[i][j]=i*j |
| `DRB077` | (see header) | U | parallel region of 4 threads + single, printf count (was parallel-for stand-in) |
| `DRB103` | (see header) | U | master with printf "Number of Threads requested" |
| `DRB113` | (see header) | OK | OK unchanged |
| `DRB048` | (see header) | U | shared const n=100, g=7 (was literal 7 hidden) |
| `DRB060` | (see header) | U | N=100 (was 20), doubles, C's exact index pattern c[i][j] += a[i][k]*b[k][j] (ale had c[i][k] += a[i][j]*b[j][k]), no invented init |
| `DRB061` | (see header) | U | removed invented a/v init (C arrays are zero-initialised globals) |
| `DRB062` | (see header) | U | removed invented init; N stays 100 (C 1000) |
| `DRB063` | (see header) | U | double zero b, removed invented init |
| `DRB064` | (see header) | U | double zero b, removed invented init |
| `DRB093` | (see header) | U | collapse(2) as single flattened parallel for |
| `DRB094` | (see header) | U | added "test i= j=" prints (ordered/depend ordering has no equivalent: documented) |
| `DRB121` | (see header) | U | was two mutex'd parallel fors; now team of 4 with omp-for reductions on sum1/sum2, barriers, reduction(+:var) -> 20*res, error print |
| `DRB170` | (see header) | U | double array 6.0/m + 4 (was int) |
| `DRB108` | (see header) | U | parallel region + atomic do (was parallel-for + mutex), printf a |
| `DRB120` | (see header) | U | real two `single` (first-arrival flag) with barriers on 4 threads (was thread 0 / thread 1), error check |
| `DRB141` | (see header) | U | master a=0 + explicit barrier + omp-for reduction + single print (was parallel-for) |
| `DRB172` | (see header) | U | double q/qq, omp for + critical + barrier + single on 4 threads, final print loop |
| `DRB190` | (see header) | U | separate producer/consumer with firstprivate packages (C: 1000, scaled to 100 because of stack growth), r burn loops 1000/1500, prints |
| `DRB057` | (see header) | U | MSIZE 200 (was 20), doubles, dx/dy/xx/yy/f formula (was zeros) |
| `DRB058` | (see header) | U | initialize() with real f, ax/ay/b computed from dx/dy, region with copy loop, barrier, stencil loop with per-thread reduction, prints; sizes 20/10 kept (C 200/1000) |
| `DRB065` | (see header) | U | real pi integral (was integer sum of i), reduction via per-thread partials; steps 2e8 -> 1e5 |

### SCTBench

| File | C source | Status | Change |
|---|---|---|---|
| `race01-yes, dpor_example3-yes, simple_mutex-no` | (see header) | OK | OK unchanged |
| `micro_unprotected_2/3/10-yes` | (see header) | U | added the final assert(0<x) / if(x<=0) assert(0) of each thread (translations had no asserts) |
| `reorder_3/4/5/10/20-yes` | (see header) | U | checkThread now tests (a,b) in {(0,0),(1,-1)} with "Bug found!" + assert (was two dead reads); iSet/iCheck argv override |
| `wronglock-yes, wronglock_3-yes` | (see header) | U | funcA's lost-update check + assert("Bug Found!"); iNum1/iNum2 argv override |
| `din_phil2/3/4_sat-yes` | (see header) | U | added `++phil; if (phil==N) assert(0)` (assert was omitted: "Alecci has no assert" is outdated), unprotected as in C |
| `din_phil5/6_sat-yes` | (see header) | U | second ESBMC atomic pair around ++phil + assert => phil is PROTECTED in the C (ale had it unprotected). yaml comments updated |
| `din_phil7_sat-yes` | (see header) | U | ++phil inside atomic (C has 3 begins / 1 end: modelled as balanced sections), assert |
| `din_phil2..7_unsat-no` | (see header) | U | names/structure as C (x[], thread1, trd_id), header; semantic unchanged |
| `account-no` | account_ok.c | U | x=1,y=2,z=4,balance=x (was 100/10/20) + assert balance==(x+y)-z (was dead reads) |
| `account_bad-no` | account_bad.c | OK | OK unchanged |
| `arithmetic_prog-no` | arithmetic_prog_ok.c | U | printf produce/total/consume, post-loop total+=j & flag, final assert total==N(N+1)/2 |
| `arithmetic_prog_bad-no` | arithmetic_prog_bad.c | U | added the printf calls |
| `carter01_bad-no, deadlock01_bad-no` | (see header) | OK | OK unchanged |
| `circular-buffer-flag-no` | circular_buffer_bad.c | U | insertLogElement/removeLogElement as functions with the missing asserts (first>=0, next<buffer_size), assert(removeLogElement()==i); removed invented print lines/last_removed |
| `circular-buffer-flag-ok-no` | circular_buffer_ok.c | U | assert(i==insertLogElement(i)) added, `value` as in C, assert(removeLogElement()==value); removed invented prints |
| `dpor_example1-no` | dpor-example1.c | U | cas() as a real function (was inlined, claimed no by-ref), thread_routine/tids as C |
| `lazy01-no` | lazy01_bad.c | U | thread3 `if (data >= 3) assert(0)` (was dead read) |
| `phase01-no, phase01_bad-no` | (see header) | OK | OK unchanged |
| `queue-flag-no` | queue_bad.c | U | init/empty/full/enqueue/dequeue functions (renamed queue_*; enqueue/dequeue are builtins), "queue is empty/full" prints, asserts (!enqueue, !empty, empty()==EMPTY), flag init in main; removed invented prints |
| `stack-no` | stack_bad.c | U | push/pop with overflow/underflow prints and asserts (was raw array ops, no asserts) |
| `stateful01-no` | stateful01_ok.c | U | added the unused mutex mb |
| `sync01-no` | sync01_ok.c | U | removed the 2-iteration loops (C threads do a single pass), added "consume ...." print |
| `sync01_inspect-no` | sync01.c | U | "producing ...."/"consume ...." prints |
| `sync01_bad-no` | (see header) | OK | OK unchanged |
| `sync02-no` | sync02_ok.c | U | produce/consume prints |
| `sync02_bad-no, token_ring_bad-no` | (see header) | OK | OK unchanged |
| `twostage-no` | twostage_bad.c | U | iTThreads=1,iRThreads=1 (was 1 + 2), funcB early return on data1Value==0, t2 != t1+1 check + assert, argv |
| `twostage_100-no` | twostage_100_bad.c | U | same (99 + 1) |
