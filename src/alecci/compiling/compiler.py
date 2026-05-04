from typing import Any, Dict, List, Optional, Tuple, Union
from llvmlite import ir
import sys

from .base_types import get_type
from .threading_utils import create_threads, create_thread, join_threads, join_thread
from ..parsing.globals import debug_print
from . import variant_utils


# ---------------------------------------------------------------------------
# Argument-type → LLVM type helper
# ---------------------------------------------------------------------------

# Types whose LLVM representation is a pointer to an opaque runtime struct.
# These match the entries in base_types._SCALAR_TYPE_MAP.
_OPAQUE_PTR_TYPES = frozenset({
    'semaphore', 'mutex', 'barrier', 'thread', 'queue',
    'array', 'string',
})

def _arg_type_to_llvm(arg_type) -> ir.Type:
    """Map a parsed argument type (string or complex_type dict) to an LLVM type.

    Rules:
      - None / unrecognised scalar strings  → i32  (variant / untyped int)
      - 'int'                               → i32
      - 'float'                             → double
      - 'char'                              → i8   (scalar byte, NOT a pointer)
      - 'string'                            → i8*
      - 'variant'                           → variant struct
      - concurrency types (semaphore, mutex, barrier, thread, queue, array)
                                            → i8*  (opaque runtime handle)
      - complex_type dict (REFERENCE, etc.) → i8*  (opaque pointer, best effort)
    """
    if isinstance(arg_type, dict):
        # e.g. {'type': 'reference_type', ...} or {'type': 'pointer_type', ...}
        return ir.IntType(8).as_pointer()
    if arg_type == 'float':
        return ir.DoubleType()
    if arg_type == 'char':
        return ir.IntType(8)      # scalar byte — NOT a pointer
    if arg_type == 'variant':
        from .base_types import get_variant_type
        return get_variant_type()
    if arg_type in _OPAQUE_PTR_TYPES:
        return ir.IntType(8).as_pointer()
    # 'int', None, unknown named types → i32
    return ir.IntType(32)


class AleError(Exception):
    """A clean, user-facing compiler error with optional source location."""
    def __init__(self, message: str, node: Dict[str, Any] | None = None) -> None:
        lineno = node.get('lineno') if isinstance(node, dict) else None
        suffix = f" (line {lineno})" if lineno else ""
        super().__init__(f"error: {message}{suffix}")


# ---------------------------------------------------------------------------
# Pre-compilation semantic check for unsupported grammar constructs
# ---------------------------------------------------------------------------

_UNSUPPORTED_NODE_TYPES = {
    'record_init': 'record initialization',
    'pointer_type': 'pointer types',
    'dereference':  'dereference',
    'reference':    'references',
}

def _check_unsupported_nodes(ast: Any) -> None:
    """Walk the AST and raise AleError for any grammar construct that is parsed
    but not yet lowered to LLVM IR.  Runs before any IR is emitted so the user
    gets a clean diagnostic instead of a Python traceback."""
    if isinstance(ast, dict):
        node_type = ast.get('type')
        if node_type in _UNSUPPORTED_NODE_TYPES:
            feature = _UNSUPPORTED_NODE_TYPES[node_type]
            raise AleError(f"'{feature}' is not yet supported", ast)
        for value in ast.values():
            _check_unsupported_nodes(value)
    elif isinstance(ast, list):
        for item in ast:
            _check_unsupported_nodes(item)


