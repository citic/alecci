"""
Tier 1 Static Semaphore Token-Flow Deadlock Analyzer

Detects semaphore exhaustion deadlocks at compile time by computing the net
signal/wait delta of each procedure and flagging semaphores that can be
permanently drained with no recovery path.

See docs/deadlock_analysis.md for full algorithm specification.
"""

import sys
from typing import Dict, List, Optional, Set, Tuple

MAX_INLINE_DEPTH = 10


# ---------------------------------------------------------------------------
# Warning emission
# ---------------------------------------------------------------------------

def _warn(source_filename: str, message: str) -> None:
    print(f"\n{source_filename}: deadlock warning: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# AST traversal helpers
# ---------------------------------------------------------------------------

def _walk_nodes(body: list):
    """
    Yield every AST node reachable from a body (list of statement dicts),
    recursing into all sub-bodies unconditionally (Tier 1: may-execute).
    Yields the node itself before recursing into its children.
    """
    for node in body:
        if not isinstance(node, dict):
            continue
        yield node
        node_type = node.get('type')

        # Compound statement sub-bodies
        if node_type == 'if':
            yield from _walk_nodes(node.get('then_body', []))
            yield from _walk_nodes(node.get('else_body', []))
        elif node_type in ('while', 'for'):
            yield from _walk_nodes(node.get('body', []))
        elif node_type == 'case':
            for arm in node.get('arms', []):
                yield from _walk_nodes(arm.get('body', []))
            default_body = node.get('default_body') or []
            yield from _walk_nodes(default_body)
        elif node_type == 'block':
            yield from _walk_nodes(node.get('body', []))


def _walk_all_nodes(ast: dict):
    """Yield every AST node in the full program (all procedure bodies)."""
    for decl in ast.get('declarations', []):
        if not isinstance(decl, dict):
            continue
        yield decl
        node_type = decl.get('type')
        if node_type in ('procedure', 'function'):
            yield from _walk_nodes(decl.get('body', []))


def _arg0_name(node: dict) -> Optional[str]:
    """
    Return the name of the first argument of a function_call node,
    if that argument is a simple identifier (ID node). Returns None otherwise
    (e.g. array access, expression), so array-indexed semaphores are skipped.
    """
    args = node.get('arguments', [])
    if not args:
        return None
    first = args[0]
    if isinstance(first, dict) and first.get('type') == 'ID':
        return first.get('value')
    return None


def _thread_proc_name(node: dict) -> Optional[str]:
    """
    Extract the procedure-name argument from create_thread / create_threads calls.
    create_thread(proc, arg)  -> args[0]
    create_threads(n, proc)   -> args[1]
    """
    name = node.get('name')
    args = node.get('arguments', [])
    if name == 'create_thread' and args:
        first = args[0]
        if isinstance(first, dict) and first.get('type') == 'ID':
            return first.get('value')
    elif name == 'create_threads' and len(args) >= 2:
        second = args[1]
        if isinstance(second, dict) and second.get('type') == 'ID':
            return second.get('value')
    return None


# ---------------------------------------------------------------------------
# Phase A: Symbol collection
# ---------------------------------------------------------------------------

def _collect_symbols(ast: dict) -> Tuple[Dict[str, int], Dict[str, list], Set[str]]:
    """
    Returns:
        semaphores   : dict[name -> initial_count]  (shared semaphore declarations)
        procedures   : dict[name -> body]            (all procedures and functions)
        thread_entries: set[name]                    (procedures used as thread entries)
    """
    semaphores: Dict[str, int] = {}
    procedures: Dict[str, list] = {}
    thread_entries: Set[str] = {'main'}

    for decl in ast.get('declarations', []):
        if not isinstance(decl, dict):
            continue
        node_type = decl.get('type')
        if node_type in ('procedure', 'function'):
            procedures[decl['name']] = decl.get('body', [])

    # Semaphores can be declared at the top level OR inside procedure bodies
    # (Alecci allows 'shared mutable x := semaphore(N)' inside main()).
    # Walk every reachable node to collect them.
    for node in _walk_all_nodes(ast):
        if not isinstance(node, dict):
            continue
        if node.get('type') == 'declaration' and node.get('shared'):
            init = node.get('init', {})
            value = init.get('value', {}) if isinstance(init, dict) else {}
            if isinstance(value, dict) and value.get('name') == 'semaphore':
                raw_args = value.get('arguments', [])
                initial_count = 0
                if raw_args:
                    first_arg = raw_args[0]
                    if isinstance(first_arg, dict) and first_arg.get('type') == 'literal':
                        initial_count = int(first_arg.get('value', 0))
                semaphores[node['name']] = initial_count

    # Find thread entries anywhere in all bodies
    for node in _walk_all_nodes(ast):
        if isinstance(node, dict) and node.get('type') == 'function_call':
            if node.get('name') in ('create_thread', 'create_threads'):
                proc_name = _thread_proc_name(node)
                if proc_name:
                    thread_entries.add(proc_name)

    return semaphores, procedures, thread_entries


# ---------------------------------------------------------------------------
# Phase B: Per-procedure delta computation (interprocedural, cycle-safe)
# ---------------------------------------------------------------------------

def _compute_delta(
    proc_name: str,
    semaphores: Dict[str, int],
    procedures: Dict[str, list],
    visited: Set[str],
    depth: int,
) -> Dict[str, int]:
    """
    Compute the net semaphore delta for one procedure invocation.
    Returns dict[sem_name -> net_change] where negative means more waits than signals.
    """
    if proc_name not in procedures:
        return {}
    if proc_name in visited or depth > MAX_INLINE_DEPTH:
        return {}

    visited = visited | {proc_name}
    delta: Dict[str, int] = {s: 0 for s in semaphores}

    for node in _walk_nodes(procedures[proc_name]):
        if not isinstance(node, dict) or node.get('type') != 'function_call':
            continue
        call_name = node.get('name')
        arg = _arg0_name(node)

        if call_name == 'wait' and arg in semaphores:
            delta[arg] -= 1
        elif call_name == 'signal' and arg in semaphores:
            delta[arg] += 1
        elif call_name in procedures:
            sub = _compute_delta(call_name, semaphores, procedures, visited, depth + 1)
            for s, v in sub.items():
                delta[s] += v

    return delta


# ---------------------------------------------------------------------------
# Companion: infinite recursion detection
# ---------------------------------------------------------------------------

def _find_recursive_cycles(
    procedures: Dict[str, list],
    source_filename: str,
) -> None:
    """
    DFS over the procedure call graph. Reports procedures that call themselves
    directly or transitively (with no possible base case in Tier 1 terms).
    """
    # Build call graph: proc -> set of directly called procedures
    call_graph: Dict[str, Set[str]] = {p: set() for p in procedures}
    for proc_name, body in procedures.items():
        for node in _walk_nodes(body):
            if isinstance(node, dict) and node.get('type') == 'function_call':
                callee = node.get('name')
                if callee in procedures and callee != proc_name:
                    call_graph[proc_name].add(callee)
                elif callee == proc_name:
                    call_graph[proc_name].add(callee)

    # Tarjan-style cycle detection with WHITE/GRAY/BLACK coloring
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {p: WHITE for p in procedures}
    reported: Set[str] = set()

    def dfs(proc: str, path: List[str]) -> None:
        color[proc] = GRAY
        path.append(proc)
        for callee in call_graph.get(proc, set()):
            if color[callee] == GRAY:
                # Found a cycle; find the cycle start in path
                cycle_start = path.index(callee)
                cycle = path[cycle_start:]
                cycle_key = frozenset(cycle)
                if cycle_key not in reported:
                    reported.add(cycle_key)
                    cycle_str = ' -> '.join(cycle + [callee])
                    _warn(
                        source_filename,
                        f"infinite recursion detected: {cycle_str}\n"
                        f"  this will cause a stack overflow at runtime",
                    )
            elif color[callee] == WHITE:
                dfs(callee, path)
        path.pop()
        color[proc] = BLACK

    for proc in procedures:
        if color[proc] == WHITE:
            dfs(proc, [])


# ---------------------------------------------------------------------------
# Phase C: Depletion checks
# ---------------------------------------------------------------------------

def _check_depletion(
    semaphores: Dict[str, int],
    all_deltas: Dict[str, Dict[str, int]],
    source_filename: str,
) -> None:
    """
    Check 1 — No-recovery: semaphore consumed but never signalled anywhere.
    Check 2 — Net-negative thread: thread-entry procedure has negative delta
              that, combined with total available signals, exhausts the semaphore.
    """
    # Aggregate across all procedures
    total_signals: Dict[str, int] = {s: 0 for s in semaphores}
    total_waits: Dict[str, int]   = {s: 0 for s in semaphores}
    for delta in all_deltas.values():
        for s in semaphores:
            v = delta.get(s, 0)
            if v > 0:
                total_signals[s] += v
            elif v < 0:
                total_waits[s] += abs(v)

    for s, initial_count in semaphores.items():
        # Check 1: consumed but never signalled
        if total_waits[s] > 0 and total_signals[s] == 0:
            consumers = [
                f"'{p}' (net {d[s]:+d})"
                for p, d in all_deltas.items()
                if d.get(s, 0) < 0
            ]
            _warn(
                source_filename,
                f"semaphore '{s}' (initial count {initial_count}) is consumed "
                f"but never signalled\n"
                f"  consumers: {', '.join(consumers)}\n"
                f"  threads will block indefinitely once the semaphore is exhausted",
            )


# ---------------------------------------------------------------------------
# Phase D: Sequential lock-set tracking — collect wait/signal sites
# ---------------------------------------------------------------------------

def _collect_sites(
    body: list,
    semaphores: Dict[str, int],
    procedures: Dict[str, list],
    visited: Set[str],
    depth: int,
    held: set,
    ever_held: set,
):
    """
    Walk *body* sequentially, maintaining two lock sets (both mutated in place):
      held      — mutexes currently held (lock increments, unlock decrements)
      ever_held — mutexes ever acquired on any path from procedure start to here

    Yields:
      ('wait',   sem_name, frozenset(held))       — lock-set at the wait call
      ('signal', sem_name, frozenset(ever_held))  — locks acquired anywhere before
                                                    the signal (even if released)

    Using ever_held for signal sites catches the classic pattern where the
    signaler acquires a mutex to enqueue/prepare, then releases it before
    calling signal — yet the waiter might hold that mutex, preventing the
    signaler from ever reaching signal.
    """
    for node in body:
        if not isinstance(node, dict):
            continue
        ntype = node.get('type')

        if ntype == 'function_call':
            call = node.get('name')
            arg  = _arg0_name(node)
            if call == 'lock' and arg:
                held.add(arg)
                ever_held.add(arg)
            elif call == 'unlock' and arg:
                held.discard(arg)
            elif call == 'wait' and arg in semaphores:
                yield ('wait', arg, frozenset(held))
            elif call == 'signal' and arg in semaphores:
                yield ('signal', arg, frozenset(ever_held))
            elif call in procedures and call not in visited and depth < MAX_INLINE_DEPTH:
                yield from _collect_sites(
                    procedures[call], semaphores, procedures,
                    visited | {call}, depth + 1, held, ever_held,
                )

        elif ntype == 'if':
            then_held = set(held);  then_ever = set(ever_held)
            else_held = set(held);  else_ever = set(ever_held)
            yield from _collect_sites(node.get('then_body', []), semaphores, procedures, visited, depth, then_held, then_ever)
            yield from _collect_sites(node.get('else_body', []), semaphores, procedures, visited, depth, else_held, else_ever)
            held.clear();      held.update(then_held | else_held)
            ever_held.update(then_ever | else_ever)

        elif ntype in ('while', 'for'):
            loop_held = set(held);  loop_ever = set(ever_held)
            yield from _collect_sites(node.get('body', []), semaphores, procedures, visited, depth, loop_held, loop_ever)
            held.update(loop_held)
            ever_held.update(loop_ever)

        elif ntype == 'case':
            arm_helds, arm_evers = [], []
            for arm in node.get('arms', []):
                ah = set(held);  ae = set(ever_held)
                yield from _collect_sites(arm.get('body', []), semaphores, procedures, visited, depth, ah, ae)
                arm_helds.append(ah);  arm_evers.append(ae)
            default_body = node.get('default_body') or []
            if default_body:
                dh = set(held);  de = set(ever_held)
                yield from _collect_sites(default_body, semaphores, procedures, visited, depth, dh, de)
                arm_helds.append(dh);  arm_evers.append(de)
            for h in arm_helds:  held.update(h)
            for e in arm_evers:  ever_held.update(e)

        elif ntype == 'block':
            yield from _collect_sites(node.get('body', []), semaphores, procedures, visited, depth, held, ever_held)


# ---------------------------------------------------------------------------
# Phase E: Cross-thread lock-order deadlock
# ---------------------------------------------------------------------------

def _check_lock_order_deadlock(
    all_wait_sites:   Dict[str, List[Tuple[str, frozenset]]],
    all_signal_sites: Dict[str, List[Tuple[str, frozenset]]],
    source_filename: str,
) -> None:
    """
    For every wait-under-lock site (sem S, held locks L) in thread entry A,
    check whether any *other* thread entry B signals S while also holding a
    lock in L.  If so, B can never reach signal(S) because A holds that lock
    while sleeping, and A can never wake up — confirmed deadlock.
    """
    signal_index: Dict[str, List[Tuple[str, frozenset]]] = {}
    for proc, sites in all_signal_sites.items():
        for sem, sig_locks in sites:
            signal_index.setdefault(sem, []).append((proc, sig_locks))

    reported: Set[tuple] = set()
    for waiter_proc, sites in all_wait_sites.items():
        for sem, wait_locks in sites:
            if not wait_locks:
                continue
            for sig_proc, sig_locks in signal_index.get(sem, []):
                if sig_proc == waiter_proc:
                    continue   # same thread, not a cross-thread deadlock
                conflict = wait_locks & sig_locks
                if conflict:
                    key = (sem, frozenset(wait_locks), sig_proc)
                    if key not in reported:
                        reported.add(key)
                        lock_list = ', '.join(f"'{m}'" for m in sorted(conflict))
                        _warn(
                            source_filename,
                            f"deadlock: '{waiter_proc}' calls wait({sem}) while holding {lock_list}\n"
                            f"  '{sig_proc}' must acquire {lock_list} before it can signal '{sem}'\n"
                            f"  these threads will block each other indefinitely",
                        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(ast: dict, source_filename: str) -> None:
    """
    Run Tier 1 static semaphore token-flow analysis on the parsed AST.
    Emits warnings to stderr; does not terminate compilation.

    Args:
        ast             : program AST dict as produced by parser.toAst()
        source_filename : source file path, used in diagnostic messages
    """
    semaphores, procedures, _ = _collect_symbols(ast)

    if not semaphores:
        return  # Nothing to analyze

    # Compute per-procedure deltas
    all_deltas: Dict[str, Dict[str, int]] = {}
    for proc_name in procedures:
        all_deltas[proc_name] = _compute_delta(
            proc_name, semaphores, procedures, set(), 0
        )

    # Depletion checks
    _check_depletion(semaphores, all_deltas, source_filename)

    # Companion: infinite recursion
    _find_recursive_cycles(procedures, source_filename)

    # Phase D+E: lock-order (wait-under-lock) deadlock
    # Iterate over all procedures — thread_entries detection misses entries
    # passed via create_thread(proc) inside declaration initialisers.
    all_wait_sites:   Dict[str, List[Tuple[str, frozenset]]] = {}
    all_signal_sites: Dict[str, List[Tuple[str, frozenset]]] = {}
    for proc_name in procedures:
        wait_s: List[Tuple[str, frozenset]] = []
        sig_s:  List[Tuple[str, frozenset]] = []
        for event, sem, held in _collect_sites(
            procedures[proc_name], semaphores, procedures, {proc_name}, 0, set(), set()
        ):
            if event == 'wait':
                wait_s.append((sem, held))
            else:
                sig_s.append((sem, held))
        if wait_s:
            all_wait_sites[proc_name] = wait_s
        if sig_s:
            all_signal_sites[proc_name] = sig_s

    if all_wait_sites and all_signal_sites:
        _check_lock_order_deadlock(all_wait_sites, all_signal_sites, source_filename)
