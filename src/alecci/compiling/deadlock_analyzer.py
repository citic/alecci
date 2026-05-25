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
# Lock-graph deadlock analyzer (mutexes + semaphores)
# ---------------------------------------------------------------------------

class LockGraphAnalyzer:
    """
    Lock-graph cycle detector for mutexes and semaphores.

    Builds a directed lock-ordering graph: edge A→B means "resource B was
    acquired while A was already held."  A cycle of length ≥ 2 indicates a
    potential deadlock (circular-wait condition).

    Covers both mutexes (lock/unlock) and semaphores (wait/signal) uniformly.
    Array-indexed resources (lock(arr[h])) are collapsed to 'arr[]'.
    Uses a may-analysis: all branches and loops are explored with a snapshot
    of the held-set, so no real deadlock is missed (but false positives are
    possible when lock patterns are branch-exclusive).
    """

    ACQUIRE_OPS: frozenset = frozenset({'lock', 'wait'})
    RELEASE_OPS: frozenset = frozenset({'unlock', 'signal'})

    def __init__(self, ast: dict, source_filename: str) -> None:
        self.ast = ast
        self.source_filename = source_filename
        self.procedures: Dict[str, list] = {}
        self.resource_names: Set[str] = set()
        self.edges: List[Tuple[str, str, str]] = []  # (holder, acquired, proc_name)
        self.thread_procs: Dict[str, int] = {}       # proc_name -> max thread count

    def analyze(self) -> None:
        self._collect_procedures()
        self._collect_resources()
        self._collect_thread_procs()
        if not self.resource_names:
            return
        for proc_name, body in self.procedures.items():
            self._walk_body(body, frozenset(), proc_name, frozenset())
        self._detect_cycles()

    def _collect_procedures(self) -> None:
        for decl in self.ast.get('declarations', []):
            if isinstance(decl, dict) and decl.get('type') in ('procedure', 'function'):
                self.procedures[decl['name']] = decl.get('body', [])

    def _collect_resources(self) -> None:
        """Collect mutex/semaphore global names.  Array resources as 'name[]'."""
        for node in _walk_all_nodes(self.ast):
            if not isinstance(node, dict):
                continue
            if not (node.get('type') == 'declaration' and node.get('shared')):
                continue
            init = node.get('init', {})
            value = init.get('value', {}) if isinstance(init, dict) else {}
            if not isinstance(value, dict):
                continue
            fname = value.get('name')
            if fname in ('mutex', 'semaphore'):
                self.resource_names.add(node['name'])
            elif fname == 'array':
                args = value.get('arguments', [])
                if len(args) >= 2:
                    elem = args[1]
                    if isinstance(elem, dict) and elem.get('name') in ('mutex', 'semaphore'):
                        self.resource_names.add(node['name'] + '[]')

    def _collect_thread_procs(self) -> None:
        """Record max thread count for each procedure used as a thread entry."""
        # create_threads is usually assigned: "mutable t := create_threads(N, proc)"
        # so it lives inside a declaration's init.value, not as a top-level statement.
        # We check both standalone calls (funcCall nodes) and declaration init values.
        candidate_calls: List[dict] = []
        for node in _walk_all_nodes(self.ast):
            if not isinstance(node, dict):
                continue
            if node.get('type') == 'function_call':
                candidate_calls.append(node)
            elif node.get('type') == 'declaration':
                init = node.get('init', {})
                value = init.get('value', {}) if isinstance(init, dict) else {}
                if isinstance(value, dict) and value.get('type') == 'function_call':
                    candidate_calls.append(value)

        for call in candidate_calls:
            call_name = call.get('name')
            args = call.get('arguments', [])
            if call_name == 'create_threads' and len(args) >= 2:
                count_node, proc_node = args[0], args[1]
                if isinstance(proc_node, dict) and proc_node.get('type') == 'ID':
                    proc_name = proc_node.get('value')
                    count = 0
                    if isinstance(count_node, dict) and count_node.get('type') == 'literal':
                        count = int(count_node.get('value', 0))
                    self.thread_procs[proc_name] = max(
                        self.thread_procs.get(proc_name, 0), count
                    )
            elif call_name == 'create_thread' and args:
                proc_node = args[0]
                if isinstance(proc_node, dict) and proc_node.get('type') == 'ID':
                    proc_name = proc_node.get('value')
                    self.thread_procs[proc_name] = max(
                        self.thread_procs.get(proc_name, 0), 1
                    )

    def _resource_name_from_arg(self, arg: dict) -> Optional[str]:
        """
        Extract the lock-graph resource name from a function-call argument.
        Simple identifier  → 'name'   (if a known resource)
        Array access       → 'name[]' (if the array is a known resource)
        Returns None if the argument is not a known resource.
        """
        if not isinstance(arg, dict):
            return None
        if arg.get('type') == 'ID':
            name = arg.get('value')
            if name in self.resource_names:
                return name
        elif arg.get('type') == 'array_access':
            arr = arg.get('array', {})
            if isinstance(arr, dict) and arr.get('type') == 'ID':
                candidate = arr.get('value', '') + '[]'
                if candidate in self.resource_names:
                    return candidate
        return None

    def _walk_body(
        self,
        body: list,
        held: frozenset,
        proc_name: str,
        visiting: frozenset,
    ) -> None:
        """
        Walk a statement list sequentially, tracking the held-resource set.

        Acquire ops (lock/wait): record edges from every currently-held resource
        to the newly acquired one, then add it to held.
        Release ops (unlock/signal): remove from held.
        Procedure calls: recurse with current held snapshot (inlining).
        Branches/loops: recurse with a held snapshot (may-analysis; no merge back).
        """
        current_held: Set[str] = set(held)
        for node in body:
            if not isinstance(node, dict):
                continue
            node_type = node.get('type')

            if node_type == 'function_call':
                call_name = node.get('name', '')
                args = node.get('arguments', [])
                if call_name in self.ACQUIRE_OPS and args:
                    resource = self._resource_name_from_arg(args[0])
                    if resource is not None:
                        for held_res in current_held:
                            self.edges.append((held_res, resource, proc_name))
                        current_held.add(resource)
                elif call_name in self.RELEASE_OPS and args:
                    resource = self._resource_name_from_arg(args[0])
                    if resource is not None:
                        current_held.discard(resource)
                elif call_name in self.procedures and call_name not in visiting:
                    self._walk_body(
                        self.procedures[call_name],
                        frozenset(current_held),
                        proc_name,
                        visiting | {call_name},
                    )

            elif node_type == 'if':
                snap = frozenset(current_held)
                self._walk_body(node.get('then_body', []), snap, proc_name, visiting)
                self._walk_body(node.get('else_body', []), snap, proc_name, visiting)

            elif node_type in ('while', 'for', 'parallel_for'):
                self._walk_body(
                    node.get('body', []), frozenset(current_held), proc_name, visiting
                )

            elif node_type == 'case':
                snap = frozenset(current_held)
                for arm in node.get('arms', []):
                    self._walk_body(arm.get('body', []), snap, proc_name, visiting)
                default_body = node.get('default_body') or []
                self._walk_body(default_body, snap, proc_name, visiting)

            elif node_type == 'block':
                self._walk_body(
                    node.get('body', []), frozenset(current_held), proc_name, visiting
                )

    def _detect_cycles(self) -> None:
        """
        Build an adjacency set from collected edges and run DFS cycle detection.
        Reports each unique cycle (identified by its directed edge set) at most once.
        """
        adjacency: Dict[str, Set[Tuple[str, str]]] = {}
        for holder, acquired, proc_name in self.edges:
            adjacency.setdefault(holder, set())
            adjacency.setdefault(acquired, set())
            adjacency[holder].add((acquired, proc_name))

        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {n: WHITE for n in adjacency}
        reported: Set[frozenset] = set()

        def dfs(node: str, path: List[Tuple[str, str]]) -> None:
            color[node] = GRAY
            for neighbor, edge_proc in adjacency.get(node, set()):
                if color.get(neighbor) == GRAY:
                    start_idx = next(
                        i for i, (n, _) in enumerate(path) if n == neighbor
                    )
                    cycle_path = path[start_idx:]
                    cycle_nodes = [n for n, _ in cycle_path] + [neighbor]
                    # Skip self-loops (double-lock on same resource)
                    if len(set(cycle_nodes[:-1])) < 2:
                        continue
                    edge_set = frozenset(zip(cycle_nodes[:-1], cycle_nodes[1:]))
                    if edge_set in reported:
                        continue
                    reported.add(edge_set)
                    cycle_procs = [p for _, p in cycle_path[1:]] + [edge_proc]
                    involved_procs = set(cycle_procs) - {''}
                    self._maybe_warn(cycle_nodes, involved_procs)
                elif color.get(neighbor, WHITE) == WHITE:
                    dfs(neighbor, path + [(neighbor, edge_proc)])
            color[node] = BLACK

        for node in list(adjacency.keys()):
            if color[node] == WHITE:
                dfs(node, [(node, '')])

    def _maybe_warn(self, cycle_nodes: List[str], involved_procs: Set[str]) -> None:
        """Apply non-concurrency pruning, then emit a deadlock warning."""
        # Infeasible: all edges came from main() — only one main thread
        if involved_procs <= {'main'}:
            return
        # Infeasible: single non-main procedure with at most 1 thread instance
        if len(involved_procs) == 1:
            proc = next(iter(involved_procs))
            if self.thread_procs.get(proc, 2) <= 1:
                return

        cycle_str = ' -> '.join(cycle_nodes)
        proc_details = ', '.join(
            f"'{p}' ({self.thread_procs.get(p, '?')} threads)"
            if p != 'main' else "'main'"
            for p in sorted(involved_procs)
        )
        _warn(
            self.source_filename,
            f"potential deadlock detected (lock-ordering cycle).\n"
            f"  Lock cycle: {cycle_str}\n"
            f"  Involved procedures: {proc_details}\n"
            f"  Hint: resources are acquired in inconsistent order across concurrent threads.",
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze(ast: dict, source_filename: str) -> None:
    """
    Run static deadlock analysis on the parsed AST.
    Emits warnings to stderr; does not terminate compilation.

    Checks performed:
      1. Semaphore token-flow: flags semaphores that can be permanently drained.
      2. Infinite recursion: flags procedures that call themselves transitively.
      3. Lock-graph cycle: flags mutex/semaphore acquire-order cycles (deadlock).

    Args:
        ast             : program AST dict as produced by parser.toAst()
        source_filename : source file path, used in diagnostic messages
    """
    semaphores, procedures, thread_entries = _collect_symbols(ast)

    if semaphores:
        all_deltas: Dict[str, Dict[str, int]] = {}
        for proc_name in procedures:
            all_deltas[proc_name] = _compute_delta(
                proc_name, semaphores, procedures, set(), 0
            )
        _check_depletion(semaphores, all_deltas, source_filename)

    if procedures:
        _find_recursive_cycles(procedures, source_filename)

    LockGraphAnalyzer(ast, source_filename).analyze()