class CodeGenerator:
    def __init__(self, performance_mode: bool = True, source_filename: str = "program.ale") -> None:
        self.module = ir.Module(name="main")
        self.builder = None
        self.funcs: Dict[str, ir.Function] = {}
        self.locals = {}  # name -> (pointer, datatype, is_constant)
        self.globals = {}  # name -> (pointer, datatype, is_constant)
        self.var_types = {}  # name -> 'int'|'float'|'string'|etc. for type tracking
        self.current_function_name = None  # Track current function for context
        self.shared_runtime_inits = []  # List of (name, expression) for shared vars that need runtime evaluation
        # timespec type for nanosleep: struct { i64 tv_sec; i64 tv_nsec; }
        self.timespec_ty = ir.LiteralStructType([ir.IntType(64), ir.IntType(64)])
        # Track if the current function/procedure had an explicit return in its body
        # Debug metadata for source location info
        self.source_filename = source_filename
        self.di_file = None
        self.di_compile_unit = None
        self.current_di_location = None
        self.has_explicit_return: bool = False
        self.loop_exit_stack: List[ir.Block] = []  # stack of loop-exit blocks for break
        # Performance mode: insert sched_yield() and TSan instrumentation for race detection
        self.performance_mode: bool = performance_mode
        self.sched_yield_fn = None  # Will be initialized in compile()

    def semantic_error(self, message: str, node: Optional[Dict[str, Any]] = None) -> None:
        """Report a semantic error and exit.
        
        Args:
            message: The error message to display
            node: Optional AST node containing location information
        """
        # Format: filename:line:column: semantic error: message (matching syntax error format)
        if node and 'lineno' in node:
            # Use 1 for column since we don't track column numbers in semantic analysis
            print(f"\n{self.source_filename}:{node['lineno']}:1: semantic error: {message}", file=sys.stderr)
        else:
            print(f"\n{self.source_filename}: semantic error: {message}", file=sys.stderr)
        sys.exit(1)

    def is_shared_mutable_variable(self, name: str) -> bool:
        """Check if a variable is a shared mutable global variable."""
        if name not in self.globals:
            return False
        ptr, dtype, is_constant = self.globals[name]
        # Shared mutable variables are globals that are not constant
        # Exclude sync primitives (mutex, semaphore, barrier) as they have their own synchronization
        return not is_constant and dtype not in ['mutex', 'semaphore', 'barrier', 'queue', 'thread', 'thread_array']

    def insert_yield(self):
        """Insert a sched_yield() call to force thread interleaving for race detection."""
        if self.performance_mode and self.sched_yield_fn and self.builder:
            self.builder.call(self.sched_yield_fn, [])
    
    def _init_debug_info(self):
        """Initialize debug metadata for source location tracking in TSan reports."""
        # Skip complex debug metadata - llvmlite has limited support
        # TSan already shows variable names correctly from the IR symbols
        # Just track that we want source info
        import os
        self.source_file = os.path.basename(self.source_filename) if self.source_filename else "program.ale"
        self.di_enabled = True
    
    def set_debug_location(self, line: int = 1, column: int = 1):
        """Set debug location for subsequent instructions."""
        if self.builder:
            # Create a simple debug location
            # This helps TSan show line numbers in reports
            loc = self.builder.debug_metadata
            # Note: llvmlite has limited debug support, but setting any location helps
    
    def insert_tsan_call(self, ptr, size_bytes, is_write=False):
        """Insert a TSan instrumentation call to track memory access.
        
        Args:
            ptr: LLVM pointer value being accessed
            size_bytes: Size of the access in bytes (1, 2, 4, or 8)
            is_write: True for writes, False for reads
        """
        if not self.builder or not self.performance_mode:
            return
        
        # Select appropriate TSan function based on size and operation
        tsan_functions = {
            (1, False): self.tsan_read1_fn,
            (2, False): self.tsan_read2_fn,
            (4, False): self.tsan_read4_fn,
            (8, False): self.tsan_read8_fn,
            (1, True): self.tsan_write1_fn,
            (2, True): self.tsan_write2_fn,
            (4, True): self.tsan_write4_fn,
            (8, True): self.tsan_write8_fn,
        }
        
        tsan_fn = tsan_functions.get((size_bytes, is_write))
        if not tsan_fn:
            return
        
        # Cast pointer to i8* for TSan call
        i8_ptr_ty = ir.IntType(8).as_pointer()
        ptr_cast = self.builder.bitcast(ptr, i8_ptr_ty)
        
        # Call TSan function
        self.builder.call(tsan_fn, [ptr_cast])

    # ------------------------------------------------------------------
    # Low-level helpers (eliminate repeated boilerplate)
    # ------------------------------------------------------------------

    def _declare_external_fn(self, name: str, return_ty, arg_tys,
                              var_arg: bool = False) -> ir.Function:
        """Get or declare an external C function, creating it once per module."""
        return variant_utils.declare_external_fn(self.module, name, return_ty,
                                                  arg_tys, var_arg)

    def _resolve_arg_ptr(self, arg0, expected_ty=None) -> ir.Value:
        """Resolve a sync-primitive argument node to a pointer value.

        Handles the three common node shapes used in wait/signal/lock/unlock/
        barrier_wait: string-literal-as-ID, ID node, array_access node, and
        anything else (visited normally). Optionally bitcasts to *expected_ty*.
        """
        if (isinstance(arg0, dict) and arg0.get('type') == 'literal' and
                isinstance(arg0.get('value'), str)):
            ptr = self.visit_ID({'type': 'ID', 'value': arg0['value']},
                                prefer_globals=True)
        elif isinstance(arg0, dict) and arg0.get('type') == 'ID':
            ptr = self.visit_ID(arg0, prefer_globals=True)
        elif isinstance(arg0, dict) and arg0.get('type') == 'array_access':
            ptr = self.visit_array_access(arg0)
        else:
            ptr = self.visit(arg0)
        if expected_ty is not None and hasattr(ptr, 'type') and ptr.type != expected_ty:
            ptr = self.builder.bitcast(ptr, expected_ty)
        return ptr

    def _emit_counted_loop(self, fn: ir.Function, ptr: ir.Value,
                            count_val: ir.Value, label: str) -> ir.Value:
        """Emit a counted loop that calls *fn*(*ptr*) exactly *count_val* times.

        Used to implement ``wait(sem, n)`` and ``signal(sem, n)``.
        Returns ``i32 0``.
        """
        # Unwrap variant if needed, coerce to i32
        count_val = self._auto_extract_value(count_val, 'int')
        if hasattr(count_val, 'type') and isinstance(count_val.type, ir.IntType) and count_val.type.width != 32:
            count_val = self.builder.zext(count_val, ir.IntType(32))

        i_ptr = self.builder.alloca(ir.IntType(32), name=f"{label}_i")
        self.builder.store(ir.Constant(ir.IntType(32), 0), i_ptr)
        cond_bb = self.builder.append_basic_block(f"{label}_loop_cond")
        body_bb = self.builder.append_basic_block(f"{label}_loop_body")
        end_bb  = self.builder.append_basic_block(f"{label}_loop_end")
        self.builder.branch(cond_bb)
        self.builder.position_at_end(cond_bb)
        i_val = self.builder.load(i_ptr)
        cond = self.builder.icmp_signed('<', i_val, count_val)
        self.builder.cbranch(cond, body_bb, end_bb)
        self.builder.position_at_end(body_bb)
        self.builder.call(fn, [ptr])
        new_i = self.builder.add(i_val, ir.Constant(ir.IntType(32), 1))
        self.builder.store(new_i, i_ptr)
        self.builder.branch(cond_bb)
        self.builder.position_at_end(end_bb)
        return ir.Constant(ir.IntType(32), 0)

    def _emit_template_sprintf(self, template: str):
        """Format a backtick template string using sprintf and return (ptr, is_string).

        *template* is the content between the backticks. Any ``{varname}``
        placeholders are replaced with the corresponding variable values via a
        stack-allocated 256-byte sprintf buffer.

        Returns ``(ptr: ir.Value, is_string: True)`` where *ptr* is an ``i8*``
        pointing to the formatted string buffer.  When no ``{...}`` placeholders
        are present the string is emitted as a global constant instead.
        """
        import re
        from .base_types import get_variant_type

        variable_patterns = re.findall(r'\{([^}]+)\}', template)

        if not variable_patterns:
            # No placeholders — emit as a plain global string constant
            name = f"str_{abs(hash(template))}"
            str_bytes = bytearray(template.encode("utf8")) + b"\00"
            str_type = ir.ArrayType(ir.IntType(8), len(str_bytes))
            if name in self.module.globals:
                str_global = self.module.get_global(name)
            else:
                str_global = ir.GlobalVariable(self.module, str_type, name=name)
                str_global.linkage = 'internal'
                str_global.global_constant = True
                str_global.initializer = ir.Constant(str_type, str_bytes)
            return self.builder.bitcast(str_global, ir.IntType(8).as_pointer()), True

        variant_ty = get_variant_type()
        format_string = template
        format_args = []

        for var_name in variable_patterns:
            entry = self.get_variable(var_name)
            dtype = entry[1] if entry and len(entry) >= 2 else None

            if dtype == 'variant':
                variant_ptr = entry[0]
                if var_name in self.var_types and self.var_types[var_name] == 'float':
                    format_string = format_string.replace(f'{{{var_name}}}', '%f')
                    format_args.append(self._extract_variant_value(variant_ptr, 'float'))
                elif var_name in self.var_types and self.var_types[var_name] == 'int':
                    format_string = format_string.replace(f'{{{var_name}}}', '%d')
                    format_args.append(self._extract_variant_value(variant_ptr, 'int'))
                else:
                    # Unknown variant type — use variant_to_string for correct output
                    format_string = format_string.replace(f'{{{var_name}}}', '%s')
                    v2s = self._declare_external_fn(
                        'variant_to_string',
                        ir.IntType(8).as_pointer(),
                        [variant_ty.as_pointer()])
                    format_args.append(self.builder.call(v2s, [variant_ptr]))
            elif dtype == 'float':
                format_string = format_string.replace(f'{{{var_name}}}', '%f')
                var_value = self.visit_ID({'type': 'ID', 'value': var_name})
                if hasattr(var_value, 'type') and isinstance(var_value.type, ir.PointerType):
                    var_value = self.builder.load(var_value)
                format_args.append(var_value)
            elif dtype == 'string':
                format_string = format_string.replace(f'{{{var_name}}}', '%s')
                var_value = self.visit_ID({'type': 'ID', 'value': var_name})
                if hasattr(var_value, 'type') and isinstance(var_value.type, ir.PointerType) and var_value.type.pointee != ir.IntType(8):
                    var_value = self.builder.load(var_value)
                format_args.append(var_value)
            else:
                format_string = format_string.replace(f'{{{var_name}}}', '%d')
                try:
                    var_value = self.visit_ID({'type': 'ID', 'value': var_name})
                    if hasattr(var_value, 'type') and isinstance(var_value.type, ir.PointerType):
                        var_value = self.builder.load(var_value)
                    format_args.append(var_value)
                except Exception:
                    format_args.append(ir.Constant(ir.IntType(32), 0))

        # Emit format string global
        fmt_name = f"fmt_{abs(hash(format_string))}"
        fmt_bytes = bytearray(format_string.encode("utf8")) + b"\00"
        fmt_type = ir.ArrayType(ir.IntType(8), len(fmt_bytes))
        if fmt_name in self.module.globals:
            fmt_global = self.module.get_global(fmt_name)
        else:
            fmt_global = ir.GlobalVariable(self.module, fmt_type, name=fmt_name)
            fmt_global.linkage = 'internal'
            fmt_global.global_constant = True
            fmt_global.initializer = ir.Constant(fmt_type, fmt_bytes)
        fmt_arg = self.builder.bitcast(fmt_global, ir.IntType(8).as_pointer())

        # Stack buffer + sprintf call
        buf_ty = ir.ArrayType(ir.IntType(8), 256)
        buf = self.builder.alloca(buf_ty, name="sprintf_buf")
        buf_ptr = self.builder.bitcast(buf, ir.IntType(8).as_pointer())
        sprintf = self._declare_external_fn(
            'sprintf', ir.IntType(32),
            [ir.IntType(8).as_pointer(), ir.IntType(8).as_pointer()],
            var_arg=True)
        self.builder.call(sprintf, [buf_ptr, fmt_arg] + format_args)
        return buf_ptr, True

    def _cleanup_concurrency_primitives(self, function_name: str):
        """Clean up concurrency primitives (mutexes, semaphores, barriers) at end of procedure."""
        if not self.builder or self.builder.block.is_terminated:
            return

        opaque_ty = ir.IntType(8).as_pointer()
        mutex_destroy  = self._declare_external_fn('pthread_mutex_destroy',  ir.IntType(32), [opaque_ty])
        sem_destroy     = self._declare_external_fn('sem_destroy',             ir.IntType(32), [opaque_ty])
        barrier_destroy = self._declare_external_fn('pthread_barrier_destroy', ir.IntType(32), [opaque_ty])

        for name, ptr in self.local_mutexes:
            debug_print(f"DEBUG: Cleaning up local mutex '{name}' in {function_name}")
            if ptr.type != opaque_ty:
                ptr = self.builder.bitcast(ptr, opaque_ty)
            self.builder.call(mutex_destroy, [ptr])

        for name, ptr in self.local_semaphores:
            debug_print(f"DEBUG: Cleaning up local semaphore '{name}' in {function_name}")
            if ptr.type != opaque_ty:
                ptr = self.builder.bitcast(ptr, opaque_ty)
            self.builder.call(sem_destroy, [ptr])

        for name, ptr in self.local_barriers:
            debug_print(f"DEBUG: Cleaning up local barrier '{name}' in {function_name}")
            if ptr.type != opaque_ty:
                ptr = self.builder.bitcast(ptr, opaque_ty)
            self.builder.call(barrier_destroy, [ptr])

        if function_name == 'main':
            for var_name, (var_ptr, var_type, _) in self.globals.items():
                if var_type == 'mutex':
                    debug_print(f"DEBUG: Cleaning up shared mutex '{var_name}' in main")
                    self.builder.call(mutex_destroy,
                                      [self.builder.bitcast(var_ptr, opaque_ty)])
                elif var_type == 'semaphore':
                    debug_print(f"DEBUG: Cleaning up shared semaphore '{var_name}' in main")
                    self.builder.call(sem_destroy,
                                      [self.builder.bitcast(var_ptr, opaque_ty)])
                elif var_type == 'barrier':
                    debug_print(f"DEBUG: Cleaning up shared barrier '{var_name}' in main")
                    self.builder.call(barrier_destroy,
                                      [self.builder.bitcast(var_ptr, opaque_ty)])
    
    def _make_shared_accesses_atomic(self, ir_string: str) -> str:
        """
        Post-process LLVM IR to make loads/stores of shared globals atomic.
        This enables ThreadSanitizer to properly instrument and detect data races.
        """
        import re
        
        # Get list of shared mutable global variable names
        shared_vars = [name for name in self.globals.keys() 
                      if self.is_shared_mutable_variable(name)]
        
        if not shared_vars:
            return ir_string
        
        # Convert loads of shared globals to atomic loads
        for var_name in shared_vars:
            # Pattern: load TYPE, TYPE* @"var_name" [, align N]
            # Replace with: load atomic TYPE, TYPE* @"var_name" monotonic, align N
            # Note: atomic operations require explicit alignment
            pattern = rf'(load )(i32|double)(, \2\* @"{re.escape(var_name)}")(?:, align (\d+))?'
            
            def add_alignment(match):
                load_kw = match.group(1)
                type_name = match.group(2)
                ptr_part = match.group(3)
                align = match.group(4) if match.group(4) else ('4' if type_name == 'i32' else '8')
                return f'{load_kw}atomic {type_name}{ptr_part} monotonic, align {align}'
            
            ir_string = re.sub(pattern, add_alignment, ir_string)
        
        # Convert stores to shared globals to atomic stores  
        for var_name in shared_vars:
            # Pattern: store TYPE %val, TYPE* @"var_name" [, align N]
            # Replace with: store atomic TYPE %val, TYPE* @"var_name" monotonic, align N
            pattern = rf'(store )(i32|double)( %[^,]+, \2\* @"{re.escape(var_name)}")(?:, align (\d+))?'
            
            def add_alignment(match):
                store_kw = match.group(1)
                type_name = match.group(2)
                val_ptr_part = match.group(3)
                align = match.group(4) if match.group(4) else ('4' if type_name == 'i32' else '8')
                return f'{store_kw}atomic {type_name}{val_ptr_part} monotonic, align {align}'
            
            ir_string = re.sub(pattern, add_alignment, ir_string)
        
        return ir_string

    def _debug_verify_module(self) -> None:
        """Walk every function/block/instruction looking for IR errors.

        Only meaningful when debug output is active.  Called from compile()
        before serialising the module so that error messages name the broken
        function rather than crashing in str(module).
        """
        for name, func in list(self.module.globals.items()):
            if not hasattr(func, 'blocks'):
                continue
            try:
                str(func)
                debug_print(f"DEBUG: Function {name} converted successfully")
            except Exception as e:
                debug_print(f"DEBUG: ERROR in function {name}: {e}")
                if not hasattr(func, 'basic_blocks'):
                    continue
                for i, block in enumerate(func.basic_blocks):
                    try:
                        str(block)
                        debug_print(f"DEBUG: Block {i} in {name} OK")
                    except Exception as be:
                        debug_print(f"DEBUG: ERROR in block {i} of {name}: {be}")
                        if not hasattr(block, 'instructions'):
                            continue
                        for j, instr in enumerate(block.instructions):
                            try:
                                str(instr)
                            except Exception as ie:
                                debug_print(f"DEBUG: ERROR in instruction {j} of block {i} of {name}: {ie}")
                                debug_print(f"DEBUG: Instruction type: {type(instr)}")
                                if hasattr(instr, 'args'):
                                    for k, arg in enumerate(instr.args):
                                        if hasattr(arg, 'type'):
                                            debug_print(f"DEBUG: Arg {k} LLVM type: {arg.type}")
                                        else:
                                            debug_print(f"DEBUG: Arg {k} has no type attribute!")
                                break

    def compile(self, ast: Dict[str, Any]) -> str:
        try:
            if self.performance_mode:
                self._init_performance_intrinsics()
            self._init_debug_info()
            _check_unsupported_nodes(ast)
            self.visit(ast)
            debug_print("DEBUG: AST compilation completed, verifying module...")
            self._debug_verify_module()
            return str(self.module)
        except Exception as e:
            debug_print(f"DEBUG: Error during compilation: {e}")
            debug_print(f"DEBUG: Module functions: {list(self.module.globals.keys())}")
            raise

    def _init_performance_intrinsics(self) -> None:
        """Declare sched_yield and TSan instrumentation functions (performance_mode only)."""
        void_ty = ir.VoidType()
        ptr_ty = ir.IntType(8).as_pointer()
        self.sched_yield_fn = ir.Function(self.module,
                                           ir.FunctionType(ir.IntType(32), []),
                                           name="sched_yield")
        for suffix in ('1', '2', '4', '8'):
            fn_ty = ir.FunctionType(void_ty, [ptr_ty])
            setattr(self, f'tsan_read{suffix}_fn',
                    ir.Function(self.module, fn_ty, name=f'__tsan_read{suffix}'))
            setattr(self, f'tsan_write{suffix}_fn',
                    ir.Function(self.module, fn_ty, name=f'__tsan_write{suffix}'))

    def visit(self, node: Union[Dict[str, Any], List[Dict[str, Any]], Any]) -> Any:
        if isinstance(node, list):
            for n in node:
                self.visit(n)
            return
        if not isinstance(node, dict):
            return node
        node_type = node.get('type')
        debug_print(f'DEBUG: visiting {node_type}')
        if node_type == 'array_access':
            debug_print(f'DEBUG: Found array_access node: {node}')        
        method = getattr(self, f'visit_{node_type}', self.generic_visit)
        return method(node)

    def generic_visit(self, node: Dict[str, Any]) -> None:
        raise Exception(f"No visit_{node.get('type')} method")
    
    def visit_program(self, node: Dict[str, Any]) -> None:
        # Two-pass compilation to handle circular dependencies
        # Pass 1: Collect all shared/global declarations and procedure signatures
        self.collect_globals_and_signatures(node['declarations'])
        # Pass 2: Compile procedure bodies
        self.compile_procedure_bodies(node['declarations'])

    def collect_globals_and_signatures(self, declarations: List[Dict[str, Any]]) -> None:
        """First pass: collect all shared variables and procedure/function signatures"""
        for decl in declarations:
            if decl.get('type') == 'procedure' or decl.get('type') == 'function':
                # Create function signature - main should accept argc and argv
                if decl['name'] == 'main':
                    # Check if main has parameters declared
                    main_params = decl.get('arguments', [])
                    if main_params:
                        # main(argc, argv) -> int main(int argc, char** argv)
                        argc_type = ir.IntType(32)  # int argc
                        argv_type = ir.IntType(8).as_pointer().as_pointer()  # char** argv
                        func_ty = ir.FunctionType(ir.IntType(32), [argc_type, argv_type])
                    else:
                        # main with no parameters
                        func_ty = ir.FunctionType(ir.IntType(32), [])
                else:
                    # Non-main procedures/functions: check if they have explicit parameters
                    # Don't automatically add thread_number - let the programmer define it
                    param_types = []
                    for arg in decl.get('arguments', []):
                        param_types.append(_arg_type_to_llvm(arg.get('arg_type')))
                    # Functions return values, procedures can also return values (default to variant)
                    if decl.get('type') == 'function':
                        # The parser does not emit return_type on function nodes; always use variant.
                        # TODO: add '-> type' return-type syntax to the grammar when needed.
                        from .base_types import get_variant_type
                        func_ty = ir.FunctionType(get_variant_type(), param_types)
                    else:
                        # Procedures also return variant by default (can be used with or without return statements)
                        from .base_types import get_variant_type
                        func_ty = ir.FunctionType(get_variant_type(), param_types)
                func = ir.Function(self.module, func_ty, name=decl['name'])
                self.funcs[decl['name']] = func
                # Recursively process shared declarations in the procedure/function body
                self._collect_shared_in_body(decl.get('body', []))
            elif decl.get('type') == 'declaration' and decl.get('shared'):
                # Process shared variable declarations
                self.process_shared_declaration(decl)

    def _collect_shared_in_body(self, body):
        if isinstance(body, list):
            for stmt in body:
                self._collect_shared_in_body(stmt)
        elif isinstance(body, dict):
            if body.get('type') == 'declaration' and body.get('shared'):
                self.process_shared_declaration(body)
            # Recurse into nested blocks (e.g., if, while, for, case, etc.)
            for key in ['body', 'then_body', 'else_body', 'default_body']:
                if key in body:
                    self._collect_shared_in_body(body[key])
            # Recurse into case arms (each arm has a 'body' key)
            if body.get('type') == 'case' and 'arms' in body:
                for arm in body['arms']:
                    self._collect_shared_in_body(arm.get('body', []))

    def compile_procedure_bodies(self, declarations: List[Dict[str, Any]]) -> None:
        """Second pass: compile procedure/function bodies"""
        for decl in declarations:
            if decl.get('type') in ['procedure', 'function']:
                func = self.funcs[decl['name']]
                block = func.append_basic_block('entry')
                # Save current builder state
                old_builder = self.builder
                old_locals = self.locals.copy()
                old_func_name = self.current_function_name

                self.builder = ir.IRBuilder(block)
                self.locals = {}  # Reset locals for this procedure/function
                self.current_function_name = decl['name']
                # Reset explicit return tracker for this body
                self.has_explicit_return = False
                # Reset local concurrency primitives tracking for this procedure
                self.local_mutexes = []
                self.local_semaphores = []
                self.local_barriers = []

                # Process explicitly declared parameters
                if decl['name'] == 'main':
                    # Process main function parameters (argc, argv)
                    main_params = decl.get('arguments', [])
                    if main_params and len(main_params) >= 1:
                        # First parameter: argc
                        argc_param = main_params[0]
                        argc_name = argc_param['id']
                        argc_value = func.args[0]
                        argc_ptr = self.builder.alloca(ir.IntType(32), name=argc_name)
                        self.builder.store(argc_value, argc_ptr)
                        self.locals[argc_name] = (argc_ptr, 'int', False)  # argc is mutable
                        debug_print(f"DEBUG: Added argc parameter '{argc_name}' to main")
                        
                        if len(main_params) >= 2:
                            # Second parameter: argv
                            argv_param = main_params[1]
                            argv_name = argv_param['id']
                            argv_value = func.args[1]
                            argv_ptr = self.builder.alloca(ir.IntType(8).as_pointer().as_pointer(), name=argv_name)
                            self.builder.store(argv_value, argv_ptr)
                            self.locals[argv_name] = (argv_ptr, 'array', False)  # argv is mutable
                            debug_print(f"DEBUG: Added argv parameter '{argv_name}' to main")
                elif decl['name'] != 'main':
                    # Process all arguments defined in the procedure/function signature
                    for i, arg in enumerate(decl.get('arguments', [])):
                        param_name = arg['id']
                        param_value = func.args[i]
                        # Use the LLVM type already on the IR argument (matches signature construction)
                        param_llvm_type = param_value.type
                        param_ptr = self.builder.alloca(param_llvm_type, name=param_name)
                        self.builder.store(param_value, param_ptr)
                        # Derive string type tag from declared arg_type (more accurate than inferring from LLVM type)
                        arg_type_str = arg.get('arg_type')
                        if isinstance(arg_type_str, str):
                            type_tag = arg_type_str
                        elif isinstance(param_llvm_type, ir.DoubleType):
                            type_tag = 'float'
                        elif isinstance(param_llvm_type, ir.PointerType):
                            type_tag = 'string'
                        else:
                            type_tag = 'int'
                        self.locals[param_name] = (param_ptr, type_tag, False)
                        debug_print(f"DEBUG: Added parameter '{param_name}' ({type_tag}) to {decl['name']}")

                # For main function, handle runtime initialization of shared variables
                if decl['name'] == 'main' and self.shared_runtime_inits:
                    debug_print(f"DEBUG: Processing {len(self.shared_runtime_inits)} runtime initializations in main")
                    for var_name, expression in self.shared_runtime_inits:
                        debug_print(f"DEBUG: Runtime initializing shared variable '{var_name}' with expression: {expression}")
                        # Evaluate the expression
                        runtime_value = self.visit(expression)
                        # Get the global variable
                        if var_name in self.globals:
                            global_var, var_type, is_const = self.globals[var_name]
                            # Store the runtime value into the global variable
                            self.builder.store(runtime_value, global_var)
                            debug_print(f"DEBUG: Stored runtime value into global variable '{var_name}'")
                        else:
                            debug_print(f"ERROR: Global variable '{var_name}' not found for runtime initialization")

                # Process non-shared declarations in this procedure/function
                self.visit(decl['body'])
                
                # Clean up concurrency primitives before returning
                self._cleanup_concurrency_primitives(decl['name'])
                
                # Append default return if none was explicitly emitted
                if decl['name'] == 'main':
                    self.builder.ret(ir.Constant(ir.IntType(32), 0))  # main returns 0
                elif decl.get('type') == 'function' or decl.get('type') == 'procedure':
                    # Functions and procedures both return variant by default
                    # If we reach here, it means no explicit return - return null variant as default
                    if not self.builder.block.is_terminated:
                        from .base_types import get_variant_type, get_variant_type_tag_enum
                        variant_ty = get_variant_type()
                        type_tags = get_variant_type_tag_enum()
                        null_tag = ir.Constant(ir.IntType(32), type_tags['null'])
                        null_data = ir.Constant(ir.ArrayType(ir.IntType(8), 16), [ir.Constant(ir.IntType(8), 0)] * 16)
                        null_variant = ir.Constant(variant_ty, [null_tag, null_data])
                        self.builder.ret(null_variant)

                # Restore builder state
                self.builder = old_builder
                self.locals = old_locals
                self.current_function_name = old_func_name

    # ------------------------------------------------------------------
    # process_shared_declaration helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_shared_array_size(size_arg) -> int:
        """Parse an array-size argument node to a plain Python int (default 10)."""
        if isinstance(size_arg, dict) and size_arg.get('type') == 'literal':
            try:
                return int(size_arg['value'])
            except (ValueError, TypeError):
                pass
        return 10

    def _shared_decl_array(self, name: str, value_node: dict) -> None:
        """Declare a shared array global (all element types)."""
        args = value_node.get('arguments', [])
        if len(args) < 2:
            raise Exception("Array function requires at least 2 arguments: size and element_type/init_value")

        array_size = self._resolve_shared_array_size(args[0])

        _ELEM_TYPES = {
            'semaphore': (ir.ArrayType(ir.IntType(8), 32),  32),
            'mutex':     (ir.ArrayType(ir.IntType(8), 40),  40),
            'barrier':   (ir.ArrayType(ir.IntType(8), 128), 128),
        }
        elem_node = args[1]
        fname = (elem_node.get('name') if isinstance(elem_node, dict) and
                 elem_node.get('type') == 'function_call' else None)
        if fname in _ELEM_TYPES:
            element_type = fname
            element_llvm_type, nbytes = _ELEM_TYPES[fname]
            zero_elem = ir.Constant(element_llvm_type, [ir.Constant(ir.IntType(8), 0)] * nbytes)
        else:
            element_type = 'int'
            element_llvm_type = ir.IntType(32)
            zero_elem = ir.Constant(element_llvm_type, 0)

        array_llvm_type = ir.ArrayType(element_llvm_type, array_size)
        g = ir.GlobalVariable(self.module, array_llvm_type, name=name)
        g.linkage = 'internal'
        g.initializer = ir.Constant(array_llvm_type, [zero_elem] * array_size)
        self.globals[name] = (g, f'array_{element_type}', False)
        debug_print(f"DEBUG: Created global array '{name}' with type 'array_{element_type}'")

    def _shared_decl_semaphore(self, name: str) -> None:
        """Declare a shared semaphore global (zero-initialised storage)."""
        ty = ir.ArrayType(ir.IntType(8), 32)
        g = ir.GlobalVariable(self.module, ty, name=f"{name}_storage")
        g.linkage = 'internal'
        g.initializer = ir.Constant(ty, [ir.Constant(ir.IntType(8), 0)] * 32)
        self.globals[name] = (g, 'semaphore', False)
        debug_print(f"DEBUG: Created global semaphore storage '{name}_storage'")

    def _shared_decl_mutex(self, name: str) -> None:
        """Declare a shared mutex global (zero-initialised storage)."""
        ty = ir.ArrayType(ir.IntType(8), 40)
        g = ir.GlobalVariable(self.module, ty, name=f"{name}_storage")
        g.linkage = 'internal'
        g.initializer = ir.Constant(ty, [ir.Constant(ir.IntType(8), 0)] * 40)
        self.globals[name] = (g, 'mutex', False)
        debug_print(f"DEBUG: Created global mutex storage '{name}_storage'")

    def _shared_decl_barrier(self, name: str) -> None:
        """Declare a shared barrier global (zero-initialised storage)."""
        ty = ir.ArrayType(ir.IntType(8), 128)
        g = ir.GlobalVariable(self.module, ty, name=f"{name}_storage")
        g.linkage = 'internal'
        g.initializer = ir.Constant(ty, [ir.Constant(ir.IntType(8), 0)] * 128)
        self.globals[name] = (g, 'barrier', False)
        debug_print(f"DEBUG: Created global barrier storage '{name}_storage'")

    def _shared_decl_queue(self, name: str, value_node) -> None:
        """Declare a shared queue global ([capacity, count, head, tail, buf…] as i32 array)."""
        capacity = 10
        if (isinstance(value_node, dict) and
                value_node.get('type') == 'function_call' and
                value_node.get('name') == 'queue'):
            qargs = value_node.get('arguments', [])
            if qargs and qargs[0].get('type') == 'literal':
                capacity = int(qargs[0]['value'])
        total = 4 + capacity
        ty = ir.ArrayType(ir.IntType(32), total)
        g = ir.GlobalVariable(self.module, ty, name=f"{name}_storage")
        g.linkage = 'internal'
        init = [ir.Constant(ir.IntType(32), 0)] * total
        init[0] = ir.Constant(ir.IntType(32), capacity)
        g.initializer = ir.Constant(ty, init)
        self.globals[name] = (g, 'queue', False)
        debug_print(f"DEBUG: Created global queue storage '{name}_storage' capacity={capacity}")

    def _shared_decl_variant(self, name: str, value_node) -> None:
        """Declare a shared variant global (null-initialised)."""
        from .base_types import get_variant_type
        variant_ty = get_variant_type()
        g = ir.GlobalVariable(self.module, variant_ty, name=name)
        g.linkage = 'internal'
        null_tag  = ir.Constant(ir.IntType(32), 8)
        null_data = ir.Constant(ir.ArrayType(ir.IntType(8), 16),
                                [ir.Constant(ir.IntType(8), 0)] * 16)
        g.initializer = ir.Constant(variant_ty, [null_tag, null_data])
        self.globals[name] = (g, 'variant', False)
        debug_print(f"DEBUG: Created global variant '{name}'")
        if value_node is not None:
            self.shared_runtime_inits.append((name, value_node))

    def _shared_decl_thread_array(self, name: str) -> None:
        """Create a placeholder global for a thread array (actual creation deferred to pass 2)."""
        from .base_types import get_type
        ty = get_type('int')
        g = ir.GlobalVariable(self.module, ty, name=name)
        g.linkage = 'internal'
        g.initializer = ir.Constant(ty, 0)
        self.globals[name] = (g, 'thread_array', False)
        debug_print(f"DEBUG: Placeholder global for thread_array '{name}'")

    def _shared_decl_scalar(self, name: str, var_type: str, value, is_constant: bool) -> None:
        """Declare a shared scalar (int/float/string/…) global."""
        from .base_types import get_type

        # Infer type from literal value when not explicit
        if var_type is None:
            raw = value['value'] if isinstance(value, dict) and value.get('type') == 'literal' else value
            if isinstance(raw, float):
                var_type = 'float'
            elif isinstance(raw, int):
                var_type = 'int'
            elif isinstance(raw, str):
                var_type = 'string'
            else:
                var_type = 'int'

        llvm_type = get_type(var_type)
        g = ir.GlobalVariable(self.module, llvm_type, name=name)
        g.linkage = 'common' if not is_constant else 'internal'
        if not is_constant:
            g.storage_class = 'default'

        if isinstance(value, dict) and value.get('type') == 'literal':
            g.initializer = ir.Constant(llvm_type, value['value'])
        elif value is not None and not isinstance(value, dict):
            g.initializer = ir.Constant(llvm_type, value)
        else:
            g.initializer = ir.Constant(llvm_type, 0)
            if isinstance(value, dict):
                self.shared_runtime_inits.append((name, value))
                debug_print(f"DEBUG: Added '{name}' to runtime init list")

        self.globals[name] = (g, var_type, is_constant)
        debug_print(f"DEBUG: Created shared scalar '{name}' type='{var_type}'")

    # ------------------------------------------------------------------
    # process_shared_declaration — dispatcher
    # ------------------------------------------------------------------

    def process_shared_declaration(self, node: Dict[str, Any]) -> None:
        """Process shared variable declarations that should be globally accessible."""
        debug_print(f"DEBUG: process_shared_declaration - Processing shared node: {node}")
        name = node['name']
        init = node['init']
        var_type = init.get('var_type')        # may be None → infer below
        value    = init.get('value')
        is_constant = node.get('const', False)
        debug_print(f"DEBUG: Shared declaration name={name}, type={var_type}, value={value}")

        # Shared arrays
        if (isinstance(value, dict) and
                value.get('type') == 'function_call' and
                value.get('name') == 'array'):
            self._shared_decl_array(name, value)
            return

        # Infer var_type from function_call when parser left it None
        if var_type is None and isinstance(value, dict) and value.get('type') == 'function_call':
            fname = value.get('name')
            if fname == 'semaphore':
                var_type = 'semaphore'
                args = value.get('arguments', [])
                value = args[0]['value'] if (args and args[0].get('type') == 'literal') else None
            elif fname == 'mutex':
                var_type = 'mutex'
                value = None
            elif fname in ('barrier', 'queue', 'variant'):
                var_type = fname
            elif fname == 'create_threads':
                var_type = 'thread_array'

        # Dispatch to per-type helper
        if var_type == 'semaphore':
            self._shared_decl_semaphore(name)
            return
        if var_type == 'mutex':
            self._shared_decl_mutex(name)
            return
        if var_type == 'barrier':
            self._shared_decl_barrier(name)
            return
        if var_type == 'queue':
            self._shared_decl_queue(name, value)
            return
        if var_type == 'variant':
            self._shared_decl_variant(name, value)
            return
        if var_type == 'thread_array':
            self._shared_decl_thread_array(name)
            return

        # Scalar (int, float, string, or inferred)
        self._shared_decl_scalar(name, var_type, value, is_constant)    
    def visit_procedure(self, node: Dict[str, Any]) -> None:
        # This method is now handled by the two-pass compilation
        # The actual compilation happens in compile_procedure_bodies
        pass

    def visit_function(self, node: Dict[str, Any]) -> None:
        # This method is now handled by the two-pass compilation
        # The actual compilation happens in compile_procedure_bodies
        pass

    # ------------------------------------------------------------------
    # Declaration helpers (each handles one var_type in visit_declaration)
    # ------------------------------------------------------------------

    def _decl_semaphore(self, name: str, shared: bool, is_constant: bool,
                         evaluated_value, raw_value) -> None:
        """Allocate / initialise a semaphore variable."""
        opaque_ty = ir.IntType(8).as_pointer()
        sem_init_fn = self._declare_external_fn(
            'sem_init', ir.IntType(32),
            [opaque_ty, ir.IntType(32), ir.IntType(32)])

        if shared:
            sem_storage, _, _ = self.globals[name]
            if self.current_function_name == 'main':
                sem_ptr = self.builder.bitcast(sem_storage, opaque_ty)
                init_int = (raw_value if isinstance(raw_value, int)
                            else evaluated_value if isinstance(evaluated_value, int)
                            else 0)
                debug_print(f"DEBUG: sem_init '{name}' with value {init_int}")
                self.builder.call(sem_init_fn, [sem_ptr,
                                                ir.Constant(ir.IntType(32), 0),
                                                ir.Constant(ir.IntType(32), init_int)])
        else:
            storage = self.builder.alloca(ir.ArrayType(ir.IntType(8), 32),
                                           name=f"{name}_storage")
            sem_ptr = self.builder.bitcast(storage, opaque_ty)
            self.locals[name] = (sem_ptr, 'semaphore', is_constant)
            if isinstance(evaluated_value, int):
                self.builder.call(sem_init_fn, [sem_ptr,
                                                ir.Constant(ir.IntType(32), 0),
                                                ir.Constant(ir.IntType(32), evaluated_value)])
            self.local_semaphores.append((name, sem_ptr))

    def _decl_mutex(self, name: str, shared: bool, is_constant: bool) -> None:
        """Allocate / initialise a mutex variable."""
        opaque_ty = ir.IntType(8).as_pointer()
        null_attr = ir.Constant(opaque_ty, None)
        mutex_init_fn = self._declare_external_fn(
            'pthread_mutex_init', ir.IntType(32), [opaque_ty, opaque_ty])

        if shared:
            mutex_storage, _, _ = self.globals[name]
            if self.current_function_name == 'main':
                mutex_ptr = self.builder.bitcast(mutex_storage, opaque_ty)
                self.builder.call(mutex_init_fn, [mutex_ptr, null_attr])
        else:
            storage = self.builder.alloca(ir.ArrayType(ir.IntType(8), 40),
                                           name=f"{name}_storage")
            mutex_ptr = self.builder.bitcast(storage, opaque_ty)
            self.locals[name] = (mutex_ptr, 'mutex', is_constant)
            self.builder.call(mutex_init_fn, [mutex_ptr, null_attr])
            self.local_mutexes.append((name, mutex_ptr))

    def _decl_barrier(self, name: str, shared: bool, is_constant: bool,
                       init_value_expr) -> None:
        """Allocate / initialise a barrier variable."""
        opaque_ty = ir.IntType(8).as_pointer()
        null_attr = ir.Constant(opaque_ty, None)
        barrier_init_fn = self._declare_external_fn(
            'pthread_barrier_init', ir.IntType(32),
            [opaque_ty, opaque_ty, ir.IntType(32)])

        # Determine participant count
        barrier_count = ir.Constant(ir.IntType(32), 1)
        if (isinstance(init_value_expr, dict) and
                init_value_expr.get('type') == 'function_call' and
                init_value_expr.get('name') == 'barrier'):
            bargs = init_value_expr.get('arguments', [])
            if bargs:
                try:
                    cnt = self._auto_extract_value(self.visit(bargs[0]), 'int')
                    if hasattr(cnt, 'type') and isinstance(cnt.type, ir.IntType) and cnt.type.width != 32:
                        cnt = (self.builder.trunc(cnt, ir.IntType(32))
                               if cnt.type.width > 32
                               else self.builder.zext(cnt, ir.IntType(32)))
                    barrier_count = cnt
                except Exception:
                    pass

        if shared:
            barrier_storage, _, _ = self.globals[name]
            if self.current_function_name == 'main':
                barrier_ptr = self.builder.bitcast(barrier_storage, opaque_ty)
                self.builder.call(barrier_init_fn, [barrier_ptr, null_attr, barrier_count])
        else:
            storage = self.builder.alloca(ir.ArrayType(ir.IntType(8), 128),
                                           name=f"{name}_storage")
            barrier_ptr = self.builder.bitcast(storage, opaque_ty)
            self.locals[name] = (barrier_ptr, 'barrier', is_constant)
            self.builder.call(barrier_init_fn, [barrier_ptr, null_attr, barrier_count])
            self.local_barriers.append((name, barrier_ptr))

    def _decl_queue(self, name: str, shared: bool, is_constant: bool,
                     init_value_expr) -> None:
        """Allocate / initialise a queue variable."""
        queue_capacity = 10  # default
        if (isinstance(init_value_expr, dict) and
                init_value_expr.get('type') == 'function_call' and
                init_value_expr.get('name') == 'queue'):
            qargs = init_value_expr.get('arguments', [])
            if qargs and isinstance(qargs[0], dict) and qargs[0].get('type') == 'literal':
                queue_capacity = int(qargs[0]['value'])

        total_words = 4 + queue_capacity
        if shared:
            queue_storage, _, _ = self.globals[name]
            queue_i32_ptr = self.builder.bitcast(queue_storage, ir.IntType(32).as_pointer())
            self.globals[name] = (queue_i32_ptr, 'queue', False)
        else:
            storage = self.builder.alloca(ir.ArrayType(ir.IntType(32), total_words),
                                           name=f"{name}_storage")
            zero = ir.Constant(ir.IntType(32), 0)
            queue_ptr = self.builder.gep(storage, [zero, zero])
            self.builder.store(ir.Constant(ir.IntType(32), queue_capacity), queue_ptr)
            for field_idx in (1, 2, 3):  # count, head, tail
                fptr = self.builder.gep(storage, [zero, ir.Constant(ir.IntType(32), field_idx)])
                self.builder.store(ir.Constant(ir.IntType(32), 0), fptr)
            self.locals[name] = (queue_ptr, 'queue', is_constant)

    def _decl_variant_local(self, name: str, is_constant: bool,
                             evaluated_value, raw_value) -> None:
        """Allocate a local variant variable and initialise it."""
        from .base_types import (get_variant_type, get_variant_type_tag_enum,
                                  get_type_tag_for_value, get_raw_type)
        variant_ty = get_variant_type()
        variable = self.builder.alloca(variant_ty, name=name)
        self.locals[name] = (variable, 'variant', is_constant)

        value_type = None
        if evaluated_value is not None:
            type_tag = get_type_tag_for_value(evaluated_value, 'variant')
            self._store_variant_value(variable, evaluated_value, type_tag, 'variant')
            if hasattr(evaluated_value, 'type'):
                if isinstance(evaluated_value.type, ir.DoubleType):
                    value_type = 'float'
                elif isinstance(evaluated_value.type, ir.IntType):
                    value_type = 'int'
                elif (isinstance(evaluated_value.type, ir.PointerType) and
                      str(evaluated_value.type.pointee) == 'i8'):
                    value_type = 'string'
        elif raw_value is not None:
            llvm_val = ir.Constant(get_raw_type('int'), raw_value) if isinstance(raw_value, int) else \
                       ir.Constant(get_raw_type('float'), raw_value) if isinstance(raw_value, float) else None
            if llvm_val is not None:
                type_tag = get_type_tag_for_value(llvm_val, 'variant')
                self._store_variant_value(variable, llvm_val, type_tag, 'variant')
                value_type = 'float' if isinstance(raw_value, float) else 'int'
            else:
                self._store_null_variant(variable)
                value_type = 'string' if isinstance(raw_value, str) else 'null'
        else:
            self._store_null_variant(variable)
            value_type = 'null'

        if value_type:
            self.var_types[name] = value_type
            debug_print(f"DEBUG: visit_declaration - tracked type for '{name}': {value_type}")

    def _infer_array_element_type(self, init_value_expr) -> str:
        """Return the element type string for an array() call init expression."""
        args = init_value_expr.get('arguments', []) if isinstance(init_value_expr, dict) else []
        if len(args) < 2:
            return 'int'
        elem = args[1]
        if not isinstance(elem, dict):
            return 'int'
        if elem.get('type') == 'function_call':
            name = elem.get('name')
            if name in ('semaphore', 'mutex', 'barrier', 'thread'):
                return name
        if elem.get('type') == 'literal' and elem.get('value') in ('thread', '"thread"'):
            return 'thread'
        return 'int'

    # ------------------------------------------------------------------
    # visit_declaration — dispatch to per-type helpers
    # ------------------------------------------------------------------

    def visit_declaration(self, node: Dict[str, Any]) -> None:
        debug_print(f"DEBUG: visit_declaration - Processing node: {node}")
        name = node['name']
        shared = node['shared']
        is_constant = node.get('const', False)

        # --- Shared declarations: mostly already handled in pass 1 ---
        if shared and name in self.globals:
            _, var_type, _ = self.globals[name]
            if var_type in ('semaphore', 'mutex', 'barrier') and self.current_function_name == 'main':
                pass  # fall through for runtime init below
            elif var_type == 'thread_array':
                init = node['init']
                val = init.get('value', {})
                if isinstance(val, dict) and val.get('type') == 'function_call' and val.get('name') == 'create_threads':
                    self.visit(val)
                return
            else:
                return

        init = node['init']
        assignment_op = init.get('assignment_op')
        if assignment_op is not None:
            if is_constant and assignment_op != '=':
                raise Exception(f"Constants must use '=' not '{assignment_op}' in declaration of '{name}'.")
            if not is_constant and assignment_op != ':=':
                raise Exception(f"Mutable variables must use ':=' not '{assignment_op}' in declaration of '{name}'.")

        init_value_expr = init.get('value')
        var_type = init.get('var_type')

        # --- Determine type and (for primitive types) evaluate the init expr ---
        evaluated_value = None
        raw_value = None

        _SPECIAL_TYPES = {'mutex', 'semaphore', 'barrier', 'queue',
                          'create_threads', 'create_thread'}

        if isinstance(init_value_expr, dict) and init_value_expr.get('type') == 'function_call':
            fname = init_value_expr.get('name')
            if fname == 'mutex':
                var_type = 'mutex'
            elif fname == 'semaphore':
                var_type = 'semaphore'
                args = init_value_expr.get('arguments', [])
                raw_value = args[0]['value'] if args and args[0].get('type') == 'literal' else None
                evaluated_value = raw_value if isinstance(raw_value, int) else 0
            elif fname == 'barrier':
                var_type = 'barrier'
            elif fname == 'queue':
                var_type = 'queue'
            elif fname == 'variant':
                var_type = 'variant'
            elif fname == 'create_threads':
                var_type = 'thread_array'
                evaluated_value = self.visit(init_value_expr)
            elif fname == 'create_thread':
                var_type = 'thread'
                evaluated_value = self.visit(init_value_expr)
            elif fname == 'array':
                var_type = 'array'
                evaluated_value = self.visit(init_value_expr)
            else:
                evaluated_value = self.visit(init_value_expr)
        elif init_value_expr is not None:
            evaluated_value = self.visit(init_value_expr)
            raw_value = init_value_expr.get('value') if isinstance(init_value_expr, dict) else None

        # Default to variant for untyped variables
        if var_type is None:
            var_type = 'variant'

        # --- Dispatch to per-type handler ---
        if var_type == 'semaphore':
            self._decl_semaphore(name, shared, is_constant, evaluated_value, raw_value)
            return
        if var_type == 'mutex':
            self._decl_mutex(name, shared, is_constant)
            return
        if var_type == 'barrier':
            self._decl_barrier(name, shared, is_constant, init_value_expr)
            return
        if var_type == 'queue':
            self._decl_queue(name, shared, is_constant, init_value_expr)
            return

        # Shared variant: already initialised in pass 1
        if var_type == 'variant' and shared:
            return

        if var_type == 'variant':
            self._decl_variant_local(name, is_constant, evaluated_value, raw_value)
            return

        if var_type == 'array':
            element_type = self._infer_array_element_type(init_value_expr)
            self.locals[name] = (evaluated_value, f'array_{element_type}', is_constant)
            return

        if var_type == 'thread_array':
            if evaluated_value is None:
                raise Exception(f"thread_array '{name}' must be initialised with create_threads()")
            self.locals[name] = (evaluated_value, 'thread_array', is_constant)
            return

        if var_type == 'thread':
            if evaluated_value is not None:
                self.locals[name] = (evaluated_value, 'thread', is_constant)
            return

        # Generic typed variable (int, float, string, …)
        from .base_types import get_type as _get_type
        llvm_type = _get_type(var_type)
        variable = self.builder.alloca(llvm_type, name=name)
        if evaluated_value is not None:
            self.builder.store(evaluated_value, variable)
        elif raw_value is not None:
            self.builder.store(ir.Constant(llvm_type, raw_value), variable)
        self.locals[name] = (variable, var_type, is_constant)

    def _store_value_to_variant(self, ptr: ir.Value, value: ir.Value) -> None:
        """Store an LLVM value into a variant pointer, inferring the type. Delegates to variant_utils."""
        variant_utils.store_value_to_variant(self.builder, self.module, ptr, value)

    def _extract_for_array_type(self, value: ir.Value, array_type: str) -> ir.Value:
        """Extract the concrete element from a variant to match *array_type*. Delegates to variant_utils."""
        return variant_utils.extract_for_array_type(self.builder, self.module, value, array_type)

    def visit_assignment(self, node: Dict[str, Any]) -> None:
        debug_print(f"DEBUG: visit_assignment - Processing assignment: {node}")
        target = node['target']
        value = self.visit(node['value'])

        if isinstance(target, str):
            # Simple variable assignment
            entry = self.get_variable(target)
            if entry is None:
                self.semantic_error(f"undefined variable '{target}' in assignment", node)
            ptr, dtype, is_constant = entry
            if is_constant:
                raise Exception(f"Cannot assign to constant variable '{target}'.")

            if dtype == 'variant':
                if hasattr(value, 'type'):
                    self._store_value_to_variant(ptr, value)
                else:
                    self._store_null_variant(ptr)
            else:
                # If the target is a typed (int/float) variable but value is a variant,
                # extract the concrete type before storing.
                if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
                    target_pointee = ptr.type.pointee
                    if isinstance(target_pointee, ir.IntType):
                        value = self._auto_extract_value(value, 'int')
                    elif isinstance(target_pointee, ir.DoubleType):
                        value = self._auto_extract_value(value, 'float')
                if self.is_shared_mutable_variable(target):
                    self.insert_yield()
                    size = (value.type.width // 8
                            if hasattr(value, 'type') and isinstance(value.type, ir.IntType)
                            else 8 if hasattr(value, 'type') and isinstance(value.type, ir.DoubleType)
                            else 4)
                    self.insert_tsan_call(ptr, size, is_write=True)
                self.builder.store(value, ptr)
                if self.is_shared_mutable_variable(target):
                    self.insert_yield()

        elif isinstance(target, dict) and target['type'] == 'array_access':
            array_name = target['array']
            index = self.visit(target['index'])

            entry = self.get_variable(array_name)
            if entry is None:
                raise Exception(f"Undefined array in assignment: {array_name}")
            array_ptr, array_type, is_constant = entry
            if is_constant:
                raise Exception(f"Cannot assign to constant array '{array_name}'.")

            # Unwrap variant index
            if hasattr(index, 'type'):
                from .base_types import get_variant_type
                variant_ty = get_variant_type()
                if index.type == variant_ty:
                    tmp = self.builder.alloca(variant_ty, name="tmp_idx")
                    self.builder.store(index, tmp)
                    index = self._extract_variant_value(tmp, 'int')
                elif isinstance(index.type, ir.PointerType) and index.type.pointee == variant_ty:
                    index = self._extract_variant_value(index, 'int')

            element_ptr = self.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), index])

            # Coerce value from variant if needed
            if hasattr(value, 'type'):
                value = self._extract_for_array_type(value, array_type)

            # Thread arrays: unwrap i8** → i8*
            if array_type == 'array_thread' and hasattr(value, 'type'):
                if isinstance(value.type, ir.PointerType) and isinstance(value.type.pointee, ir.PointerType):
                    value = self.builder.load(value)

            debug_print(f"DEBUG: Array assignment - store value={value} → {element_ptr}")
            self.builder.store(value, element_ptr)
        else:
            raise Exception(f"Unsupported assignment target type: {target}")

    def visit_literal(self, node: Dict[str, Any]) -> ir.Constant:
        debug_print(f"DEBUG: visit_literal - Processing node: {node}")
        v = node['value']
        if isinstance(v, int):
            return ir.Constant(ir.IntType(32), v)
        if isinstance(v, float):
            return ir.Constant(ir.DoubleType(), v)
        if isinstance(v, str):
            # Variable reference masquerading as a literal (parser quirk)
            if v in self.locals or v in self.globals:
                debug_print(f"DEBUG: visit_literal - '{v}' found as variable, delegating to visit_ID")
                return self.visit_ID({'type': 'ID', 'value': v})
            # True string literal → global constant + i8* pointer
            str_name = f"str_{abs(hash(v))}"
            str_bytes = bytearray(v.encode("utf8")) + b"\x00"
            str_type = ir.ArrayType(ir.IntType(8), len(str_bytes))
            if str_name in self.module.globals:
                str_global = self.module.get_global(str_name)
            else:
                str_global = ir.GlobalVariable(self.module, str_type, name=str_name)
                str_global.linkage = 'internal'
                str_global.global_constant = True
                str_global.initializer = ir.Constant(str_type, str_bytes)
            return self.builder.bitcast(str_global, ir.IntType(8).as_pointer())
        raise Exception(f"Unsupported literal type: {type(v)} with value {v}")

    def visit_binary_op(self, node: Dict[str, Any]) -> ir.Value:
        op = node['op']
        debug_print(f"DEBUG: visit_binary_op - op: {op}")

        from .base_types import get_variant_type
        variant_ty = get_variant_type()

        # ---- Determine float vs int mode from AST (before visiting) ----
        bitwise_ops = {'&', '|', 'xor', '<<', '>>', '~'}
        operation_type = 'int'
        if op not in bitwise_ops:
            for ast_node in (node['left'], node['right']):
                if isinstance(ast_node, dict):
                    if ast_node.get('type') == 'ID':
                        if self.var_types.get(ast_node.get('value')) == 'float':
                            operation_type = 'float'
                    elif ast_node.get('type') == 'literal':
                        v = ast_node.get('value')
                        if isinstance(v, float):
                            operation_type = 'float'
                        elif isinstance(v, str) and self.var_types.get(v) == 'float':
                            operation_type = 'float'

        left_raw  = self.visit(node['left'])
        right_raw = self.visit(node['right'])

        # Override to float if the computed values are already doubles
        if hasattr(left_raw,  'type') and isinstance(left_raw.type,  ir.DoubleType):
            operation_type = 'float'
        if hasattr(right_raw, 'type') and isinstance(right_raw.type, ir.DoubleType):
            operation_type = 'float'

        left  = self._auto_extract_value(left_raw,  operation_type)
        right = self._auto_extract_value(right_raw, operation_type)

        # Coerce both operands to double when doing float arithmetic
        if operation_type == 'float':
            if hasattr(left,  'type') and isinstance(left.type,  ir.IntType):
                left  = self.builder.sitofp(left,  ir.DoubleType())
            if hasattr(right, 'type') and isinstance(right.type, ir.IntType):
                right = self.builder.sitofp(right, ir.DoubleType())

        debug_print(f"DEBUG: visit_binary_op op={op} op_type={operation_type} "
                    f"left={getattr(left,'type','?')} right={getattr(right,'type','?')}")

        # ---- Arithmetic: dispatch table ----
        _INT_OPS = {'+': 'add', '-': 'sub', '*': 'mul', '/': 'sdiv',
                    '#': 'sdiv', '%': 'srem', 'mod': 'srem'}
        _FLT_OPS = {'+': 'fadd', '-': 'fsub', '*': 'fmul', '/': 'fdiv',
                    '%': 'frem', 'mod': 'frem'}

        if op in _FLT_OPS and operation_type == 'float':
            return getattr(self.builder, _FLT_OPS[op])(left, right)
        if op in _INT_OPS and operation_type == 'int':
            return getattr(self.builder, _INT_OPS[op])(left, right)

        # '#' in float mode: convert to int first, then sdiv
        if op == '#' and operation_type == 'float':
            return self.builder.sdiv(self.builder.fptosi(left, ir.IntType(32)),
                                     self.builder.fptosi(right, ir.IntType(32)))

        # ---- Exponentiation ----
        if op == '^':
            pow_fn = self._declare_external_fn('pow', ir.DoubleType(),
                                               [ir.DoubleType(), ir.DoubleType()])
            lf = left  if operation_type == 'float' else self.builder.sitofp(left,  ir.DoubleType())
            rf = right if operation_type == 'float' else self.builder.sitofp(right, ir.DoubleType())
            res = self.builder.call(pow_fn, [lf, rf])
            return res if operation_type == 'float' else self.builder.fptosi(res, ir.IntType(32))

        # ---- Bitwise ----
        _BIT_OPS = {'&': 'and_', '|': 'or_', 'xor': 'xor', '<<': 'shl', '>>': 'ashr'}
        if op in _BIT_OPS:
            return getattr(self.builder, _BIT_OPS[op])(left, right)

        # ---- Comparisons ----
        _CMP_MAP = {'=': '==', '==': '==', '!=': '!=',
                    '<': '<', '<=': '<=', '>': '>', '>=': '>='}
        if op in _CMP_MAP:
            pred = _CMP_MAP[op]
            if hasattr(left, 'type') and isinstance(left.type, ir.IntType) and left.type.width < 32:
                left  = self.builder.sext(left,  ir.IntType(32))
            if hasattr(right, 'type') and isinstance(right.type, ir.IntType) and right.type.width < 32:
                right = self.builder.sext(right, ir.IntType(32))
            if hasattr(left, 'type') and left.type != right.type:
                raise Exception(f"Type mismatch in comparison: {left.type} vs {right.type}")
            if hasattr(left, 'type') and isinstance(left.type, ir.PointerType):
                raise Exception("Direct pointer comparison is not supported.")
            cmp = (self.builder.fcmp_ordered(pred, left, right)
                   if operation_type == 'float'
                   else self.builder.icmp_signed(pred, left, right))
            return self.builder.zext(cmp, ir.IntType(32))

        # ---- Logical and / or ----
        if op in ('and', 'or'):
            def to_bool(v):
                if operation_type == 'float':
                    return self.builder.fcmp_ordered('!=', v, ir.Constant(ir.DoubleType(), 0.0))
                return self.builder.icmp_signed('!=', v, ir.Constant(v.type, 0))
            lb, rb = to_bool(left), to_bool(right)
            comb = self.builder.and_(lb, rb) if op == 'and' else self.builder.or_(lb, rb)
            return self.builder.zext(comb, ir.IntType(32))

        raise Exception(f"Unsupported operator: {op}")

    def visit_unary_op(self, node: Dict[str, Any]) -> ir.Value:
        """Handle unary operators like unary minus, logical NOT, bitwise NOT"""
        operand_raw = self.visit(node['operand'])
        op = node['op']
        
        # Auto-extract the operand value
        operand = self._auto_extract_value(operand_raw, 'auto')
        
        if op == '-':
            # Unary minus
            if hasattr(operand, 'type'):
                if isinstance(operand.type, ir.DoubleType):
                    # Float negation: -x = 0.0 - x
                    zero = ir.Constant(ir.DoubleType(), 0.0)
                    return self.builder.fsub(zero, operand)
                elif isinstance(operand.type, ir.IntType):
                    # Integer negation: -x = 0 - x
                    zero = ir.Constant(operand.type, 0)
                    return self.builder.sub(zero, operand)
                else:
                    raise Exception(f"Unsupported type for unary minus: {operand.type}")
            else:
                raise Exception("Operand for unary minus has no type information")
        elif op == 'not':
            # Logical NOT: not x = (x == 0)
            # Returns 1 if operand is 0, returns 0 otherwise
            if hasattr(operand, 'type') and isinstance(operand.type, ir.IntType):
                zero = ir.Constant(operand.type, 0)
                result_bool = self.builder.icmp_signed('==', operand, zero)
                return self.builder.zext(result_bool, ir.IntType(32))
            else:
                raise Exception(f"Unsupported type for logical NOT: {operand.type if hasattr(operand, 'type') else 'unknown'}")
        elif op == '~':
            # Bitwise NOT: ~x
            if hasattr(operand, 'type') and isinstance(operand.type, ir.IntType):
                # In LLVM, bitwise NOT is done as XOR with all 1s (-1)
                all_ones = ir.Constant(operand.type, -1)
                return self.builder.xor(operand, all_ones)
            else:
                raise Exception(f"Unsupported type for bitwise NOT: {operand.type if hasattr(operand, 'type') else 'unknown'}")
        else:
            raise Exception(f"Unsupported unary operator: {op}")

    def visit_body(self, node: List[Dict[str, Any]]) -> None:
        self.visit(node)

    def visit_if(self, node: Dict[str, Any]) -> None:
        cond_val = self._auto_extract_value(self.visit(node['condition']), 'int')
        # Convert i32/i8 condition to i1
        if hasattr(cond_val, 'type') and isinstance(cond_val.type, ir.IntType) and cond_val.type.width != 1:
            cond_val = self.builder.icmp_signed('!=', cond_val, ir.Constant(cond_val.type, 0))
        then_bb = self.builder.append_basic_block('then')
        else_bb = self.builder.append_basic_block('else') if 'else_body' in node else None
        end_bb = self.builder.append_basic_block('endif')
        if else_bb:
            self.builder.cbranch(cond_val, then_bb, else_bb)
        else:
            self.builder.cbranch(cond_val, then_bb, end_bb)
        # Then block
        self.builder.position_at_start(then_bb)
        self.visit(node['then_body'])
        if not self.builder.block.is_terminated:
            self.builder.branch(end_bb)
        # Else block
        if else_bb:
            self.builder.position_at_start(else_bb)
            self.visit(node['else_body'])
            if not self.builder.block.is_terminated:
                self.builder.branch(end_bb)
        # End block
        self.builder.position_at_start(end_bb)

    def visit_case(self, node: Dict[str, Any]) -> None:
        # Evaluate the switch expression; unwrap variant if needed
        val = self._auto_extract_value(self.visit(node['expression']), 'int')
        if not hasattr(val, 'type'):
            self.semantic_error("case expression must evaluate to an integer or char value", node)

        # Coerce to i32 for the LLVM switch instruction
        if isinstance(val.type, ir.IntType) and val.type.width != 32:
            val = self.builder.zext(val, ir.IntType(32)) if val.type.width < 32 else self.builder.trunc(val, ir.IntType(32))

        arms = node.get('arms', [])
        default_body = node.get('default_body')

        end_bb = self.builder.append_basic_block('case.end')
        default_bb = self.builder.append_basic_block('case.default') if default_body else end_bb

        # Build arm blocks
        arm_bbs = [self.builder.append_basic_block(f'case.arm.{i}') for i in range(len(arms))]

        # Emit LLVM switch instruction
        sw = self.builder.switch(val, default_bb)
        for i, arm in enumerate(arms):
            arm_val = self.visit(arm['value'])
            if not isinstance(arm_val, ir.Constant):
                self.semantic_error("case arm value must be a compile-time constant (literal)", node)
            arm_const = ir.Constant(ir.IntType(32), arm_val.constant)
            sw.add_case(arm_const, arm_bbs[i])

        # Emit arm bodies
        for i, arm in enumerate(arms):
            self.builder.position_at_start(arm_bbs[i])
            self.visit(arm['body'])
            if not self.builder.block.is_terminated:
                self.builder.branch(end_bb)

        # Emit default body
        if default_body:
            self.builder.position_at_start(default_bb)
            self.visit(default_body)
            if not self.builder.block.is_terminated:
                self.builder.branch(end_bb)

        self.builder.position_at_start(end_bb)

    def visit_break(self, node: Dict[str, Any]) -> None:
        if not self.loop_exit_stack:
            raise Exception("'break' used outside of a loop")
        self.builder.branch(self.loop_exit_stack[-1])
        # Append an unreachable block so the builder has somewhere to emit
        # any subsequent instructions without corrupting the IR
        dead_bb = self.builder.append_basic_block('break.dead')
        self.builder.position_at_start(dead_bb)

    def visit_while(self, node: Dict[str, Any]) -> None:
        cond_bb = self.builder.append_basic_block('while.cond')
        body_bb = self.builder.append_basic_block('while.body')
        end_bb = self.builder.append_basic_block('while.end')
        self.builder.branch(cond_bb)
        self.builder.position_at_start(cond_bb)
        cond_val = self._auto_extract_value(self.visit(node['condition']), 'int')

        # Convert condition to i1 if it's i32 (from comparison operators)
        if hasattr(cond_val, 'type') and isinstance(cond_val.type, ir.IntType) and cond_val.type.width != 1:
            cond_val = self.builder.icmp_signed('!=', cond_val, ir.Constant(ir.IntType(32), 0))
        
        self.builder.cbranch(cond_val, body_bb, end_bb)
        self.builder.position_at_start(body_bb)
        self.loop_exit_stack.append(end_bb)
        self.visit(node['body'])
        self.loop_exit_stack.pop()
        if not self.builder.block.is_terminated:
            self.builder.branch(cond_bb)
        self.builder.position_at_start(end_bb)

    def visit_for(self, node: Dict[str, Any]) -> None:
        # Only support integer for-loops: for i := start to end
        var = node['iterator']
        start = self._auto_extract_value(self.visit(node['start']), 'int')
        end   = self._auto_extract_value(self.visit(node['end']),   'int')
        ptr = self.builder.alloca(ir.IntType(32), name=var)
        self.locals[var] = (ptr, 'int', False)  # for loop variables are mutable
        self.builder.store(start, ptr)
        cond_bb = self.builder.append_basic_block('for.cond')
        body_bb = self.builder.append_basic_block('for.body')
        end_bb = self.builder.append_basic_block('for.end')
        self.builder.branch(cond_bb)
        self.builder.position_at_start(cond_bb)
        idx = self.builder.load(ptr)
        cond = self.builder.icmp_signed('<', idx, end)
        self.builder.cbranch(cond, body_bb, end_bb)
        self.builder.position_at_start(body_bb)
        self.loop_exit_stack.append(end_bb)
        self.visit(node['body'])
        self.loop_exit_stack.pop()
        if not self.builder.block.is_terminated:
            idx = self.builder.load(ptr)
            next_idx = self.builder.add(idx, ir.Constant(ir.IntType(32), 1))
            self.builder.store(next_idx, ptr)
            self.builder.branch(cond_bb)
        self.builder.position_at_start(end_bb)

    def visit_print(self, node: Dict[str, Any]) -> None:
        expression = node.get('expression')
        format_str = node.get('format')
        debug_print(f"DEBUG: visit_print - expression: {expression}, format: {format_str}")

        # --- Template string in the 'format' field (from parser) ---
        if format_str and isinstance(format_str, str) and format_str.startswith('`') and format_str.endswith('`'):
            val, is_string = self._emit_template_sprintf(format_str[1:-1])

        # --- Template string in the 'expression' field as a raw string ---
        elif (isinstance(expression, str) and
              expression.startswith('`') and expression.endswith('`')):
            val, is_string = self._emit_template_sprintf(expression[1:-1])

        # --- Template string in a literal node ---
        elif (isinstance(expression, dict) and
              expression.get('type') == 'literal' and
              isinstance(expression.get('value'), str) and
              expression['value'].startswith('`') and expression['value'].endswith('`')):
            val, is_string = self._emit_template_sprintf(expression['value'][1:-1])

        else:
            # Regular expression (variable, arithmetic, literal, …)
            val = self.visit(expression)
            is_string = (isinstance(expression, dict) and
                         expression.get('type') == 'literal' and
                         isinstance(expression.get('value'), str))
        
        # Create format string
        if is_string:
            fmt = "%s\n\0".replace('\\n', '\n')
        else:
            fmt = "%d\n\0".replace('\\n', '\n')
        fmt_bytes = bytearray(fmt.encode("utf8"))
        fmt_type = ir.ArrayType(ir.IntType(8), len(fmt_bytes))
        fmt_name = f"fmt_{'str' if is_string else 'int'}"
        if fmt_name in self.module.globals:
            fmt_global = self.module.get_global(fmt_name)
        else:
            fmt_global = ir.GlobalVariable(self.module, fmt_type, name=fmt_name)
            fmt_global.linkage = 'internal'
            fmt_global.global_constant = True
            fmt_global.initializer = ir.Constant(fmt_type, fmt_bytes)
        fmt_arg = self.builder.bitcast(fmt_global, ir.IntType(8).as_pointer())
        
        # Get or create printf function
        printf = self.module.globals.get('printf')
        if not printf:
            voidptr_ty = ir.IntType(8).as_pointer()
            printf_ty = ir.FunctionType(ir.IntType(32), [voidptr_ty], var_arg=True)
            printf = ir.Function(self.module, printf_ty, name="printf")
        
        # Ensure val is an LLVM value, not a Python string
        if isinstance(val, str):
            debug_print(f"DEBUG: visit_print - ERROR: val is still a Python string: {val}")
            raise Exception(f"visit_print received a Python string instead of LLVM value: {val}")
        
        debug_print(f"DEBUG: visit_print - calling printf with fmt_arg: {fmt_arg}, val: {val}")
        self.builder.call(printf, [fmt_arg, val])

    def visit_scan(self, node: Dict[str, Any]) -> None:
        """Handle SCAN formatted input statements.
        Syntax supported: SCAN `Prompt text {var1} {var2}`
        - Prints the prompt text (text outside of {...})
        - Calls scanf with "%d" specifiers for each variable placeholder
        - Stores the read integers into the provided variables
        """
        import re
        fmt = node.get('format')
        if not isinstance(fmt, str):
            raise Exception(f"SCAN expects a formatted string, got: {fmt}")

        # Extract template between backticks if present
        template = fmt
        if template.startswith('`') and template.endswith('`'):
            template = template[1:-1]
        debug_print(f"DEBUG: visit_scan - template: {template}")

        # Find variables in {var} placeholders
        var_names = re.findall(r'\{([^}]+)\}', template)
        debug_print(f"DEBUG: visit_scan - variables: {var_names}")

        # Build and print prompt text (template with placeholders removed)
        prompt_text = re.sub(r'\{[^}]+\}', '', template)
        prompt_text = prompt_text.rstrip()
        debug_print(f"DEBUG: visit_scan - prompt_text: '{prompt_text}'")

        if prompt_text:
            # Create a string constant for the prompt (no newline)
            name = f"str_{abs(hash('scan_prompt:' + prompt_text))}"
            str_bytes = bytearray(prompt_text.encode("utf8")) + b"\00"
            str_type = ir.ArrayType(ir.IntType(8), len(str_bytes))
            if name in self.module.globals:
                str_global = self.module.get_global(name)
            else:
                str_global = ir.GlobalVariable(self.module, str_type, name=name)
                str_global.linkage = 'internal'
                str_global.global_constant = True
                str_global.initializer = ir.Constant(str_type, str_bytes)
            prompt_ptr = self.builder.bitcast(str_global, ir.IntType(8).as_pointer())

            # Declare or get printf
            printf = self.module.globals.get('printf')
            if not printf:
                voidptr_ty = ir.IntType(8).as_pointer()
                printf_ty = ir.FunctionType(ir.IntType(32), [voidptr_ty], var_arg=True)
                printf = ir.Function(self.module, printf_ty, name="printf")

            # Print the prompt without newline
            self.builder.call(printf, [prompt_ptr])

        # If there are no variables, nothing else to scan
        if not var_names:
            return

        # Determine per-variable scanf format specifiers and validate types
        format_specs = []
        for var_name in var_names:
            entry = self.get_variable(var_name, prefer_globals=True)
            if entry is None:
                self.semantic_error(f"undefined variable '{var_name}' in scan statement", node)
            var_ptr, dtype, is_constant = entry
            debug_print(f"DEBUG: visit_scan - var '{var_name}' ptr type: {getattr(var_ptr, 'type', None)}, dtype: {dtype}")
            if not hasattr(var_ptr, 'type') or not isinstance(var_ptr.type, ir.PointerType):
                self.semantic_error(f"variable '{var_name}' is not addressable for scan statement", node)
            if dtype == 'int':
                format_specs.append('%d')
            elif dtype == 'float':
                format_specs.append('%lf')
            elif dtype == 'char':
                format_specs.append(' %c')
            elif dtype == 'string':
                format_specs.append('%255s')
            else:
                self.semantic_error(f"scan does not support type '{dtype}' for variable '{var_name}'", node)

        # Build scanf format string
        scanf_format = ' '.join(format_specs) + '\0'
        fmt_name = f"str_{abs(hash('scan_format:' + scanf_format))}"
        fmt_bytes = bytearray(scanf_format.encode("utf8"))
        fmt_type = ir.ArrayType(ir.IntType(8), len(fmt_bytes))
        if fmt_name in self.module.globals:
            fmt_global = self.module.get_global(fmt_name)
        else:
            fmt_global = ir.GlobalVariable(self.module, fmt_type, name=fmt_name)
            fmt_global.linkage = 'internal'
            fmt_global.global_constant = True
            fmt_global.initializer = ir.Constant(fmt_type, fmt_bytes)
        fmt_ptr = self.builder.bitcast(fmt_global, ir.IntType(8).as_pointer())

        # Resolve variable pointers for scanf arguments
        scanf_args: List[ir.Value] = [fmt_ptr]
        string_buffers = {}  # var_name -> (var_ptr, buf_ptr) for post-scan pointer update
        for var_name in var_names:
            entry = self.get_variable(var_name, prefer_globals=True)
            var_ptr, dtype, is_constant = entry
            if dtype == 'int':
                scanf_args.append(var_ptr)
            elif dtype == 'float':
                scanf_args.append(var_ptr)
            elif dtype == 'char':
                scanf_args.append(var_ptr)
            elif dtype == 'string':
                # Allocate a mutable buffer for scanf, then store its pointer in the variable
                buf_ty = ir.ArrayType(ir.IntType(8), 256)
                buf = self.builder.alloca(buf_ty, name=f"scan_buf_{var_name}")
                buf_ptr = self.builder.bitcast(buf, ir.IntType(8).as_pointer())
                string_buffers[var_name] = (var_ptr, buf_ptr)
                scanf_args.append(buf_ptr)

        # Declare or get scanf
        scanf = self.module.globals.get('scanf')
        if not scanf:
            scanf_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()], var_arg=True)
            scanf = ir.Function(self.module, scanf_ty, name="scanf")

        # Call scanf and capture the return value (number of items successfully read)
        debug_print(f"DEBUG: visit_scan - calling scanf with {len(scanf_args)-1} variables")
        scan_result = self.builder.call(scanf, scanf_args)

        # Update string variable pointers to point at the scanned buffers
        for var_name, (var_ptr, buf_ptr) in string_buffers.items():
            self.builder.store(buf_ptr, var_ptr)

        # Return (result > 0) as i32 so scan can be used as a while-loop condition.
        # scanf returns the number of items read (>0 = success, 0 = no match, -1 = EOF).
        # Returning 1 on success and 0 otherwise makes it safe to use in a boolean context.
        pos = self.builder.icmp_signed('>', scan_result, ir.Constant(ir.IntType(32), 0))
        return self.builder.zext(pos, ir.IntType(32))

    def visit_ID(self, node: Dict[str, Any], prefer_globals: bool = False) -> ir.Value:
        name = node['value']
        debug_print(f"DEBUG: visit_ID searching for '{name}', prefer_globals={prefer_globals}")
        entry = self.get_variable(name, prefer_globals)
        if entry is None:
            self.semantic_error(f"undefined variable '{name}'", node)

        ptr, dtype, is_constant = entry
        debug_print(f"DEBUG: visit_ID for '{name}', dtype={dtype}, ptr type={getattr(ptr, 'type', None)}")

        # Opaque C types stored as raw byte arrays — bitcast to i8* on every access
        if dtype in ('semaphore', 'mutex', 'barrier'):
            if (hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType) and
                    isinstance(ptr.type.pointee, ir.ArrayType) and
                    ptr.type.pointee.element == ir.IntType(8)):
                return self.builder.bitcast(ptr, ir.IntType(8).as_pointer())
            return ptr

        if dtype == 'thread':
            if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
                return self.builder.load(ptr)
            return ptr

        if dtype == 'variant':
            return ptr

        if dtype == 'string':
            return ptr

        if dtype in ('int', 'float'):
            if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
                is_shared = self.is_shared_mutable_variable(name)
                if is_shared:
                    self.insert_yield()
                    self.insert_tsan_call(ptr, 4 if dtype == 'int' else 8, is_write=False)
                loaded = self.builder.load(ptr)
                if is_shared:
                    self.insert_yield()
                return loaded
            return ptr

        if dtype is not None:
            if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
                return self.builder.load(ptr)
            return ptr

        # Fallback: dtype is None — infer from pointer shape
        if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
            pointee = ptr.type.pointee
            if pointee == ir.IntType(8):
                return ptr
            if isinstance(pointee, ir.PointerType) and pointee.pointee == ir.IntType(8):
                return self.builder.load(ptr)
            if isinstance(pointee, (ir.IntType, ir.DoubleType)):
                return self.builder.load(ptr)
        return ptr

    # ------------------------------------------------------------------
    # visit_func_call helpers — one method per heavy built-in
    # ------------------------------------------------------------------

    def _handle_create_thread(self, node: Dict[str, Any]) -> ir.Value:
        """Handle create_thread(func, arg1, …) built-in."""
        target_func_arg = node['arguments'][0]
        target_func = target_func_arg['value'] if isinstance(target_func_arg, dict) else target_func_arg

        args = [self.visit(node['arguments'][i])
                for i in range(1, len(node['arguments']))]

        if target_func not in self.funcs:
            raise Exception(f"Undefined function: {target_func}")
        target_func_obj = self.funcs[target_func]

        if len(target_func_obj.args) != len(args):
            raise Exception(f"Function '{target_func}' expects {len(target_func_obj.args)} arguments, "
                            f"but got {len(args)}")

        from .base_types import get_variant_type
        variant_ty = get_variant_type()
        coerced: list = []
        for i, (arg, param) in enumerate(zip(args, target_func_obj.args)):
            if hasattr(arg, 'type') and isinstance(arg.type, ir.PointerType) and arg.type.pointee == variant_ty:
                if isinstance(param.type, ir.IntType):
                    arg = self._extract_variant_value(arg, 'int')
                elif isinstance(param.type, ir.DoubleType):
                    arg = self._extract_variant_value(arg, 'float')
                elif isinstance(param.type, ir.PointerType):
                    arg = self._extract_variant_value(arg, 'string')
            elif hasattr(arg, 'type') and arg.type == variant_ty:
                tmp = self.builder.alloca(variant_ty, name=f"thread_arg_{i}_tmp")
                self.builder.store(arg, tmp)
                if isinstance(param.type, ir.IntType):
                    arg = self._extract_variant_value(tmp, 'int')
                elif isinstance(param.type, ir.DoubleType):
                    arg = self._extract_variant_value(tmp, 'float')
                elif isinstance(param.type, ir.PointerType):
                    arg = self._extract_variant_value(tmp, 'string')
            coerced.append(arg)

        debug_print(f"DEBUG: create_thread - target_func: {target_func}, args: {coerced}")
        result = create_thread(self.builder, self.module, target_func_obj, thread_args=coerced)
        debug_print(f"DEBUG: create_thread - returned: {result}")
        return result

    def _handle_join_threads(self, node: Dict[str, Any]) -> ir.Value:
        """Handle join_threads(threads_arr [, count]) built-in."""
        threads_arg = node['arguments'][0]

        if len(node['arguments']) > 1:
            thread_count = self.visit(node['arguments'][1])
        elif 'thread_count' in self.globals:
            ptr, _, _ = self.globals['thread_count']
            thread_count = self.builder.load(ptr)
        else:
            thread_count = ir.Constant(ir.IntType(32), 1)

        if isinstance(threads_arg, dict) and threads_arg.get('type') in ('literal', 'ID'):
            threads_name = threads_arg['value']
            if threads_name in self.locals:
                threads_ptr, dtype, _ = self.locals[threads_name]
                debug_print(f"DEBUG: join_threads - local '{threads_name}', dtype={dtype}")
            elif threads_name in self.globals:
                threads_ptr, *_ = self.globals[threads_name]
                debug_print(f"DEBUG: join_threads - global '{threads_name}'")
            else:
                raise Exception(f"Undefined thread array variable: {threads_name}")
        else:
            threads_ptr = self.visit(threads_arg)

        join_threads(self.builder, self.module, threads_ptr, thread_count)
        return ir.Constant(ir.IntType(32), 0)

    def _handle_rand(self, node: Dict[str, Any]) -> ir.Value:
        """Handle rand([max]) or rand(min, max) — thread-safe, OS-seeded."""
        args = node.get('arguments', [])
        if len(args) not in (0, 1, 2):
            raise Exception(f"rand() requires 0, 1 or 2 arguments, got {len(args)}")

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate a per-function seed variable at the entry block
        func_label = self.current_function_name or 'global'
        seed_var_name = f'__rand_seed_{func_label}'
        if seed_var_name not in self.locals:
            saved_block = self.builder.block
            entry_block = self.builder.function.entry_basic_block
            if len(entry_block.instructions) > 0:
                self.builder.position_before(entry_block.instructions[0])
            else:
                self.builder.position_at_end(entry_block)
            seed_var = self.builder.alloca(i32, name=seed_var_name)
            self.builder.store(ir.Constant(i32, 0), seed_var)
            self.locals[seed_var_name] = (seed_var, 'int', False)
            self.builder.position_at_end(saved_block)

        seed_var, _, _ = self.locals[seed_var_name]
        seed_val = self.builder.load(seed_var)
        need_seed = self.builder.icmp_signed('==', seed_val, ir.Constant(i32, 0))

        cur_func = self.builder.function
        seed_bb      = cur_func.append_basic_block('rand_seed')
        cont_bb      = cur_func.append_basic_block('rand_cont')
        self.builder.cbranch(need_seed, seed_bb, cont_bb)

        # ---- Seed block ----
        self.builder.position_at_end(seed_bb)
        getrandom_fn = self._declare_external_fn('getrandom', i64,
                                                  [ir.IntType(8).as_pointer(), i64, i32])
        time_fn      = self._declare_external_fn('time', i64, [i64.as_pointer()])
        pthread_self_fn = self._declare_external_fn('pthread_self',
                                                     ir.IntType(8).as_pointer(), [])

        seed_tmp = self.builder.alloca(i32, name='seed_tmp')
        seed_buf = self.builder.bitcast(seed_tmp, ir.IntType(8).as_pointer())
        gr_n     = self.builder.call(getrandom_fn,
                                     [seed_buf, ir.Constant(i64, 4), ir.Constant(i32, 0)])

        ok_bb        = cur_func.append_basic_block('rand_seed_ok')
        fb_bb        = cur_func.append_basic_block('rand_seed_fb')
        done_seed_bb = cur_func.append_basic_block('rand_seed_done')
        self.builder.cbranch(self.builder.icmp_signed('==', gr_n, ir.Constant(i64, 4)),
                             ok_bb, fb_bb)

        # OK path: hardware entropy
        self.builder.position_at_end(ok_bb)
        self.builder.store(self.builder.load(seed_tmp), seed_var)
        self.builder.branch(done_seed_bb)

        # Fallback: time XOR pthread_self XOR seed_addr
        self.builder.position_at_end(fb_bb)
        t          = self.builder.call(time_fn, [ir.Constant(i64.as_pointer(), None)])
        tid        = self.builder.call(pthread_self_fn, [])
        tid_int    = self.builder.ptrtoint(tid, i64)
        addr_int   = self.builder.ptrtoint(seed_var, i64)
        combined   = self.builder.xor(self.builder.xor(t, tid_int), addr_int)
        shifted    = self.builder.lshr(combined, ir.Constant(i64, 17))
        final64    = self.builder.xor(combined, shifted)
        seed_fb    = self.builder.trunc(final64, i32)
        seed_nz    = self.builder.select(
            self.builder.icmp_signed('==', seed_fb, ir.Constant(i32, 0)),
            ir.Constant(i32, 1), seed_fb)
        self.builder.store(seed_nz, seed_var)
        self.builder.branch(done_seed_bb)

        # Warmup loop
        self.builder.position_at_end(done_seed_bb)
        tid_wu      = self.builder.call(pthread_self_fn, [])
        tid_wu_32   = self.builder.trunc(self.builder.ptrtoint(tid_wu, i64), i32)
        warmup_cnt  = self.builder.and_(tid_wu_32, ir.Constant(i32, 15))

        warmup_loop_bb = cur_func.append_basic_block('rand_warmup_loop')
        warmup_done_bb = cur_func.append_basic_block('rand_warmup_done')
        warmup_ctr     = self.builder.alloca(i32, name='warmup_counter')
        self.builder.store(ir.Constant(i32, 0), warmup_ctr)
        self.builder.branch(warmup_loop_bb)

        self.builder.position_at_end(warmup_loop_bb)
        ctr_val      = self.builder.load(warmup_ctr)
        rand_r_local = self._declare_external_fn('rand_r', i32, [i32.as_pointer()])
        self.builder.call(rand_r_local, [seed_var])
        next_ctr     = self.builder.add(ctr_val, ir.Constant(i32, 1))
        self.builder.store(next_ctr, warmup_ctr)
        self.builder.cbranch(self.builder.icmp_signed('>=', next_ctr, warmup_cnt),
                             warmup_done_bb, warmup_loop_bb)

        self.builder.position_at_end(warmup_done_bb)
        self.builder.branch(cont_bb)

        # ---- Continue block: produce the random value ----
        self.builder.position_at_end(cont_bb)
        rand_r_func = self._declare_external_fn('rand_r', i32, [i32.as_pointer()])
        rand_val    = self.builder.call(rand_r_func, [seed_var])

        def ensure_i32(val: ir.Value) -> ir.Value:
            v = self._auto_extract_value(val, 'int')
            if not hasattr(v, 'type') or not isinstance(v.type, ir.IntType):
                raise Exception("rand() argument must be an integer expression")
            if v.type.width == 32:
                return v
            return self.builder.zext(v, i32) if v.type.width < 32 else self.builder.trunc(v, i32)

        if len(args) == 0:
            return rand_val
        if len(args) == 1:
            max_v   = ensure_i32(self.visit(args[0]))
            zero    = ir.Constant(i32, 0)
            safe    = self.builder.select(
                self.builder.icmp_signed('==', max_v, zero), ir.Constant(i32, 1), max_v)
            return self.builder.srem(rand_val, safe)
        # 2-arg form: rand(min, max) half-open [min, max)
        min_v   = ensure_i32(self.visit(args[0]))
        max_v   = ensure_i32(self.visit(args[1]))
        one     = ir.Constant(i32, 1)
        zero    = ir.Constant(i32, 0)
        ge      = self.builder.icmp_signed('>=', max_v, min_v)
        hi      = self.builder.select(ge, max_v, min_v)
        lo      = self.builder.select(ge, min_v, max_v)
        rng     = self.builder.sub(hi, lo)
        safe    = self.builder.select(
            self.builder.icmp_signed('<=', rng, zero), one, rng)
        return self.builder.add(self.builder.srem(rand_val, safe), lo)

    def visit_func_call(self, node: Dict[str, Any]) -> ir.Value:
        # Special handling for create_threads, create_thread, wait, and signal
        func_name = node['name']['value'] if isinstance(node['name'], dict) else node['name']
        if func_name == 'create_threads':
            thread_count_arg = node['arguments'][0]
            target_func_arg = node['arguments'][1]
            target_func = target_func_arg['value'] if isinstance(target_func_arg, dict) else target_func_arg
            thread_count = self.visit(thread_count_arg)
            if target_func not in self.funcs:
                raise Exception(f"Undefined function: {target_func}")
            target_func_obj = self.funcs[target_func]
            if len(target_func_obj.args) == 0:
                raise Exception(f"Function '{target_func}' called by create_threads must have at least one parameter (thread_number)")
            return create_threads(self.builder, self.module, thread_count, target_func_obj)
        elif func_name == 'create_thread':
            return self._handle_create_thread(node)
        elif func_name == 'join_thread':
            if len(node['arguments']) != 1:
                raise Exception(f"join_thread() requires exactly 1 argument (thread handle), got {len(node['arguments'])}")
            thread_arg = self.visit(node['arguments'][0])
            if hasattr(thread_arg, 'type'):
                from .base_types import get_variant_type
                variant_ty = get_variant_type()
                if thread_arg.type == variant_ty:
                    tmp = self.builder.alloca(variant_ty, name="tmp_thread")
                    self.builder.store(thread_arg, tmp)
                    thread_arg = self._extract_variant_value(tmp, 'thread')
                elif isinstance(thread_arg.type, ir.PointerType) and thread_arg.type.pointee == variant_ty:
                    thread_arg = self._extract_variant_value(thread_arg, 'thread')
            return join_thread(self.builder, self.module, thread_arg)
        elif func_name in ('wait', 'signal'):
            opaque_ty = ir.IntType(8).as_pointer()
            sem_ptr = self._resolve_arg_ptr(node['arguments'][0], opaque_ty)
            if not hasattr(sem_ptr, 'type') or not isinstance(sem_ptr.type, ir.PointerType):
                raise Exception(f"Semaphore argument to {func_name}() is not a pointer.")
            c_name = 'sem_wait' if func_name == 'wait' else 'sem_post'
            fn = self._declare_external_fn(c_name, ir.IntType(32), [opaque_ty])
            if len(node['arguments']) >= 2:
                return self._emit_counted_loop(fn, sem_ptr,
                                               self.visit(node['arguments'][1]), func_name[:3])
            return self.builder.call(fn, [sem_ptr])
        elif func_name == 'barrier_wait':
            # Barrier wait — maps to pthread_barrier_wait
            if len(node['arguments']) != 1:
                raise Exception(f"barrier_wait() requires exactly 1 argument (barrier), got {len(node['arguments'])}")
            opaque_ty = ir.IntType(8).as_pointer()
            barrier_ptr = self._resolve_arg_ptr(node['arguments'][0], opaque_ty)
            if not hasattr(barrier_ptr, 'type') or not isinstance(barrier_ptr.type, ir.PointerType):
                raise Exception(f"barrier_wait() argument is not a pointer. Got type: {getattr(barrier_ptr, 'type', type(barrier_ptr))}")
            debug_print(f"DEBUG: barrier_wait - barrier_ptr: {barrier_ptr}")
            fn = self._declare_external_fn('pthread_barrier_wait', ir.IntType(32), [opaque_ty])
            return self.builder.call(fn, [barrier_ptr])
        elif func_name in ('lock', 'unlock'):
            opaque_ty = ir.IntType(8).as_pointer()
            mutex_ptr = self._resolve_arg_ptr(node['arguments'][0], opaque_ty)
            if not hasattr(mutex_ptr, 'type') or not isinstance(mutex_ptr.type, ir.PointerType):
                raise Exception(f"Mutex argument to {func_name}() is not a pointer.")
            c_name = 'pthread_mutex_lock' if func_name == 'lock' else 'pthread_mutex_unlock'
            fn = self._declare_external_fn(c_name, ir.IntType(32), [opaque_ty])
            return self.builder.call(fn, [mutex_ptr])
        elif func_name == 'join_threads':
            return self._handle_join_threads(node)
        elif func_name == 'array':
            # Handle array() function calls for local arrays
            args = node.get('arguments', [])
            if len(args) < 2:
                raise Exception(f"Array function requires at least 2 arguments: size and element_type/init_value")
            
            # Get array size
            size_arg = args[0]
            if isinstance(size_arg, dict) and size_arg.get('type') == 'literal':
                array_size = size_arg['value']
            else:
                array_size = self.visit(size_arg)
                if not isinstance(array_size, ir.Constant):
                    raise Exception(f"Array size must be a constant value for local arrays")
                array_size = array_size.constant
            
            # Get element type/initialization
            element_init = args[1]

            _ELEM_SPEC = {
                'semaphore': ('semaphore', ir.ArrayType(ir.IntType(8), 32)),
                'mutex':     ('mutex',     ir.ArrayType(ir.IntType(8), 40)),
                'barrier':   ('barrier',   ir.ArrayType(ir.IntType(8), 128)),
                'thread':    ('thread',    ir.IntType(8).as_pointer()),
            }
            init_name = None
            if isinstance(element_init, dict):
                if element_init.get('type') == 'function_call':
                    init_name = element_init.get('name')
                elif element_init.get('type') == 'literal':
                    v = element_init.get('value', '')
                    init_name = v.strip('"') if isinstance(v, str) else None
            element_type, element_llvm_type = _ELEM_SPEC.get(init_name, ('int', ir.IntType(32)))
            
            # Create local array
            array_llvm_type = ir.ArrayType(element_llvm_type, array_size)
            array_ptr = self.builder.alloca(array_llvm_type)
            
            # Store in locals with array metadata
            # Note: this returns the alloca pointer, but stores metadata for array access
            return array_ptr
        elif func_name == 'int':
            # Handle int() type conversion function
            if len(node['arguments']) != 1:
                raise Exception(f"int() function requires exactly 1 argument, got {len(node['arguments'])}")
            
            arg = self.visit(node['arguments'][0])
            debug_print(f"DEBUG: int() conversion - arg type: {getattr(arg, 'type', type(arg))}, value: {arg}")
            
            # If argument is already an integer, return as-is
            if hasattr(arg, 'type') and isinstance(arg.type, ir.IntType):
                return arg
            
            # If argument is a string pointer, use atoi to convert
            if hasattr(arg, 'type') and isinstance(arg.type, ir.PointerType) and arg.type.pointee == ir.IntType(8):
                atoi = self._declare_external_fn('atoi', ir.IntType(32), [ir.IntType(8).as_pointer()])
                return self.builder.call(atoi, [arg])
            
            # For other types, create a placeholder (compile-time conversion not supported)
            debug_print(f"DEBUG: int() conversion - unsupported type, creating placeholder")
            return ir.Constant(ir.IntType(32), 0)  # Placeholder value
        # Variant creation functions
        elif func_name.startswith('variant_create_'):
            # Handle variant_create_* functions
            variant_type = func_name[15:]  # Remove 'variant_create_' prefix
            args = node.get('arguments', [])
            
            from .base_types import get_variant_type
            variant_ty = get_variant_type()
            
            # Get or create the runtime function
            runtime_func = self.module.globals.get(func_name)
            if not runtime_func:
                if variant_type == 'int':
                    func_ty = ir.FunctionType(variant_ty, [ir.IntType(32)])
                elif variant_type == 'float':
                    func_ty = ir.FunctionType(variant_ty, [ir.DoubleType()])
                elif variant_type in ['string', 'semaphore', 'mutex', 'barrier', 'thread', 'array']:
                    func_ty = ir.FunctionType(variant_ty, [ir.IntType(8).as_pointer()])
                elif variant_type == 'null':
                    func_ty = ir.FunctionType(variant_ty, [])
                else:
                    raise Exception(f"Unknown variant type: {variant_type}")
                runtime_func = ir.Function(self.module, func_ty, name=func_name)
            
            # Process arguments and call function
            if variant_type == 'null':
                return self.builder.call(runtime_func, [])
            elif len(args) == 1:
                arg_val = self.visit(args[0])
                return self.builder.call(runtime_func, [arg_val])
            else:
                raise Exception(f"{func_name} requires exactly 1 argument, got {len(args)}")
        # Variant type checking functions
        elif func_name.startswith('variant_is_'):
            # Handle variant_is_* functions
            args = node.get('arguments', [])
            if len(args) != 1:
                raise Exception(f"{func_name} requires exactly 1 argument, got {len(args)}")
                
            variant_arg = self.visit(args[0])
            
            # Get or create the runtime function
            runtime_func = self.module.globals.get(func_name)
            if not runtime_func:
                from .base_types import get_variant_type
                variant_ty = get_variant_type()
                func_ty = ir.FunctionType(ir.IntType(32), [variant_ty])
                runtime_func = ir.Function(self.module, func_ty, name=func_name)
            
            return self.builder.call(runtime_func, [variant_arg])
        # Variant value extraction functions
        elif func_name.startswith('variant_get_'):
            # Handle variant_get_* functions
            get_type = func_name[12:]  # Remove 'variant_get_' prefix
            args = node.get('arguments', [])
            if len(args) != 1:
                raise Exception(f"{func_name} requires exactly 1 argument, got {len(args)}")
                
            variant_arg = self.visit(args[0])
            
            # Get or create the runtime function
            runtime_func = self.module.globals.get(func_name)
            if not runtime_func:
                from .base_types import get_variant_type
                variant_ty = get_variant_type()
                if get_type == 'int':
                    return_ty = ir.IntType(32)
                elif get_type == 'float':
                    return_ty = ir.DoubleType()
                elif get_type in ['string', 'pointer']:
                    return_ty = ir.IntType(8).as_pointer()
                else:
                    raise Exception(f"Unknown variant get type: {get_type}")
                func_ty = ir.FunctionType(return_ty, [variant_ty])
                runtime_func = ir.Function(self.module, func_ty, name=func_name)
            
            return self.builder.call(runtime_func, [variant_arg])
        # Variant utility functions
        elif func_name in ['variant_type', 'variant_copy', 'variant_equals', 'variant_to_string']:
            args = node.get('arguments', [])
            
            # Get or create the runtime function
            runtime_func = self.module.globals.get(func_name)
            if not runtime_func:
                from .base_types import get_variant_type
                variant_ty = get_variant_type()
                if func_name == 'variant_type':
                    func_ty = ir.FunctionType(ir.IntType(8).as_pointer(), [variant_ty])
                elif func_name == 'variant_copy':
                    func_ty = ir.FunctionType(variant_ty, [variant_ty])
                elif func_name == 'variant_equals':
                    func_ty = ir.FunctionType(ir.IntType(32), [variant_ty, variant_ty])
                elif func_name == 'variant_to_string':
                    func_ty = ir.FunctionType(ir.IntType(8).as_pointer(), [variant_ty.as_pointer()])
                runtime_func = ir.Function(self.module, func_ty, name=func_name)
            
            # Process arguments
            call_args = []
            for arg in args:
                call_args.append(self.visit(arg))
            
            return self.builder.call(runtime_func, call_args)
        elif func_name == 'thread':
            # Handle thread() type specifier - returns a null thread pointer as placeholder
            debug_print(f"DEBUG: thread() type specifier - returning null thread pointer")
            thread_type = ir.IntType(8).as_pointer()  # pthread_t as void*
            return ir.Constant(thread_type, None)  # NULL thread pointer
        elif func_name == 'sleep':
            # Sleep with optional units: seconds (default), milliseconds, nanoseconds
            # Usage: sleep(value) or sleep(value, "ms"|"milliseconds"|"ns"|"nanoseconds"|"s"|"seconds")
            args = node.get('arguments', [])
            if len(args) == 0 or len(args) > 2:
                raise Exception(f"sleep() requires 1 or 2 arguments, got {len(args)}")

            # Duration (expects integer; unwrap variant if passed a local variable)
            duration_val = self._auto_extract_value(self.visit(args[0]), 'int')
            if not hasattr(duration_val, 'type') or not isinstance(duration_val.type, ir.IntType):
                raise Exception("sleep() duration must be an integer expression")

            # Determine unit (default seconds)
            unit = 's'
            if len(args) == 2:
                unit_node = args[1]
                if isinstance(unit_node, dict) and unit_node.get('type') == 'literal' and isinstance(unit_node.get('value'), str):
                    unit_raw = unit_node['value']
                    # Strip quotes if present
                    if unit_raw.startswith('"') and unit_raw.endswith('"'):
                        unit_raw = unit_raw[1:-1]
                    unit_l = unit_raw.strip().lower()
                    if unit_l in ('s', 'sec', 'secs', 'second', 'seconds'):
                        unit = 's'
                    elif unit_l in ('ms', 'msec', 'msecs', 'millisecond', 'milliseconds', 'milisecond', 'miliseconds'):
                        # Also accept common misspelling 'milisecond(s)'
                        unit = 'ms'
                    elif unit_l in ('ns', 'nsec', 'nsecs', 'nanosecond', 'nanoseconds'):
                        unit = 'ns'
                    else:
                        raise Exception(f"Unsupported sleep() unit: {unit_raw}")
                else:
                    # If not a string literal, default to seconds
                    unit = 's'

            i32 = ir.IntType(32)
            i64 = ir.IntType(64)

            # Extend duration to i64 for computations
            dur64 = self.builder.zext(duration_val, i64) if isinstance(duration_val.type, ir.IntType) and duration_val.type.width < 64 else duration_val
            if isinstance(dur64.type, ir.IntType) and dur64.type.width == 32:
                dur64 = self.builder.zext(dur64, i64)

            # Compute tv_sec and tv_nsec as i64 values
            if unit == 's':
                tv_sec = dur64
                tv_nsec = ir.Constant(i64, 0)
            elif unit == 'ms':
                thousand = ir.Constant(i64, 1000)
                one_million = ir.Constant(i64, 1000000)
                tv_sec = self.builder.sdiv(dur64, thousand)
                rem_ms = self.builder.srem(dur64, thousand)
                tv_nsec = self.builder.mul(rem_ms, one_million)
            else:  # 'ns'
                one_billion = ir.Constant(i64, 1000000000)
                tv_sec = self.builder.sdiv(dur64, one_billion)
                tv_nsec = self.builder.srem(dur64, one_billion)

            # Allocate timespec and store values
            ts_ptr = self.builder.alloca(self.timespec_ty, name="ts")
            # ts.tv_sec
            sec_ptr = self.builder.gep(ts_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
            self.builder.store(tv_sec, sec_ptr)
            # ts.tv_nsec
            nsec_ptr = self.builder.gep(ts_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
            self.builder.store(tv_nsec, nsec_ptr)

            nanosleep = self._declare_external_fn('nanosleep', ir.IntType(32),
                                                   [self.timespec_ty.as_pointer(), self.timespec_ty.as_pointer()])
            null_rem = ir.Constant(self.timespec_ty.as_pointer(), None)
            return self.builder.call(nanosleep, [ts_ptr, null_rem])
        elif func_name == 'seed':
            # Remove explicit seeding API in favor of automatic OS-entropy seeding on first rand() use
            raise Exception("seed() was removed. rand() now auto-seeds from OS entropy on first use.")
        elif func_name == 'rand':
            return self._handle_rand(node)

        # Handle constructor functions for synchronization primitives
        elif func_name == 'semaphore':
            # semaphore(initial_value) - return the initial value for use in declarations
            if len(node['arguments']) != 1:
                raise Exception(f"semaphore() constructor requires exactly 1 argument (initial value), got {len(node['arguments'])}")
            initial_value = self.visit(node['arguments'][0])
            return initial_value
        elif func_name == 'mutex':
            # mutex() - return 0 as a placeholder (mutexes don't have initial values)
            return ir.Constant(ir.IntType(32), 0)
        elif func_name == 'barrier':
            # barrier(participant_count) - return the participant count for use in declarations
            if len(node['arguments']) != 1:
                raise Exception(f"barrier() constructor requires exactly 1 argument (participant count), got {len(node['arguments'])}")
            participant_count = self.visit(node['arguments'][0])
            return participant_count
        elif func_name == 'queue':
            # queue(capacity) - return 0 as placeholder; real initialization done in visit_declaration
            return ir.Constant(ir.IntType(32), 0)

        elif func_name == 'enqueue':
            # enqueue(q, value) - push value onto back of circular buffer (NOT thread-safe)
            if len(node['arguments']) != 2:
                raise Exception(f"enqueue() requires exactly 2 arguments (queue, value), got {len(node['arguments'])}")
            queue_ptr = self._get_queue_ptr(node['arguments'][0])
            i32 = ir.IntType(32)
            zero = ir.Constant(i32, 0)
            # Load fields
            cap_ptr  = self.builder.gep(queue_ptr, [zero], inbounds=False)
            cnt_ptr  = self.builder.gep(queue_ptr, [ir.Constant(i32, 1)], inbounds=False)
            head_ptr = self.builder.gep(queue_ptr, [ir.Constant(i32, 2)], inbounds=False)
            capacity = self.builder.load(cap_ptr)
            head     = self.builder.load(head_ptr)
            # Write value at buffer[head] = queue_ptr + 4 + head
            buf_idx  = self.builder.add(ir.Constant(i32, 4), head)
            slot_ptr = self.builder.gep(queue_ptr, [buf_idx], inbounds=False)
            val = self.visit(node['arguments'][1])
            # Coerce val to i32 — handle variant pointers, plain int pointers, wider/narrower ints
            if isinstance(val.type, ir.PointerType):
                from .base_types import get_variant_type
                if val.type.pointee == get_variant_type():
                    # Variant variable (e.g. `mutable x := 0`) — extract the integer field
                    val = self._extract_variant_value(val, 'int')
                else:
                    # Plain integer pointer — load it
                    val = self.builder.load(val)
            if not isinstance(val.type, ir.IntType) or val.type.width != 32:
                if hasattr(val.type, 'width') and val.type.width > 32:
                    val = self.builder.trunc(val, i32)
                else:
                    val = self.builder.zext(val, i32)
            self.builder.store(val, slot_ptr)
            # head = (head + 1) % capacity
            new_head = self.builder.srem(self.builder.add(head, ir.Constant(i32, 1)), capacity)
            self.builder.store(new_head, head_ptr)
            # count += 1
            cnt = self.builder.load(cnt_ptr)
            self.builder.store(self.builder.add(cnt, ir.Constant(i32, 1)), cnt_ptr)
            return ir.Constant(i32, 0)

        elif func_name == 'dequeue':
            # dequeue(q) - pop value from front of circular buffer (NOT thread-safe)
            if len(node['arguments']) != 1:
                raise Exception(f"dequeue() requires exactly 1 argument (queue), got {len(node['arguments'])}")
            queue_ptr = self._get_queue_ptr(node['arguments'][0])
            i32 = ir.IntType(32)
            zero = ir.Constant(i32, 0)
            # Load fields
            cap_ptr  = self.builder.gep(queue_ptr, [zero], inbounds=False)
            cnt_ptr  = self.builder.gep(queue_ptr, [ir.Constant(i32, 1)], inbounds=False)
            tail_ptr = self.builder.gep(queue_ptr, [ir.Constant(i32, 3)], inbounds=False)
            capacity = self.builder.load(cap_ptr)
            tail     = self.builder.load(tail_ptr)
            # Read value from buffer[tail]
            buf_idx  = self.builder.add(ir.Constant(i32, 4), tail)
            slot_ptr = self.builder.gep(queue_ptr, [buf_idx], inbounds=False)
            val      = self.builder.load(slot_ptr)
            # tail = (tail + 1) % capacity
            new_tail = self.builder.srem(self.builder.add(tail, ir.Constant(i32, 1)), capacity)
            self.builder.store(new_tail, tail_ptr)
            # count -= 1
            cnt = self.builder.load(cnt_ptr)
            self.builder.store(self.builder.sub(cnt, ir.Constant(i32, 1)), cnt_ptr)
            return val

        elif func_name == 'queue_size':
            # queue_size(q) - return number of elements currently in the queue
            if len(node['arguments']) != 1:
                raise Exception(f"queue_size() requires exactly 1 argument (queue), got {len(node['arguments'])}")
            queue_ptr = self._get_queue_ptr(node['arguments'][0])
            i32 = ir.IntType(32)
            cnt_ptr = self.builder.gep(queue_ptr, [ir.Constant(i32, 1)], inbounds=False)
            return self.builder.load(cnt_ptr)

        elif func_name == 'queue_capacity':
            # queue_capacity(q) - return capacity of the queue
            if len(node['arguments']) != 1:
                raise Exception(f"queue_capacity() requires exactly 1 argument (queue), got {len(node['arguments'])}")
            queue_ptr = self._get_queue_ptr(node['arguments'][0])
            i32 = ir.IntType(32)
            cap_ptr = self.builder.gep(queue_ptr, [ir.Constant(i32, 0)], inbounds=False)
            return self.builder.load(cap_ptr)

        # Default: regular function call
        debug_print(f"DEBUG: default function call: {func_name} with args {[getattr(a, 'type', 'no-type') for a in node['arguments']]}")
        
        # Process arguments
        args = []
        for i, arg in enumerate(node['arguments']):
            try:
                processed_arg = self.visit(arg)
                debug_print(f"DEBUG: Processed arg {i}: {type(processed_arg)} -> {getattr(processed_arg, 'type', 'no-llvm-type')}")
                args.append(processed_arg)
            except Exception as e:
                debug_print(f"DEBUG: Error processing arg {i}: {e}")
                raise
        
        debug_print(f"DEBUG: default function call '{func_name}' processed args: {[str(a) for a in args]}")
        
        # Guard: if calling sem_post or sem_wait directly, check argument type and value
        if func_name in ('sem_post', 'sem_wait'):
            for idx, val in enumerate(args):
                # If the argument is a constant integer, this is always an error
                if isinstance(val, ir.Constant) and isinstance(val.type, ir.IntType) and val.type.width == 32:
                    raise Exception(f"Direct call to {func_name} with i32 constant argument: {val}. You must pass a semaphore variable (i8* pointer), not an integer literal.")
                if not hasattr(val, 'type') or not isinstance(val.type, ir.PointerType) or val.type != ir.IntType(8).as_pointer():
                    raise Exception(f"Direct call to {func_name} with non-i8* argument: {val} (type: {getattr(val, 'type', type(val))}). You must pass a semaphore variable (i8* pointer). If you passed a literal or non-semaphore variable, this is an error.")
        
        func = self.funcs.get(func_name)
        if func is None:
            # Try to get from module.globals (for external functions like sem_post/sem_wait)
            func = self.module.globals.get(func_name)
        if func is None:
            raise Exception(f"Function '{func_name}' not found in user functions or module.globals.")
        
        debug_print(f"DEBUG: About to call function '{func_name}' with {len(args)} args")
        try:
            result = self.builder.call(func, args)
            debug_print(f"DEBUG: Function call '{func_name}' succeeded")
            return result
        except Exception as e:
            debug_print(f"DEBUG: Function call '{func_name}' failed: {e}")
            debug_print(f"DEBUG: Function: {func}")
            debug_print(f"DEBUG: Args: {args}")
            debug_print(f"DEBUG: Arg types: {[getattr(a, 'type', type(a)) for a in args]}")
            raise

    def visit_function_call(self, node: Dict[str, Any]) -> ir.Value:
        return self.visit_func_call(node)

    def visit_array_access(self, node: Dict[str, Any]) -> ir.Value:
        # Support arrays of any type by tracking type in locals and globals
        array_name = node['array']
        debug_print(f"DEBUG: visit_array_access - array_name: {array_name}")
        
        # Special handling for thread_number as array index
        index_node = node['index']
        debug_print(f"DEBUG: visit_array_access - index_node: {index_node}")
        
        if (isinstance(index_node, dict) and 
            index_node.get('type') == 'literal' and 
            index_node.get('value') == 'thread_number'):
            # Handle thread_number as parameter passed to the function
            if 'thread_number' in self.locals:
                thread_number_ptr, _, _ = self.locals['thread_number']
                index = self.builder.load(thread_number_ptr)
                debug_print(f"DEBUG: visit_array_access - using actual thread_number from locals")
            else:
                # Fallback to 0 if thread_number is not available (e.g., in main)
                index = ir.Constant(ir.IntType(32), 0)
                debug_print(f"DEBUG: visit_array_access - using thread_number fallback (0)")
        elif (isinstance(index_node, dict) and 
              index_node.get('type') == 'binary_op' and 
              index_node.get('left', {}).get('type') == 'literal' and
              index_node.get('left', {}).get('value') == 'thread_number'):
            # Handle thread_number + N
            right_value = index_node.get('right', {}).get('value', 0)
            if 'thread_number' in self.locals:
                thread_number_ptr, _, _ = self.locals['thread_number']
                thread_number_val = self.builder.load(thread_number_ptr)
                index = self.builder.add(thread_number_val, ir.Constant(ir.IntType(32), right_value))
                debug_print(f"DEBUG: visit_array_access - using actual thread_number + {right_value}")
            else:
                # Fallback to 0 + right_value if thread_number is not available
                index = ir.Constant(ir.IntType(32), right_value)
                debug_print(f"DEBUG: visit_array_access - using thread_number fallback + {right_value} = {right_value}")
        else:
            debug_print(f"DEBUG: visit_array_access - visiting index normally")
            index = self.visit(index_node)
            debug_print(f"DEBUG: visit_array_access - index result: {index}, type: {getattr(index, 'type', type(index))}")
        
        # Handle variant indices - extract integer value if needed
        if hasattr(index, 'type'):
            from .base_types import get_variant_type
            variant_ty = get_variant_type()
            if index.type == variant_ty:
                # Index is a variant struct - need to create temp and extract
                temp_var = self.builder.alloca(variant_ty, name="temp_index_variant")
                self.builder.store(index, temp_var)
                index = self._extract_variant_value(temp_var, 'int')
                debug_print(f"DEBUG: visit_array_access - extracted index from variant: {index}")
            elif isinstance(index.type, ir.PointerType) and index.type.pointee == variant_ty:
                # Index is pointer to variant - extract directly
                index = self._extract_variant_value(index, 'int')
                debug_print(f"DEBUG: visit_array_access - extracted index from variant pointer: {index}")
        
        # Get array variable
        array_info = self.get_variable(array_name)
        if array_info is None:
            raise Exception(f"Undefined array: {array_name}")
        
        if isinstance(array_info, tuple):
            array_ptr, element_type, is_constant = array_info
        else:
            array_ptr = array_info
            element_type = ir.IntType(32)  # fallback for legacy code
        
        debug_print(f"DEBUG: visit_array_access - array_ptr: {array_ptr}, element_type: {element_type}")
        
        # Special handling for argv (command-line arguments)
        if element_type == 'array' and array_name in self.locals:
            # This is argv - load the argv pointer, then GEP to get argv[index]
            argv_ptr_ptr = array_ptr  # This is char*** (pointer to char**)
            argv_ptr = self.builder.load(argv_ptr_ptr)  # Load to get char**
            element_ptr = self.builder.gep(argv_ptr, [index], inbounds=True)  # GEP to get char**[index] -> char*
            # Return the char* pointer (don't load it, as it's already a string pointer)
            debug_print(f"DEBUG: visit_array_access - returning argv string pointer: {element_ptr}")
            return self.builder.load(element_ptr)  # Load char* from char**[index]
        
        # For both global and local arrays, we need to use GEP with two indices: [0, index]
        # The first index (0) dereferences the pointer to the array
        # The second index selects the array element
        debug_print(f"DEBUG: Array GEP - array_ptr type: {getattr(array_ptr, 'type', 'unknown')}")
        debug_print(f"DEBUG: Array GEP - index type: {getattr(index, 'type', 'unknown')}")
        element_ptr = self.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), index], inbounds=True)
        
        debug_print(f"DEBUG: visit_array_access - element_ptr: {element_ptr}")
        
        # Value types are loaded; opaque C types (semaphore/mutex/barrier) return the pointer
        _LOAD_TYPES = {'int', 'float', 'thread'}
        if isinstance(element_type, str):
            actual = element_type.removeprefix('array_')
            if actual in _LOAD_TYPES:
                return self.builder.load(element_ptr)
            return element_ptr
        return self.builder.load(element_ptr)

    def visit_return(self, node: Dict[str, Any]) -> None:
        # Mark that we've seen an explicit return in this body
        self.has_explicit_return = True
        if 'value' in node and node['value'] is not None:
            val = self.visit(node['value'])
            from .base_types import get_variant_type
            variant_ty = get_variant_type()
            func_return_type = self.builder.function.type.pointee.return_type

            # If the function returns variant by value, coerce val to match
            if func_return_type == variant_ty:
                if hasattr(val, 'type') and isinstance(val.type, ir.PointerType) and val.type.pointee == variant_ty:
                    # val is a variant pointer — load it
                    val = self.builder.load(val)
                elif hasattr(val, 'type') and val.type != variant_ty:
                    # val is a non-variant (e.g. i32, double) — wrap in variant
                    temp_ptr = self.builder.alloca(variant_ty, name="ret_variant_tmp")
                    from .base_types import get_type_tag_for_value
                    type_tag = get_type_tag_for_value(val, None)
                    self._store_variant_value(temp_ptr, val, type_tag)
                    val = self.builder.load(temp_ptr)
            elif hasattr(val, 'type') and isinstance(val.type, ir.PointerType) and val.type.pointee == func_return_type:
                # val is a pointer to the expected type — load it
                val = self.builder.load(val)

            self.builder.ret(val)
        else:
            self.builder.ret_void()

    def visit_record_init(self, node: Dict[str, Any]) -> None:
        # Reached only if _check_unsupported_nodes somehow missed this node
        raise AleError("record initialization is not yet supported", node)

    def visit_pointer_type(self, node: Dict[str, Any]) -> None:
        raise AleError("pointer types are not yet supported", node)

    def visit_dereference(self, node: Dict[str, Any]) -> None:
        raise AleError("dereference is not yet supported", node)

    def visit_reference(self, node: Dict[str, Any]) -> None:
        raise AleError("references are not yet supported", node)

    def _store_variant_value(self, variant_ptr, value, type_tag, type_hint=None):
        """Store *value* into the variant at *variant_ptr*. Delegates to variant_utils."""
        debug_print(f"DEBUG: _store_variant_value - value: {value}, type_tag: {type_tag}")
        variant_utils.store_variant(self.builder, self.module, variant_ptr, value)

    def _extract_variant_value(self, variant_ptr, expected_type='int'):
        """Extract a typed value from the variant at *variant_ptr*. Delegates to variant_utils."""
        return variant_utils.extract_variant(self.builder, self.module, variant_ptr, expected_type)

    def _auto_extract_value(self, value, prefer_type='int'):
        """Strip variant/pointer wrapping from *value*. Delegates to variant_utils."""
        debug_print(f"DEBUG: _auto_extract_value - value type: {getattr(value, 'type', 'no-type')}, prefer: {prefer_type}")
        return variant_utils.auto_extract(self.builder, self.module, value, prefer_type)

    def _store_null_variant(self, variant_ptr):
        """Store a null variant. Delegates to variant_utils."""
        variant_utils.store_null_variant(self.builder, variant_ptr)

    def _get_queue_ptr(self, arg_node) -> ir.Value:
        """Resolve a queue argument node to an i32* pointer into the queue's storage array."""
        i32 = ir.IntType(32)
        if isinstance(arg_node, dict) and arg_node.get('type') == 'ID':
            var_name = arg_node['value']
            entry = self.locals.get(var_name) or self.globals.get(var_name)
            if entry is None:
                raise Exception(f"Undefined queue variable '{var_name}'")
            ptr, dtype, _ = entry
            if dtype != 'queue':
                raise Exception(f"Variable '{var_name}' is not a queue (got type '{dtype}')")
            # For shared queues stored as GlobalVariable, bitcast to i32*
            if isinstance(ptr, ir.GlobalVariable):
                return self.builder.bitcast(ptr, i32.as_pointer())
            return ptr
        # Fall back: evaluate as expression and treat as i32*
        val = self.visit(arg_node)
        if isinstance(val, ir.GlobalVariable):
            return self.builder.bitcast(val, i32.as_pointer())
        return val

    def get_variable(self, name: str, prefer_globals: bool = False):
        """
        Get a variable from locals or globals, returning (ptr, dtype, is_constant) tuple.
        Args:
            name: Variable name to look up
            prefer_globals: If True, check globals first, otherwise check locals first
        Returns:
            (ptr, dtype, is_constant) tuple if found, None if not found
        """
        if prefer_globals:
            # Check globals first, then locals
            entry = self.globals.get(name)
            if entry is not None:
                return entry
            entry = self.locals.get(name)
            if entry is not None:
                return entry
        else:
            # Check locals first, then globals
            entry = self.locals.get(name)
            if entry is not None:
                return entry
            entry = self.globals.get(name)
            if entry is not None:
                return entry
        return None


def compile(ast: Dict[str, Any]) -> str:
    cg = CodeGenerator()
    return cg.compile(ast)

def set_debug(enable_debug: bool) -> None:
    """Set the global DEBUG variable to enable or disable debug output."""
    global DEBUG, debug_print
    DEBUG = enable_debug
    debug_print = print if DEBUG else lambda *args, **kwargs: None
