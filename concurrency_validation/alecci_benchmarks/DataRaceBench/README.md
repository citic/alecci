# DataRaceBench — Alecci Translation Summary

## Overview

DataRaceBench (DRB) is a structured benchmark suite for evaluating data race detection tools.
This directory contains Alecci translations of a subset of the C benchmarks.

**Source:** [Github](https://github.com/llnl/dataracebench/tree/master)   
**Total C/C++ benchmarks in DRB:** 183 (plus 168 Fortran, not translated)  
**Translated to Alecci:** 55 benchmarks (30 — no race, 25 — race)

---

## Categories

DRB benchmarks are labeled by race category:

| Label | Description |
|-------|-------------|
| Y1 | Loop-carried dependency races (anti-dep, true-dep, output-dep) |
| Y2 | Missing private/reduction variable |
| Y3 | Missing synchronization (critical section, barrier, lock) |
| Y4 | SIMD vector races |
| Y5 | GPU/accelerator races |
| Y6 | Pointer-aliasing / dynamic memory races |
| Y7 | Indirect array access (pointer-indexed) races |
| N1 | Embarrassingly parallel (DOALL) — no race |
| N2 | Correct private/reduction variable — no race |
| N3 | Proper synchronization (barrier, critical, lock) — no race |
| N4 | SIMD correct |
| N5 | GPU/accelerator correct |
| N6 | Pointer/aliasing analysis correct |
| N7 | Complex numerical kernels — no race |

---

## Translated Benchmarks

### Y1 — Loop-Carried Dependency Races (22 of 31 translated)

| Alecci file | DRB source | Pattern |
|---|---|---|
| `DRB001-antidep1-orig-yes.ale` | DRB001-antidep1-orig-yes.c | `a[i] = a[i-1]+1` anti-dependence |
| `DRB002-antidep1-var-yes.ale` | DRB002-antidep1-var-yes.c | Same with different bounds |
| `DRB003-antidep2-orig-yes.ale` | DRB003-antidep2-orig-yes.c | `a[i] = a[i+1]+1` anti-dependence |
| `DRB004-antidep2-var-yes.ale` | DRB004-antidep2-var-yes.c | Same with different bounds |
| `DRB016-outputdep-orig-yes.ale` | DRB016-outputdep-orig-yes.c | `a[i%2] = ...` output dependence |
| `DRB017-outputdep-var-yes.ale` | DRB017-outputdep-var-yes.c | Output dependence variant |
| `DRB018-plusplus-orig-yes.ale` | DRB018-plusplus-orig-yes.c | `a[i]++` shared scalar |
| `DRB019-plusplus-var-yes.ale` | DRB019-plusplus-var-yes.c | Shared scalar variant |
| `DRB029-truedep1-orig-yes.ale` | DRB029-truedep1-orig-yes.c | `a[i] = a[i-1]` true dependence |
| `DRB030-truedep1-var-yes.ale` | DRB030-truedep1-var-yes.c | True dependence variant |
| `DRB031-truedepfirstdimension-orig-yes.ale` | DRB031-truedepfirstdimension-orig-yes.c | True dep, 1D linearised |
| `DRB032-truedepfirstdimension-var-yes.ale` | DRB032-truedepfirstdimension-var-yes.c | Variant |
| `DRB033-truedeplinear-orig-yes.ale` | DRB033-truedeplinear-orig-yes.c | Linear true dependence |
| `DRB034-truedeplinear-var-yes.ale` | DRB034-truedeplinear-var-yes.c | Variant |
| `DRB035-truedepscalar-orig-yes.ale` | DRB035-truedepscalar-orig-yes.c | Scalar true dependence |
| `DRB036-truedepscalar-var-yes.ale` | DRB036-truedepscalar-var-yes.c | Variant |
| `DRB037-truedepseconddimension-orig-yes.ale` | DRB037-truedepseconddimension-orig-yes.c | Second-dimension dep (linearised) |
| `DRB038-truedepseconddimension-var-yes.ale` | DRB038-truedepseconddimension-var-yes.c | Variant |
| `DRB039-truedepsingleelement-orig-yes.ale` | DRB039-truedepsingleelement-orig-yes.c | Single shared element write |
| `DRB040-truedepsingleelement-var-yes.ale` | DRB040-truedepsingleelement-var-yes.c | Variant |
| `DRB075-getthreadnum-orig-yes.ale` | DRB075-getthreadnum-orig-yes.c | Shared variable written with thread ID |
| `DRB169-missingsyncwrite-orig-yes.ale` | DRB169-missingsyncwrite-orig-yes.c | Unprotected write then read |

### Y2 — Missing Private/Reduction Variable (8 of 19 translated)

| Alecci file | DRB source | Pattern |
|---|---|---|
| `DRB009-lastprivatemissing-orig-yes.ale` | DRB009-lastprivatemissing-orig-yes.c | Last-value carry-out without private |
| `DRB010-lastprivatemissing-var-yes.ale` | DRB010-lastprivatemissing-var-yes.c | Variant |
| `DRB020-privatemissing-orig-yes.ale` | DRB020-privatemissing-orig-yes.c | Loop var shared instead of private |
| `DRB021-reductionmissing-orig-yes.ale` | DRB021-privatemissing-var-yes.c | Private var missing, variant |
| `DRB022-reductionmissing-var-yes.ale` | DRB022-reductionmissing-orig-yes.c | Reduction without reduction clause |
| `DRB023-reductionmissing-var-yes.ale` | DRB023-reductionmissing-var-yes.c | Reduction variant |
| `DRB028-privatemissing-orig-yes.ale` | DRB028-taskdependmissing-orig-yes.c | Missing private (adapted from task) |
| `DRB111-linearmissing-orig-yes.ale` | DRB111-linearmissing-orig-yes.c | Linear clause missing, shared pointer |

### Y3 — Missing Synchronization (3 of 22 translated)

| Alecci file | DRB source | Pattern |
|---|---|---|
| `DRB011-minusminus-orig-yes.ale` | DRB011-minusminus-orig-yes.c | `sum--` without lock |
| `DRB012-minusminus-var-yes.ale` | DRB012-minusminus-var-yes.c | Variant |
| `DRB140-reduction-barrier-orig-yes.ale` | DRB140-reduction-barrier-orig-yes.c | Missing barrier before reduction |

### N1 — Embarrassingly Parallel (8 of 28 translated)

| Alecci file | DRB source | Pattern |
|---|---|---|
| `DRB045-doall1-orig-no.ale` | DRB045-doall1-orig-no.c | Independent `a[i] = b[i]+1` |
| `DRB046-doall2-orig-no.ale` | DRB046-doall2-orig-no.c | Independent with two arrays |
| `DRB047-doallchar-orig-no.ale` | DRB047-doallchar-orig-no.c | Char array DOALL |
| `DRB053-inneronly1-orig-no.ale` | DRB053-inneronly1-orig-no.c | Outer loop serial, inner parallel |
| `DRB054-inneronly2-orig-no.ale` | DRB054-inneronly2-orig-no.c | Inner-only variant |
| `DRB077-single-orig-no.ale` | DRB077-single-orig-no.c | Single-thread initialisation, then parallel |
| `DRB103-master-orig-no.ale` | DRB103-master-orig-no.c | Master-thread initialisation, then parallel |
| `DRB113-default-orig-no.ale` | DRB113-default-orig-no.c | Default-clause parallel, no race |

### N2 — Correct Private/Reduction (8 of 23 translated)

| Alecci file | DRB source | Pattern |
|---|---|---|
| `DRB048-firstprivate-orig-no.ale` | DRB048-firstprivate-orig-no.c | First-private copy per thread |
| `DRB060-matrixmultiply-orig-no.ale` | DRB060-matrixmultiply-orig-no.c | Matrix multiply, local accumulator |
| `DRB063-outeronly1-orig-no.ale` | DRB063-outeronly1-orig-no.c | Outer-only parallel, inner serial |
| `DRB064-outeronly2-orig-no.ale` | DRB064-outeronly2-orig-no.c | Variant |
| `DRB093-doall2-collapse-orig-no.ale` | DRB093-doall2-collapse-orig-no.c | Collapsed loop DOALL |
| `DRB094-doall2-ordered-orig-no.ale` | DRB094-doall2-ordered-orig-no.c | Ordered reduction, no race |
| `DRB121-reduction-orig-no.ale` | DRB121-reduction-orig-no.c | Proper reduction with mutex |
| `DRB170-nestedloops-orig-no.ale` | DRB170-nestedloops-orig-no.c | Nested loops, no race |

### N3 — Proper Synchronization (4 of 21 translated)

| Alecci file | DRB source | Pattern |
|---|---|---|
| `DRB108-atomic-orig-no.ale` | DRB108-atomic-orig-no.c | Atomic update (mutex-protected) |
| `DRB120-barrier-orig-no.ale` | DRB120-barrier-orig-no.c | Barrier synchronisation |
| `DRB141-reduction-barrier-orig-no.ale` | DRB141-reduction-barrier-orig-no.c | Barrier before reduction read |
| `DRB172-critical2-orig-no.ale` | DRB172-critical2-orig-no.c | Critical section protecting shared update |

### N7 — Complex Numerical Kernels (2 of 7 translated)

| Alecci file | DRB source | Pattern |
|---|---|---|
| `DRB057-jacobiinitialize-orig-no.ale` | DRB057-jacobiinitialize-orig-no.c | Jacobi initialisation loop |
| `DRB065-pireduction-orig-no.ale` | DRB065-pireduction-orig-no.c | PI computation with reduction |

---

## Skipped Benchmarks

### Entire categories skipped

| Category | Count | Reason |
|---|---|---|
| Y4 | 1 | SIMD races — Alecci has no `simd` directive |
| Y5 | 1 | GPU races — Alecci has no `target`/`teams` |
| Y6 | 13 | Pointer/aliasing races — Alecci has no pointer type |
| Y7 | 4 | Indirect array access via pointer indexing — no pointer support |
| N4 | 3 | SIMD correct — same reason |
| N5 | 1 | GPU correct — same reason |
| N6 | 9 | Pointer-aliasing analysis — no pointer support |
| C++ (.cpp) | 4 | DRB086-087, DRB100-101 — Alecci is not C++ |
| Fortran (.f95) | 168 | Wrong language |

### Individual skips within translated categories

**Y1 — 9 of 31 skipped:**

| DRB source | Reason |
|---|---|
| DRB025-026 — simdtruedep | SIMD vector race, no `simd` directive in Alecci |
| DRB027 — targetparallelfor | GPU `target` directive |
| DRB114 — if-orig | Conditional parallel (`if` clause) — Alecci has no equivalent |
| DRB115 — forsimd | Combined `for simd` |
| DRB134, DRB136, DRB168 — taskdep5, mutexinoutset | OpenMP `task`+`depend` — no task model in Alecci |
| DRB178 — input-dependence | Complex wave-front dependence across two dimensions |

**Y2 — 11 of 19 skipped:**

| DRB source | Reason |
|---|---|
| DRB073 — doall2 race | Race via `threadprivate` variable — no `threadprivate` in Alecci |
| DRB074 — flush | Memory-model `flush` ordering — no Alecci equivalent |
| DRB084, DRB092 — threadprivatemissing | `threadprivate` clause |
| DRB086-087 | C++ (static data members) |
| DRB088-090 — dynamic/static storage | Dynamic and static local storage races |
| DRB095 — taskloop | OpenMP `taskloop` |
| DRB129 — mergeable-taskwait | OpenMP `task` + `taskwait` |
| DRB153 — missinglock2-gpu | GPU `target` region |

**Y3 — 19 of 22 skipped:**

| DRB source | Reason |
|---|---|
| DRB013 — nowait | `nowait` clause synchronisation |
| DRB024 — sections1 | `#pragma omp sections` — no sections in Alecci |
| DRB028, DRB106, DRB117, DRB131, DRB165 | OpenMP `task`/`taskwait`/`taskgroup` |
| DRB109 — orderedmissing | `ordered` clause — no Alecci equivalent |
| DRB116, DRB144, DRB148, DRB150, DRB151, DRB160, DRB161, DRB164 | GPU/SIMD target regions |
| DRB119 — nestlock | Nested locks — no Alecci nested lock |
| DRB142 — acquirerelease | Acquire-release memory model semantics |
| DRB183 — atomic3 | Atomic RMW without lock construct |

**N1 — 20 of 28 skipped:**

| DRB source | Reason |
|---|---|
| DRB070, DRB098, DRB137 | SIMD |
| DRB071, DRB099, DRB146, DRB147, DRB155, DRB158, DRB166-167 | GPU target |
| DRB100-101 | C++ |
| DRB125-128, DRB132 | `single`, `sections`, `task`/`threadprivate` |
| DRB139 | Complex worksharing + critical pattern |
| DRB171 | `threadprivate` |

**N2 — 15 of 23 skipped:**

| DRB source | Reason |
|---|---|
| DRB041-044 | 3mm / ADI polyhedral benchmarks — 2D arrays, very large |
| DRB059 — lastprivate | `lastprivate` clause semantics |
| DRB076 — flush | Memory-model `flush` |
| DRB085, DRB091 — threadprivate | `threadprivate` clause |
| DRB096 — taskloop collapse | OpenMP `taskloop` |
| DRB097 — target-teams | GPU |
| DRB102 — copyprivate | `copyprivate` clause |
| DRB112 — linear | OpenMP `linear` clause |
| DRB130 — mergeable-taskwait | `task`/`taskwait` |
| DRB145 — atomiccritical-gpu | GPU |

**N3 — 17 of 21 skipped:**

| DRB source | Reason |
|---|---|
| DRB069 — sectionslock1 | `sections` directive |
| DRB072, DRB078-079, DRB105, DRB107, DRB133, DRB135, DRB174, DRB176 | `task`/`taskwait`/`taskgroup` |
| DRB104 — nowait-barrier | Complex `nowait` + barrier interaction |
| DRB110 — ordered | `ordered` clause |
| DRB118 — nestlock | Nested locks |
| DRB143 — acquirerelease | Acquire-release |
| DRB152, DRB154, DRB159 | GPU |
| DRB182 — atomic3 | Atomic RMW |

**N7 — 5 of 7 skipped:**

| DRB source | Reason |
|---|---|
| DRB052 — indirectaccesssharebase | Indirect array access via shared pointer base |
| DRB055-056 — jacobi2d | 2D array stencil |
| DRB058 — jacobikernel | 2D Jacobi kernel |
| DRB061-062 — matrixvector | Matrix–vector product, 2D array |

---

## Summary

| Category | Total C | Translated | Skipped | Skip reason (primary) |
|---|---|---|---|---|
| Y1 | 31 | 22 | 9 | SIMD, GPU, task, complex dependence |
| Y2 | 19 | 8 | 11 | threadprivate, C++, dynamic storage, task |
| Y3 | 22 | 3 | 19 | sections, task, GPU, ordered, atomic |
| Y4 | 1 | 0 | 1 | SIMD |
| Y5 | 1 | 0 | 1 | GPU |
| Y6 | 13 | 0 | 13 | Pointer arithmetic |
| Y7 | 4 | 0 | 4 | Pointer indexing |
| N1 | 28 | 8 | 20 | SIMD, GPU, task, sections, C++ |
| N2 | 23 | 8 | 15 | 2D arrays, threadprivate, task, GPU |
| N3 | 21 | 4 | 17 | task, sections, GPU, ordered |
| N4 | 3 | 0 | 3 | SIMD |
| N5 | 1 | 0 | 1 | GPU |
| N6 | 9 | 0 | 9 | Pointer arithmetic |
| N7 | 7 | 2 | 5 | 2D arrays, pointer indexing |
| **Total** | **183** | **55** | **128** | |
