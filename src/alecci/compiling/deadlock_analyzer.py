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
            yield from _walk_nodes(node.get('then', []))
            yield from _walk_nodes(node.get('else', []))
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
    semaphores, procedures, thread_entries = _collect_symbols(ast)

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
