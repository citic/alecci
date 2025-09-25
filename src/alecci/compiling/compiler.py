from typing import Any, Dict, List, Optional, Tuple, Union
from typing import Dict, Any, List, Union
from llvmlite import ir

from .base_types import get_type
from .threading_utils import create_threads, create_thread, join_threads, join_thread
from ..parsing.globals import debug_print

DEBUG = False  # Temporarily enable debug for troubleshooting



class CodeGenerator:
    def __init__(self) -> None:
        self.module = ir.Module(name="main")
        self.builder = None
        self.funcs: Dict[str, ir.Function] = {}
        self.locals = {}  # name -> (pointer, datatype, is_constant)
        self.globals = {}  # name -> (pointer, datatype, is_constant)
        self.current_function_name = None  # Track current function for context
        self.shared_runtime_inits = []  # List of (name, expression) for shared vars that need runtime evaluation
        # timespec type for nanosleep: struct { i64 tv_sec; i64 tv_nsec; }
        self.timespec_ty = ir.LiteralStructType([ir.IntType(64), ir.IntType(64)])
        # Track if the current function/procedure had an explicit return in its body
        self.has_explicit_return: bool = False

    def compile(self, ast: Dict[str, Any]) -> str:
        try:
            self.visit(ast)
            debug_print("DEBUG: AST compilation completed, attempting to convert module to string...")
            
            # Try to convert each function individually to find the problematic one
            debug_print("DEBUG: Checking individual functions...")
            for name, func in list(self.module.globals.items()):
                if hasattr(func, 'blocks'):  # It's a function
                    try:
                        func_str = str(func)
                        debug_print(f"DEBUG: Function {name} converted successfully")
                    except Exception as e:
                        debug_print(f"DEBUG: ERROR in function {name}: {e}")
                        # Try to get more details about the problematic function
                        if hasattr(func, 'basic_blocks'):
                            for i, block in enumerate(func.basic_blocks):
                                try:
                                    block_str = str(block)
                                    debug_print(f"DEBUG: Block {i} in {name} OK")
                                except Exception as be:
                                    debug_print(f"DEBUG: ERROR in block {i} of {name}: {be}")
                                    # Check individual instructions
                                    if hasattr(block, 'instructions'):
                                        for j, instr in enumerate(block.instructions):
                                            try:
                                                instr_str = str(instr)
                                                debug_print(f"DEBUG: Instruction {j} in block {i} of {name} OK")
                                            except Exception as ie:
                                                debug_print(f"DEBUG: ERROR in instruction {j} of block {i} of {name}: {ie}")
                                                debug_print(f"DEBUG: Instruction type: {type(instr)}")
                                                if hasattr(instr, 'args'):
                                                    debug_print(f"DEBUG: Number of args: {len(instr.args)}")
                                                    for k, arg in enumerate(instr.args):
                                                        debug_print(f"DEBUG: Arg {k}: {repr(arg)} (type: {type(arg)})")
                                                        if hasattr(arg, 'type'):
                                                            debug_print(f"DEBUG: Arg {k} LLVM type: {arg.type}")
                                                        else:
                                                            debug_print(f"DEBUG: Arg {k} has no type attribute!")
                                                break
            
            return str(self.module)
        except Exception as e:
            debug_print(f"DEBUG: Error during module string conversion: {e}")
            debug_print(f"DEBUG: Module functions: {list(self.module.globals.keys())}")
            debug_print(f"DEBUG: Error type: {type(e)}")
            raise

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
                        if arg.get('arg_type') == 'int' or arg.get('arg_type') is None:
                            param_types.append(ir.IntType(32))
                        # Add other parameter types as needed
                    # Functions return values, procedures return void
                    if decl.get('type') == 'function':
                        # Check if function has explicit return type annotation, otherwise default to variant
                        return_type = decl.get('return_type')
                        if return_type == 'int':
                            func_ty = ir.FunctionType(ir.IntType(32), param_types)
                        elif return_type == 'string':
                            func_ty = ir.FunctionType(ir.IntType(8).as_pointer(), param_types)
                        else:
                            # Default to variant for functions without explicit return type
                            from .base_types import get_variant_type
                            func_ty = ir.FunctionType(get_variant_type(), param_types)
                    else:
                        func_ty = ir.FunctionType(ir.VoidType(), param_types)
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
            # Recurse into nested blocks (e.g., if, while, for, etc.)
            for key in ['body', 'then_body', 'else_body']:
                if key in body:
                    self._collect_shared_in_body(body[key])

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
                        param_ptr = self.builder.alloca(ir.IntType(32), name=param_name)
                        self.builder.store(param_value, param_ptr)
                        self.locals[param_name] = (param_ptr, 'int', False)  # function parameters are mutable
                        debug_print(f"DEBUG: Added parameter '{param_name}' to {decl['name']}")

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
                
                # Append default return if none was explicitly emitted
                if decl['name'] == 'main':
                    self.builder.ret(ir.Constant(ir.IntType(32), 0))  # main returns 0
                elif decl.get('type') == 'function':
                    # Functions should have return statements in their body
                    # If we reach here, it means no explicit return - return 0 as default
                    if not self.builder.block.is_terminated:
                        self.builder.ret(ir.Constant(ir.IntType(32), 0))
                else:
                    # Procedures return void
                    if not self.builder.block.is_terminated:
                        self.builder.ret_void()

                # Restore builder state
                self.builder = old_builder
                self.locals = old_locals
                self.current_function_name = old_func_name

    def process_shared_declaration(self, node: Dict[str, Any]) -> None:
        """Process shared variable declarations that should be globally accessible"""
        debug_print(f"DEBUG: process_shared_declaration - Processing shared node: {node}")
        name = node['name']
        init = node['init']
        var_type = init.get('var_type', 'int')
        value = init['value'] if init.get('value') else None
        is_constant = node.get('const', False)  # Get const flag from parser
        debug_print(f"DEBUG: Shared declaration name={name}, type={var_type}, value={value}")

        # Check if this is an array initialization
        if value and isinstance(value, dict) and value.get('type') == 'function_call' and value.get('name') == 'array':
            # Handle shared array declarations
            args = value.get('arguments', [])
            if len(args) < 2:
                raise Exception(f"Array function requires at least 2 arguments: size and element_type/init_value")
            
            # Get array size
            size_arg = args[0]
            debug_print(f"DEBUG: Array size argument: {size_arg}")
            
            if isinstance(size_arg, dict) and size_arg.get('type') == 'literal':
                array_size = size_arg['value']
                if isinstance(array_size, str):
                    try:
                        array_size = int(array_size)
                    except ValueError:
                        debug_print(f"DEBUG: String literal '{array_size}' cannot be converted to int, using default 10")
                        array_size = 10
            elif isinstance(size_arg, dict) and size_arg.get('type') == 'literal' and isinstance(size_arg.get('value'), str):
                # This might be a variable reference stored as a string literal
                var_name = size_arg['value']
                # For now, use a default size - in a real implementation we'd need to track constants
                debug_print(f"DEBUG: Array size references variable '{var_name}', using default size 10")
                array_size = 10  # Default fallback
            elif isinstance(size_arg, str):
                # Direct variable reference
                debug_print(f"DEBUG: Array size is variable reference '{size_arg}', using default size 10")
                array_size = 10  # Default fallback
            else:
                # Try to handle the case where it's a variable name directly
                debug_print(f"DEBUG: Array size is not a literal: {size_arg}, using default size 10")
                array_size = 10  # Default fallback
                
            # Ensure array_size is an integer
            if not isinstance(array_size, int):
                debug_print(f"DEBUG: Converting array_size {array_size} (type: {type(array_size)}) to int")
                try:
                    array_size = int(array_size)
                except (ValueError, TypeError):
                    debug_print(f"DEBUG: Could not convert array_size to int, using default 10")
                    array_size = 10
            
            # Get element type/initialization
            element_init = args[1]
            
            # Determine element type
            if isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'semaphore':
                element_type = 'semaphore'
                element_llvm_type = ir.ArrayType(ir.IntType(8), 32)  # sem_t storage
            elif isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'mutex':
                element_type = 'mutex'
                element_llvm_type = ir.ArrayType(ir.IntType(8), 40)  # pthread_mutex_t storage
            elif isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'barrier':
                element_type = 'barrier'
                element_llvm_type = ir.ArrayType(ir.IntType(8), 128)  # pthread_barrier_t storage (opaque)
            else:
                # For now, assume int if not semaphore or mutex
                element_type = 'int'
                element_llvm_type = ir.IntType(32)
            
            # Create global array
            array_llvm_type = ir.ArrayType(element_llvm_type, array_size)
            debug_print(f"DEBUG: Declaring shared array '{name}' of {array_size} {element_type} elements")
            
            array_variable = ir.GlobalVariable(self.module, array_llvm_type, name=name)
            array_variable.linkage = 'internal'
            
            # Initialize array
            if element_type == 'semaphore':
                # Initialize each semaphore element
                zero_bytes = [ir.Constant(ir.IntType(8), 0)] * 32
                sem_init = ir.Constant(element_llvm_type, zero_bytes)
                array_init = ir.Constant(array_llvm_type, [sem_init] * array_size)
            elif element_type == 'mutex':
                # Initialize each mutex element
                zero_bytes = [ir.Constant(ir.IntType(8), 0)] * 40
                mutex_init = ir.Constant(element_llvm_type, zero_bytes)
                array_init = ir.Constant(array_llvm_type, [mutex_init] * array_size)
            elif element_type == 'barrier':
                # Initialize each barrier element
                zero_bytes = [ir.Constant(ir.IntType(8), 0)] * 128
                barrier_init = ir.Constant(element_llvm_type, zero_bytes)
                array_init = ir.Constant(array_llvm_type, [barrier_init] * array_size)
            else:
                # Initialize with zeros for other types
                array_init = ir.Constant(array_llvm_type, [ir.Constant(element_llvm_type, 0)] * array_size)
            
            array_variable.initializer = array_init
            
            # Store in globals with array metadata
            self.globals[name] = (array_variable, f'array_{element_type}', False)  # Arrays are mutable
            debug_print(f"DEBUG: Created global array '{name}' with type 'array_{element_type}'")
            return

        # Fix: If var_type is None and value is a function_call to 'semaphore' or 'mutex', treat appropriately
        if var_type is None and isinstance(value, dict) and value.get('type') == 'function_call' and value.get('name') == 'semaphore':
            var_type = 'semaphore'
            # Extract initial value from function_call arguments
            args = value.get('arguments', [])
            if args and args[0].get('type') == 'literal':
                value = args[0]['value']
            else:
                value = None
        elif var_type is None and isinstance(value, dict) and value.get('type') == 'function_call' and value.get('name') == 'mutex':
            var_type = 'mutex'
            # Mutexes don't take initial values
            value = None
        elif var_type is None and isinstance(value, dict) and value.get('type') == 'function_call' and value.get('name') == 'barrier':
            var_type = 'barrier'
            # Barriers take a participant count, handled at initialization time
            # Keep value as-is for now
        elif var_type is None and isinstance(value, dict) and value.get('type') == 'function_call' and value.get('name') == 'variant':
            var_type = 'variant'
            # Variants can be created with variant() function call
        elif var_type is None and isinstance(value, dict) and value.get('type') == 'function_call' and value.get('name') == 'create_threads':
            # Special handling for thread arrays - defer actual creation to second pass
            var_type = 'thread_array'
            debug_print(f"DEBUG: Detected shared thread array '{name}' - deferring to second pass")
            # Create a placeholder global variable that will be replaced in second pass
            from .base_types import get_type
            llvm_type = get_type('int')  # Placeholder type
            variable = ir.GlobalVariable(self.module, llvm_type, name=name)
            variable.linkage = 'internal'
            variable.initializer = ir.Constant(llvm_type, 0)
            self.globals[name] = (variable, 'thread_array', False)  # Thread arrays are mutable
            return

        if var_type == 'semaphore':
            # Handle shared semaphore declarations
            sem_ty = ir.IntType(8).as_pointer()  # sem_t*
            debug_print(f"DEBUG: Declaring shared semaphore '{name}' (process_shared_declaration)")
            sem_storage_ty = ir.ArrayType(ir.IntType(8), 32)
            variable = ir.GlobalVariable(self.module, sem_storage_ty, name=f"{name}_storage")
            variable.linkage = 'internal'
            variable.initializer = ir.Constant(sem_storage_ty, [ir.Constant(ir.IntType(8), 0)] * 32)
            # Bitcast the storage to sem_t* and store in globals
            # We can't use self.builder here, so store the variable for now
            self.globals[name] = (variable, 'semaphore', False)  # Store as tuple with mutability flag
            debug_print(f"DEBUG: Created global semaphore storage variable '{name}_storage'")
            return

        if var_type == 'mutex':
            # Handle shared mutex declarations
            mutex_ty = ir.IntType(8).as_pointer()  # pthread_mutex_t*
            debug_print(f"DEBUG: Declaring shared mutex '{name}' (process_shared_declaration)")
            mutex_storage_ty = ir.ArrayType(ir.IntType(8), 40)  # pthread_mutex_t storage
            variable = ir.GlobalVariable(self.module, mutex_storage_ty, name=f"{name}_storage")
            variable.linkage = 'internal'
            variable.initializer = ir.Constant(mutex_storage_ty, [ir.Constant(ir.IntType(8), 0)] * 40)
            # Bitcast the storage to pthread_mutex_t* and store in globals
            # We can't use self.builder here, so store the variable for now
            self.globals[name] = (variable, 'mutex', False)  # Store as tuple with mutability flag
            debug_print(f"DEBUG: Created global mutex storage variable '{name}_storage'")
            return

        if var_type == 'barrier':
            # Handle shared barrier declarations
            barrier_ty = ir.IntType(8).as_pointer()  # pthread_barrier_t*
            debug_print(f"DEBUG: Declaring shared barrier '{name}' (process_shared_declaration)")
            barrier_storage_ty = ir.ArrayType(ir.IntType(8), 128)  # opaque storage
            variable = ir.GlobalVariable(self.module, barrier_storage_ty, name=f"{name}_storage")
            variable.linkage = 'internal'
            variable.initializer = ir.Constant(barrier_storage_ty, [ir.Constant(ir.IntType(8), 0)] * 128)
            self.globals[name] = (variable, 'barrier', False)  # Barriers are mutable
            debug_print(f"DEBUG: Created global barrier storage variable '{name}_storage'")
            return

        if var_type == 'variant':
            # Handle shared variant declarations
            debug_print(f"DEBUG: Declaring shared variant '{name}' (process_shared_declaration)")
            from .base_types import get_variant_type
            variant_ty = get_variant_type()
            variable = ir.GlobalVariable(self.module, variant_ty, name=name)
            variable.linkage = 'internal'
            # Initialize with null variant (type_tag = 8, empty data)
            null_tag = ir.Constant(ir.IntType(32), 8)  # NULL type
            null_data = ir.Constant(ir.ArrayType(ir.IntType(8), 16), [ir.Constant(ir.IntType(8), 0)] * 16)
            variable.initializer = ir.Constant(variant_ty, [null_tag, null_data])
            self.globals[name] = (variable, 'variant', False)  # Variants are mutable
            debug_print(f"DEBUG: Created global variant variable '{name}'")
            # If there's an initialization value, add it to runtime inits
            if value is not None:
                self.shared_runtime_inits.append((name, value))
            return

        # Handle other shared variable types
        from .base_types import get_type
        # If var_type is None, infer from value
        if var_type is None:
            if isinstance(value, dict) and value.get('type') == 'literal':
                literal_value = value['value']
                if isinstance(literal_value, int):
                    var_type = 'int'
                elif isinstance(literal_value, float):
                    var_type = 'float'
                elif isinstance(literal_value, str):
                    var_type = 'string'
                else:
                    var_type = 'int'  # Default
            elif isinstance(value, int):
                var_type = 'int'
            elif isinstance(value, float):
                var_type = 'float'
            elif isinstance(value, str):
                var_type = 'string'
            else:
                var_type = 'int'  # Default
        
        debug_print(f"DEBUG: process_shared_declaration - name: {name}, value: {value}, inferred var_type: {var_type}")
        
        llvm_type = get_type(var_type)
        debug_print(f"DEBUG: Declaring shared variable '{name}' of type '{var_type}' (LLVM type: {llvm_type})")
        
        variable = ir.GlobalVariable(self.module, llvm_type, name=name)
        variable.linkage = 'internal'
        if isinstance(value, dict) and value.get('type') == 'literal':
            variable.initializer = ir.Constant(llvm_type, value['value'])
        elif value is not None and not isinstance(value, dict):
            # Simple value (not a complex expression)
            variable.initializer = ir.Constant(llvm_type, value)
        else:
            # Complex expression (like function calls) or no value - use default initialization
            # Global variables must have constant initializers, so we default to 0
            variable.initializer = ir.Constant(llvm_type, 0)
            debug_print(f"DEBUG: Using default initializer (0) for complex expression in '{name}'")
            
            # Add to runtime initialization list if it's a complex expression that needs evaluation
            if isinstance(value, dict):
                self.shared_runtime_inits.append((name, value))
                debug_print(f"DEBUG: Added '{name}' to runtime initialization list")
        
        self.globals[name] = (variable, var_type, is_constant)  # Store as tuple with constness
        debug_print(f"DEBUG: Created global variable '{name}' with inferred type '{var_type}'")    
    def visit_procedure(self, node: Dict[str, Any]) -> None:
        # This method is now handled by the two-pass compilation
        # The actual compilation happens in compile_procedure_bodies
        pass

    def visit_function(self, node: Dict[str, Any]) -> None:
        # This method is now handled by the two-pass compilation
        # The actual compilation happens in compile_procedure_bodies
        pass

    def visit_declaration(self, node: Dict[str, Any]) -> None:
        debug_print(f"DEBUG: visit_declaration - Processing node: {node}")
        name = node['name']
        shared = node['shared']
        is_constant = node.get('const', False)  # Get const flag from parser
        
        # Skip shared declarations during the second pass - they were already processed
        if shared:
            debug_print(f"DEBUG: visit_declaration - Skipping shared declaration '{name}' (already processed in first pass)")
            # Special case: if this is a shared thread array, we need to execute the create_threads call
            if name in self.globals and self.globals[name][1] == 'thread_array':
                init = node['init']
                if init.get('value', {}).get('type') == 'function_call' and init['value'].get('name') == 'create_threads':
                    debug_print(f"DEBUG: visit_declaration - executing create_threads call for shared '{name}'")
                    threads_ptr = self.visit(init['value'])
                    # Update the global entry with the actual thread array pointer
                    self.globals[name] = (threads_ptr, 'thread_array', False)  # Thread arrays are mutable
                    debug_print(f"DEBUG: visit_declaration - updated shared thread array '{name}' with actual pointer")
            # Special case: if this is a shared barrier, we need to initialize it in main
            elif name in self.globals and self.globals[name][1] == 'barrier' and self.current_function_name == 'main':
                init = node['init']
                init_value_expr = init.get('value')
                debug_print(f"DEBUG: visit_declaration - initializing shared barrier '{name}' in main")
                
                # Determine participant count from barrier() call
                barrier_count = ir.Constant(ir.IntType(32), 1)
                if isinstance(init_value_expr, dict) and init_value_expr.get('type') == 'function_call' and init_value_expr.get('name') == 'barrier':
                    bargs = init_value_expr.get('arguments', [])
                    if bargs:
                        try:
                            cnt = self.visit(bargs[0])
                            debug_print(f"DEBUG: visit_declaration - barrier count argument evaluated to: {cnt}, type: {cnt.type}")
                            if hasattr(cnt, 'type') and isinstance(cnt.type, ir.IntType) and cnt.type.width != 32:
                                cnt = self.builder.trunc(cnt, ir.IntType(32)) if cnt.type.width > 32 else self.builder.zext(cnt, ir.IntType(32))
                            barrier_count = cnt
                        except Exception as e:
                            debug_print(f"DEBUG: visit_declaration - error evaluating barrier count: {e}")
                            barrier_count = ir.Constant(ir.IntType(32), 1)
                
                # Initialize the barrier
                barrier_ty = ir.IntType(8).as_pointer()
                barrier_storage, _, _ = self.globals[name]
                barrier_ptr = self.builder.bitcast(barrier_storage, barrier_ty)
                # Don't update globals with the bitcast instruction - keep the original storage
                # self.globals[name] = (barrier_ptr, 'barrier')  # This was the bug!
                
                barrier_init = self.module.globals.get('pthread_barrier_init')
                if not barrier_init:
                    barrier_init_ty = ir.FunctionType(ir.IntType(32), [barrier_ty, ir.IntType(8).as_pointer(), ir.IntType(32)])
                    barrier_init = ir.Function(self.module, barrier_init_ty, name='pthread_barrier_init')
                null_attr = ir.Constant(ir.IntType(8).as_pointer(), None)
                debug_print(f"DEBUG: visit_declaration - calling pthread_barrier_init with count: {barrier_count}")
                self.builder.call(barrier_init, [barrier_ptr, null_attr, barrier_count])
            return
            
        init = node['init']
        var_type = init.get('var_type', 'int')
        
        # Validate assignment operator for constants
        assignment_op = init.get('assignment_op')
        if assignment_op is not None:  # Only check if there's an assignment
            if is_constant and assignment_op != '=':
                raise Exception(f"Constants must be assigned using '=' operator, not '{assignment_op}'. Found in declaration of '{name}'.")
            elif not is_constant and assignment_op != ':=':
                raise Exception(f"Mutable variables must be assigned using ':=' operator, not '{assignment_op}'. Found in declaration of '{name}'.")
        
        # Check if this is a special function call (mutex, semaphore, etc.)
        init_value_expr = init.get('value')
        if (isinstance(init_value_expr, dict) and 
            init_value_expr.get('type') == 'function_call'):
            
            func_name = init_value_expr.get('name')
            if func_name == 'mutex':
                var_type = 'mutex'
                evaluated_value = None  # Will be handled by mutex logic below
            elif func_name == 'semaphore':
                var_type = 'semaphore'
                # Extract initial value from semaphore function arguments
                args = init_value_expr.get('arguments', [])
                if args and args[0].get('type') == 'literal':
                    evaluated_value = args[0]['value']
                else:
                    evaluated_value = 0  # Default semaphore value
            else:
                # Regular function call - evaluate it
                evaluated_value = self.visit(init_value_expr)
        elif init_value_expr is not None:
            # Visit the initialization expression to get the LLVM value
            evaluated_value = self.visit(init_value_expr)
        else:
            evaluated_value = None
            
        # For type inference, we need to look at the expression type, not the raw value
        raw_value = init_value_expr.get('value') if isinstance(init_value_expr, dict) else None

        # Detect thread array type from create_threads function_call
        if var_type is None and isinstance(init_value_expr, dict) and init_value_expr.get('type') == 'function_call' and init_value_expr.get('name') == 'create_threads':
            var_type = 'thread_array'
            # Execute the function call and get the threads pointer
            threads_ptr = evaluated_value  # Already evaluated above
            debug_print(f"DEBUG: visit_declaration - create_threads returned: {threads_ptr}, type: {getattr(threads_ptr, 'type', type(threads_ptr))}")
            # Store the threads pointer in locals with the correct type
            self.locals[name] = (threads_ptr, 'thread_array', is_constant)
            return
        
        # Detect semaphore, mutex, or barrier type from function_call
        if var_type is None and isinstance(init_value_expr, dict) and init_value_expr.get('type') == 'function_call':
            fname = init_value_expr.get('name')
            if fname == 'semaphore':
                var_type = 'semaphore'
                args = init_value_expr.get('arguments', [])
                raw_value = args[0]['value'] if args and args[0].get('type') == 'literal' else None
            elif fname == 'mutex':
                var_type = 'mutex'
                raw_value = None  # Mutexes don't take initial values
            elif fname == 'barrier':
                var_type = 'barrier'
                args = init_value_expr.get('arguments', [])
                raw_value = args[0]['value'] if args and args[0].get('type') == 'literal' else None
            elif fname == 'variant':
                var_type = 'variant'
                # Variants can be initialized with any value
                raw_value = None

        if var_type == 'semaphore':
            sem_ty = ir.IntType(8).as_pointer()
            if shared:
                sem_storage, _, _ = self.globals[name]
                sem_ptr = self.builder.bitcast(sem_storage, sem_ty)
                self.globals[name] = (sem_ptr, 'semaphore', False)
                if self.current_function_name == 'main':
                    sem_init = self.module.globals.get('sem_init')
                    if not sem_init:
                        sem_init_ty = ir.FunctionType(ir.IntType(32), [sem_ty, ir.IntType(32), ir.IntType(32)])
                        sem_init = ir.Function(self.module, sem_init_ty, name='sem_init')
                    pshared = ir.Constant(ir.IntType(32), 0)
                    init_int = evaluated_value if isinstance(evaluated_value, int) else 0
                    initial = ir.Constant(ir.IntType(32), init_int)
                    self.builder.call(sem_init, [sem_ptr, pshared, initial])
                return
            else:
                sem_storage_ty = ir.ArrayType(ir.IntType(8), 32)
                variable = self.builder.alloca(sem_storage_ty, name=f"{name}_storage")
                sem_ptr = self.builder.bitcast(variable, sem_ty)
                self.locals[name] = (sem_ptr, 'semaphore', is_constant)
                if isinstance(evaluated_value, int):
                    sem_init = self.module.globals.get('sem_init')
                    if not sem_init:
                        sem_init_ty = ir.FunctionType(ir.IntType(32), [sem_ty, ir.IntType(32), ir.IntType(32)])
                        sem_init = ir.Function(self.module, sem_init_ty, name='sem_init')
                    pshared = ir.Constant(ir.IntType(32), 0)
                    initial = ir.Constant(ir.IntType(32), evaluated_value)
                    self.builder.call(sem_init, [sem_ptr, pshared, initial])
                return

        if var_type == 'mutex':
            mutex_ty = ir.IntType(8).as_pointer()
            if shared:
                mutex_storage, _, _ = self.globals[name]
                mutex_ptr = self.builder.bitcast(mutex_storage, mutex_ty)
                self.globals[name] = (mutex_ptr, 'mutex', False)
                if self.current_function_name == 'main':
                    pthread_mutex_init = self.module.globals.get('pthread_mutex_init')
                    if not pthread_mutex_init:
                        pthread_mutex_init_ty = ir.FunctionType(ir.IntType(32), [mutex_ty, ir.IntType(8).as_pointer()])
                        pthread_mutex_init = ir.Function(self.module, pthread_mutex_init_ty, name='pthread_mutex_init')
                    # Initialize with NULL attributes (default mutex)
                    null_attr = ir.Constant(ir.IntType(8).as_pointer(), None)
                    self.builder.call(pthread_mutex_init, [mutex_ptr, null_attr])
                return
            else:
                mutex_storage_ty = ir.ArrayType(ir.IntType(8), 40)
                variable = self.builder.alloca(mutex_storage_ty, name=f"{name}_storage")
                mutex_ptr = self.builder.bitcast(variable, mutex_ty)
                self.locals[name] = (mutex_ptr, 'mutex', is_constant)
                # Initialize the mutex
                pthread_mutex_init = self.module.globals.get('pthread_mutex_init')
                if not pthread_mutex_init:
                    pthread_mutex_init_ty = ir.FunctionType(ir.IntType(32), [mutex_ty, ir.IntType(8).as_pointer()])
                    pthread_mutex_init = ir.Function(self.module, pthread_mutex_init_ty, name='pthread_mutex_init')
                # Initialize with NULL attributes (default mutex)
                null_attr = ir.Constant(ir.IntType(8).as_pointer(), None)
                self.builder.call(pthread_mutex_init, [mutex_ptr, null_attr])
                return

        if var_type == 'barrier':
            barrier_ty = ir.IntType(8).as_pointer()
            # Determine participant count from barrier() call if present
            barrier_count = ir.Constant(ir.IntType(32), 1)
            if isinstance(init_value_expr, dict) and init_value_expr.get('type') == 'function_call' and init_value_expr.get('name') == 'barrier':
                bargs = init_value_expr.get('arguments', [])
                if bargs:
                    try:
                        cnt = self.visit(bargs[0])
                        if hasattr(cnt, 'type') and isinstance(cnt.type, ir.IntType) and cnt.type.width != 32:
                            cnt = self.builder.trunc(cnt, ir.IntType(32)) if cnt.type.width > 32 else self.builder.zext(cnt, ir.IntType(32))
                        barrier_count = cnt
                    except Exception:
                        barrier_count = ir.Constant(ir.IntType(32), 1)
            if shared:
                barrier_storage, _, _ = self.globals[name]
                barrier_ptr = self.builder.bitcast(barrier_storage, barrier_ty)
                self.globals[name] = (barrier_ptr, 'barrier', False)
                if self.current_function_name == 'main':
                    barrier_init = self.module.globals.get('pthread_barrier_init')
                    if not barrier_init:
                        barrier_init_ty = ir.FunctionType(ir.IntType(32), [barrier_ty, ir.IntType(8).as_pointer(), ir.IntType(32)])
                        barrier_init = ir.Function(self.module, barrier_init_ty, name='pthread_barrier_init')
                    null_attr = ir.Constant(ir.IntType(8).as_pointer(), None)
                    self.builder.call(barrier_init, [barrier_ptr, null_attr, barrier_count])
                return
            else:
                barrier_storage_ty = ir.ArrayType(ir.IntType(8), 128)
                variable = self.builder.alloca(barrier_storage_ty, name=f"{name}_storage")
                barrier_ptr = self.builder.bitcast(variable, barrier_ty)
                self.locals[name] = (barrier_ptr, 'barrier', is_constant)
                barrier_init = self.module.globals.get('pthread_barrier_init')
                if not barrier_init:
                    barrier_init_ty = ir.FunctionType(ir.IntType(32), [barrier_ty, ir.IntType(8).as_pointer(), ir.IntType(32)])
                    barrier_init = ir.Function(self.module, barrier_init_ty, name='pthread_barrier_init')
                null_attr = ir.Constant(ir.IntType(8).as_pointer(), None)
                self.builder.call(barrier_init, [barrier_ptr, null_attr, barrier_count])
                return

        if var_type == 'variant':
            from .base_types import get_variant_type, get_variant_type_tag_enum
            variant_ty = get_variant_type()
            
            if shared:
                # For shared variants, just get the existing global variable and initialize it
                variant_ptr, _, _ = self.globals[name]
                self.globals[name] = (variant_ptr, 'variant', False)
                # The initialization was handled in process_shared_declaration
                return
            else:
                # Create local variant
                variable = self.builder.alloca(variant_ty, name=name)
                self.locals[name] = (variable, 'variant', is_constant)
                
                # Initialize variant based on the provided value
                if evaluated_value is not None:
                    # We need runtime functions to create variants properly
                    # For now, create a null variant and let runtime functions handle it
                    type_tags = get_variant_type_tag_enum()
                    null_tag = ir.Constant(ir.IntType(32), type_tags['null'])
                    null_data = ir.Constant(ir.ArrayType(ir.IntType(8), 16), [ir.Constant(ir.IntType(8), 0)] * 16)
                    null_variant = ir.Constant(variant_ty, [null_tag, null_data])
                    self.builder.store(null_variant, variable)
                    # TODO: Call runtime function to initialize with proper value
                else:
                    # Create null variant
                    type_tags = get_variant_type_tag_enum()
                    null_tag = ir.Constant(ir.IntType(32), type_tags['null'])
                    null_data = ir.Constant(ir.ArrayType(ir.IntType(8), 16), [ir.Constant(ir.IntType(8), 0)] * 16)
                    null_variant = ir.Constant(variant_ty, [null_tag, null_data])
                    self.builder.store(null_variant, variable)
                return

        # Check for array function call before general type inference
        if (isinstance(init_value_expr, dict) and 
            init_value_expr.get('type') == 'function_call' and 
            init_value_expr.get('name') == 'array'):
            # Handle array() function calls for local arrays
            debug_print(f"DEBUG: visit_declaration - handling array() function call for '{name}'")
            array_ptr = evaluated_value  # Already evaluated above
            
            # Extract element type from the array function arguments
            args = init_value_expr.get('arguments', [])
            if len(args) >= 2:
                element_init = args[1]
                if isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'thread':
                    element_type = 'thread'
                elif isinstance(element_init, dict) and element_init.get('type') == 'literal' and element_init.get('value') == 'thread':
                    element_type = 'thread'
                elif isinstance(element_init, dict) and element_init.get('type') == 'literal' and element_init.get('value') == '"thread"':
                    element_type = 'thread'
                elif isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'semaphore':
                    element_type = 'semaphore'
                elif isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'mutex':
                    element_type = 'mutex'
                elif isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'barrier':
                    element_type = 'barrier'
                else:
                    element_type = 'int'
            else:
                element_type = 'int'
            
            # Store the array pointer in locals with array type
            self.locals[name] = (array_ptr, f'array_{element_type}', is_constant)
            return

        from .base_types import get_type, is_variant_type, get_variant_type
        
        # Check if there's an explicit type annotation in the init
        explicit_type = init.get('var_type')
        
        # If there's an explicit type, use it
        if explicit_type is not None:
            var_type = explicit_type
            debug_print(f"DEBUG: visit_declaration - using explicit type: {var_type}")
        # If no explicit type, create as variant (dynamic type) regardless of initialization
        else:
            var_type = 'variant'
            debug_print(f"DEBUG: visit_declaration - no explicit type provided, creating as variant for dynamic typing")
        
        
        # Check if this should be a transparent variant (only for untyped variables)
        if var_type == 'variant':
            # Create variant automatically for transparent variant system
            from .base_types import get_variant_type, get_variant_type_tag_enum, get_type_tag_for_value
            variant_ty = get_variant_type()
            variable = self.builder.alloca(variant_ty, name=name)
            
            if evaluated_value is not None:
                # Create variant with the evaluated value
                type_tag = get_type_tag_for_value(evaluated_value, var_type)
                self._store_variant_value(variable, evaluated_value, type_tag, var_type)
            elif raw_value is not None:
                # Create variant with raw value
                from .base_types import get_raw_type
                llvm_value = ir.Constant(get_raw_type(var_type), raw_value)
                type_tag = get_type_tag_for_value(llvm_value, var_type)
                self._store_variant_value(variable, llvm_value, type_tag, var_type)
            else:
                # Create null variant
                type_tags = get_variant_type_tag_enum()
                self._store_null_variant(variable)
            
            self.locals[name] = (variable, 'variant', is_constant)
        else:
            # System types (int, float, string, semaphore, mutex, etc.) use original logic
            llvm_type = get_type(var_type)
            variable = self.builder.alloca(llvm_type, name=name)
            if evaluated_value is not None:
                # Store the evaluated value directly
                self.builder.store(evaluated_value, variable)
            elif raw_value is not None:
                # Fall back to constant if we have a raw value
                initial_value = ir.Constant(llvm_type, raw_value)
                self.builder.store(initial_value, variable)
            self.locals[name] = (variable, var_type, is_constant)

    def visit_assignment(self, node: Dict[str, Any]) -> None:
        debug_print(f"DEBUG: visit_assignment - Processing assignment: {node}")
        target = node['target']
        value = self.visit(node['value'])
        
        # Handle different types of assignment targets
        if isinstance(target, str):
            # Simple variable assignment
            debug_print(f"DEBUG: visit_assignment - Assigning to variable: {target}")
            entry = self.get_variable(target)
            if entry is None:
                raise Exception(f"Undefined variable in assignment: {target}")
            ptr, dtype, is_constant = entry
            debug_print(f"DEBUG: visit_assignment - Variable {target} has dtype: {dtype}, is_constant: {is_constant}")
            
            # Check if trying to assign to a constant
            if is_constant:
                raise Exception(f"Cannot assign to constant variable '{target}'. Constants can only be set during declaration.")
            
            # Handle transparent variant assignment
            if dtype == 'variant':
                debug_print(f"DEBUG: visit_assignment - Assigning to variant variable: {target}")
                # Determine the type of the value being assigned
                from .base_types import get_type_tag_for_value
                
                if hasattr(value, 'type'):
                    if isinstance(value.type, ir.IntType) and value.type.width == 32:
                        type_tag = get_type_tag_for_value(value, 'int')
                        self._store_variant_value(ptr, value, type_tag, 'int')
                    elif isinstance(value.type, ir.DoubleType):
                        type_tag = get_type_tag_for_value(value, 'float')
                        self._store_variant_value(ptr, value, type_tag, 'float')
                    elif isinstance(value.type, ir.PointerType) and value.type.pointee == ir.IntType(8):
                        type_tag = get_type_tag_for_value(value, 'string')
                        self._store_variant_value(ptr, value, type_tag, 'string')
                    else:
                        # Default to int for unknown types
                        type_tag = get_type_tag_for_value(value, 'int')
                        self._store_variant_value(ptr, value, type_tag, 'int')
                else:
                    # If no type info, store as null
                    self._store_null_variant(ptr)
            else:
                # Non-variant assignment (system types)
                self.builder.store(value, ptr)
        elif isinstance(target, dict) and target['type'] == 'array_access':
            # Array element assignment - get the array element pointer
            array_name = target['array']
            index = self.visit(target['index'])
            
            # Get the array info
            entry = self.get_variable(array_name)
            if entry is None:
                raise Exception(f"Undefined array in assignment: {array_name}")
            
            array_ptr, array_type, is_constant = entry
            
            # Check if trying to assign to a constant array
            if is_constant:
                raise Exception(f"Cannot assign to constant array '{array_name}'. Constants can only be set during declaration.")
            
            # Calculate element pointer - handle variant indices
            zero = ir.Constant(ir.IntType(32), 0)
            
            # If index is a variant, extract the integer value
            if hasattr(index, 'type'):
                from .base_types import get_variant_type
                variant_ty = get_variant_type()
                if index.type == variant_ty:
                    # Index is a variant struct - need to create temp and extract
                    temp_var = self.builder.alloca(variant_ty, name="temp_index_variant")
                    self.builder.store(index, temp_var)
                    index = self._extract_variant_value(temp_var, 'int')
                elif isinstance(index.type, ir.PointerType) and index.type.pointee == variant_ty:
                    # Index is pointer to variant - extract directly
                    index = self._extract_variant_value(index, 'int')
            
            element_ptr = self.builder.gep(array_ptr, [zero, index])
            
            # Handle variant values - extract the appropriate type for the array
            if hasattr(value, 'type'):
                from .base_types import get_variant_type
                variant_ty = get_variant_type()
                if value.type == variant_ty:
                    # Value is a variant struct - extract based on array type
                    temp_var = self.builder.alloca(variant_ty, name="temp_value_variant")
                    self.builder.store(value, temp_var)
                    if array_type == 'array_int':
                        value = self._extract_variant_value(temp_var, 'int')
                    elif array_type == 'array_thread':
                        value = self._extract_variant_value(temp_var, 'thread')
                    elif array_type == 'array_string':
                        value = self._extract_variant_value(temp_var, 'string')
                    else:
                        # Default to int for unknown array types
                        value = self._extract_variant_value(temp_var, 'int')
                elif isinstance(value.type, ir.PointerType) and value.type.pointee == variant_ty:
                    # Value is pointer to variant - extract directly
                    if array_type == 'array_int':
                        value = self._extract_variant_value(value, 'int')
                    elif array_type == 'array_thread':
                        value = self._extract_variant_value(value, 'thread')
                    elif array_type == 'array_string':
                        value = self._extract_variant_value(value, 'string')
                    else:
                        # Default to int for unknown array types
                        value = self._extract_variant_value(value, 'int')
            
            # Special handling for thread values
            if array_type == 'array_thread' and hasattr(value, 'type'):
                debug_print(f"DEBUG: Array assignment - storing thread value: {value}, type: {getattr(value, 'type', type(value))}")
                if isinstance(value.type, ir.PointerType) and isinstance(value.type.pointee, ir.PointerType):
                    # If value is i8** (pointer to thread handle), load it to get i8* (thread handle)
                    debug_print(f"DEBUG: Array assignment - loading from i8** to get i8* thread handle")
                    loaded_value = self.builder.load(value)
                    debug_print(f"DEBUG: Array assignment - loaded thread handle: {loaded_value}, type: {getattr(loaded_value, 'type', type(loaded_value))}")
                    if loaded_value is None:
                        debug_print("ERROR: Loaded thread handle is None!")
                    value = loaded_value
                elif value.type == ir.IntType(8).as_pointer():
                    debug_print(f"DEBUG: Array assignment - value is already i8* thread handle")
                else:
                    debug_print(f"DEBUG: Array assignment - unexpected thread value type: {value.type}")
            
            # Store the value
            debug_print(f"DEBUG: Array assignment - final store: value={value}, element_ptr={element_ptr}")
            if value is None:
                debug_print("ERROR: Trying to store None value in array!")
            self.builder.store(value, element_ptr)
        elif isinstance(target, dict) and target['type'] == 'dereference':
            # Pointer dereference assignment - handle existing case
            name = node['target']
            entry = self.get_variable(name)
            if entry is None:
                raise Exception(f"Undefined variable in assignment: {name}")
            ptr, dtype, is_constant = entry
            self.builder.store(value, ptr)
        else:
            raise Exception(f"Unsupported assignment target type: {target}")

    def visit_literal(self, node: Dict[str, Any]) -> ir.Constant:
        debug_print(f"DEBUG: visit_literal - Processing node: {node}")
        v = node['value']
        debug_print(f"DEBUG: visit_literal - Value type: {type(v)}, value: {v}")
        debug_print(f"DEBUG: visit_literal - Current locals: {list(self.locals.keys())}")
        # If v is a variable name in locals, return its value using visit_ID
        if v in self.locals:
            debug_print(f"DEBUG: visit_literal - Found '{v}' in locals, treating as variable")
            ptr, dtype, _ = self.locals[v]
            debug_print(f"DEBUG: visit_literal - Variable '{v}' has dtype='{dtype}', ptr type={getattr(ptr, 'type', 'unknown')}")
            if dtype == 'int':
                loaded = self.builder.load(ptr)
                debug_print(f"DEBUG: visit_literal - Loaded int value: {loaded}, type: {getattr(loaded, 'type', 'unknown')}")
                return loaded
            elif dtype == 'float':
                return self.builder.load(ptr)
            elif dtype == 'string':
                return ptr
            elif dtype == 'semaphore':
                return ptr
            else:
                loaded = self.builder.load(ptr)
                debug_print(f"DEBUG: visit_literal - Loaded default value: {loaded}, type: {getattr(loaded, 'type', 'unknown')}")
                return loaded
        if isinstance(v, int):
            result = ir.Constant(ir.IntType(32), v)
            debug_print(f"DEBUG: visit_literal - Created integer constant: {result}")
            return result
        if isinstance(v, float):
            result = ir.Constant(ir.DoubleType(), v)
            debug_print(f"DEBUG: visit_literal - Created float constant: {result}")
            return result
        if isinstance(v, str):
            # Check if this string literal is actually a variable name (workaround for parser issue)
            if v in self.globals or v in self.locals:
                debug_print(f"DEBUG: visit_literal - String '{v}' found as variable, treating as ID")
                return self.visit_ID({'type': 'ID', 'value': v})
            
            # Create a global string for the literal
            name = f"str_{abs(hash(v))}"
            debug_print(f"DEBUG: visit_literal - Creating string with hash name: {name}")
            str_bytes = bytearray(v.encode("utf8")) + b"\00"
            str_type = ir.ArrayType(ir.IntType(8), len(str_bytes))
            debug_print(f"DEBUG: visit_literal - String bytes length: {len(str_bytes)}")
            if name in self.module.globals:
                debug_print(f"DEBUG: visit_literal - Reusing existing global string: {name}")
                str_global = self.module.get_global(name)
            else:
                debug_print(f"DEBUG: visit_literal - Creating new global string: {name}")
                str_global = ir.GlobalVariable(self.module, str_type, name=name)
                str_global.linkage = 'internal'
                str_global.global_constant = True
                str_global.initializer = ir.Constant(str_type, str_bytes)
            result = self.builder.bitcast(str_global, ir.IntType(8).as_pointer())
            debug_print(f"DEBUG: visit_literal - Created string pointer: {result}")
            return result
        debug_print(f"DEBUG: visit_literal - ERROR: Unsupported literal type: {type(v)} with value {v}")
        raise Exception(f"Unsupported literal type: {type(v)} with value {v}")

    def visit_binary_op(self, node: Dict[str, Any]) -> ir.Value:
        left_raw = self.visit(node['left'])
        right_raw = self.visit(node['right'])
        op = node['op']

        # Determine the appropriate type for the operation
        # First, try to extract without forcing type to see what we have
        left_test = self._auto_extract_value(left_raw, 'auto')  # Don't force type yet
        right_test = self._auto_extract_value(right_raw, 'auto')  # Don't force type yet
        
        # Determine operation type based on operand types
        operation_type = 'int'  # default
        if (hasattr(left_test, 'type') and isinstance(left_test.type, ir.DoubleType)) or \
           (hasattr(right_test, 'type') and isinstance(right_test.type, ir.DoubleType)):
            operation_type = 'float'
        
        # Now extract values with the determined type
        left = self._auto_extract_value(left_raw, operation_type)
        right = self._auto_extract_value(right_raw, operation_type)
        
        # If we're doing float operations, ensure both operands are float type
        if operation_type == 'float':
            if hasattr(left, 'type') and isinstance(left.type, ir.IntType):
                # Convert integer to float
                left = self.builder.sitofp(left, ir.DoubleType())
            if hasattr(right, 'type') and isinstance(right.type, ir.IntType):
                # Convert integer to float
                right = self.builder.sitofp(right, ir.DoubleType())
        
        # For arithmetic operations with floats, use float operations
        if op == '+':
            if operation_type == 'float':
                return self.builder.fadd(left, right)
            else:
                return self.builder.add(left, right)
        elif op == '-':
            if operation_type == 'float':
                return self.builder.fsub(left, right)
            else:
                return self.builder.sub(left, right)
        elif op == '*':
            if operation_type == 'float':
                return self.builder.fmul(left, right)
            else:
                return self.builder.mul(left, right)
        elif op == '/':
            if operation_type == 'float':
                return self.builder.fdiv(left, right)
            else:
                return self.builder.sdiv(left, right)
        
        # Comparison operators
        if op in ['=', '!=', '<', '<=', '>', '>=']:
            if hasattr(left, 'type') and hasattr(right, 'type'):
                if left.type != right.type:
                    raise Exception(f"Type mismatch in comparison: {left.type} vs {right.type}")
                if isinstance(left.type, ir.PointerType):
                    raise Exception("Direct comparison of pointers (e.g., strings) is not supported. Use a string comparison function.")
                
                # Map operators to LLVM predicates
                op_map = {
                    '=': '==',  
                    '==': '==', 
                    '!=': '!=',
                    '<': '<',
                    '<=': '<=',
                    '>': '>',
                    '>=': '>='
                }
                return self.builder.icmp_signed(op_map[op], left, right)
        
        # Logical operators
        elif op == 'and':
            return self.builder.and_(left, right)
        elif op == 'or':
            return self.builder.or_(left, right)
            
        # Add more operators as needed
        else:
            raise Exception(f"Unsupported operator: {op}")

    def visit_body(self, node: List[Dict[str, Any]]) -> None:
        self.visit(node)

    def visit_if(self, node: Dict[str, Any]) -> None:
        cond_val = self.visit(node['condition'])
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
        self.builder.branch(end_bb)
        # Else block
        if else_bb:
            self.builder.position_at_start(else_bb)
            self.visit(node['else_body'])
            self.builder.branch(end_bb)
        # End block
        self.builder.position_at_start(end_bb)

    def visit_while(self, node: Dict[str, Any]) -> None:
        cond_bb = self.builder.append_basic_block('while.cond')
        body_bb = self.builder.append_basic_block('while.body')
        end_bb = self.builder.append_basic_block('while.end')
        self.builder.branch(cond_bb)
        self.builder.position_at_start(cond_bb)
        cond_val = self.visit(node['condition'])
        self.builder.cbranch(cond_val, body_bb, end_bb)
        self.builder.position_at_start(body_bb)
        self.visit(node['body'])
        self.builder.branch(cond_bb)
        self.builder.position_at_start(end_bb)

    def visit_for(self, node: Dict[str, Any]) -> None:
        # Only support integer for-loops: for i := start to end
        var = node['iterator']
        start = self.visit(node['start'])
        end = self.visit(node['end'])
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
        self.visit(node['body'])
        idx = self.builder.load(ptr)
        next_idx = self.builder.add(idx, ir.Constant(ir.IntType(32), 1))
        self.builder.store(next_idx, ptr)
        self.builder.branch(cond_bb)
        self.builder.position_at_start(end_bb)

    def visit_print(self, node: Dict[str, Any]) -> None:
        expression = node.get('expression')
        format_str = node.get('format')
        debug_print(f"PRINT DEBUG: Processing print node: {node}")
        debug_print(f"DEBUG: visit_print - expression: {expression}")
        debug_print(f"DEBUG: visit_print - format: {format_str}")
        debug_print(f"DEBUG: visit_print - full node: {node}")
        
        # Check if this is a template string in the format field
        if format_str and isinstance(format_str, str) and format_str.startswith('`') and format_str.endswith('`'):
            # Handle template string from format field
            template = format_str[1:-1]  # Remove backticks
            debug_print(f"FORMAT TEMPLATE DEBUG: Processing format template: '{template}'")
            debug_print(f"DEBUG: visit_print - processing template string from format field: {template}")
            
            # Use the same template processing logic as in the expression field
            import re
            
            # Find all variables in the template string {variable_name}
            variable_patterns = re.findall(r'\{([^}]+)\}', template)
            debug_print(f"DEBUG: visit_print - found variables in format template: {variable_patterns}")
            
            if variable_patterns:
                # Use sprintf to format the string with actual variable values
                format_string = template
                format_args = []
                
                # Replace each variable with appropriate format specifier and get values
                for var_name in variable_patterns:
                    # Get the variable value first to determine its type
                    try:
                        var_value = self.visit_ID({'type': 'ID', 'value': var_name})
                        
                        # Check if this is a variant
                        entry = self.get_variable(var_name)
                        if entry and entry[1] == 'variant':
                            # For variants, use %s format and call variant_to_string runtime function
                            format_string = format_string.replace(f'{{{var_name}}}', '%s')
                            
                            # Get or create the variant_to_string runtime function
                            from .base_types import get_variant_type
                            variant_ty = get_variant_type()
                            variant_to_string = self.module.globals.get('variant_to_string')
                            if not variant_to_string:
                                func_ty = ir.FunctionType(ir.IntType(8).as_pointer(), [variant_ty.as_pointer()])
                                variant_to_string = ir.Function(self.module, func_ty, name='variant_to_string')
                            
                            # Pass the variant pointer directly (no loading needed)
                            if hasattr(var_value, 'type') and isinstance(var_value.type, ir.PointerType):
                                variant_ptr = var_value
                            else:
                                # If it's not a pointer, we need to create one
                                temp_ptr = self.builder.alloca(variant_ty, name=f"temp_{var_name}")
                                self.builder.store(var_value, temp_ptr)
                                variant_ptr = temp_ptr
                            
                            # Call variant_to_string to get the string representation
                            string_result = self.builder.call(variant_to_string, [variant_ptr])
                            format_args.append(string_result)
                            debug_print(f"DEBUG: visit_print - added variant {var_name} using variant_to_string")
                        else:
                            # For non-variants, determine format based on variable type
                            entry = self.get_variable(var_name)
                            if entry and len(entry) >= 2:
                                dtype = entry[1]
                                if dtype == 'float':
                                    format_string = format_string.replace(f'{{{var_name}}}', '%f')
                                else:
                                    format_string = format_string.replace(f'{{{var_name}}}', '%d')
                            else:
                                format_string = format_string.replace(f'{{{var_name}}}', '%d')
                            
                            if hasattr(var_value, 'type') and isinstance(var_value.type, ir.PointerType):
                                var_value = self.builder.load(var_value)
                            format_args.append(var_value)
                            debug_print(f"DEBUG: visit_print - added {var_name} = {var_value} to format args")
                    except Exception as e:
                        debug_print(f"DEBUG: visit_print - could not resolve variable {var_name}: {e}")
                        # Fall back to 0 if variable can't be resolved
                        format_string = format_string.replace(f'{{{var_name}}}', '%d')
                        format_args.append(ir.Constant(ir.IntType(32), 0))
                
                # Create format string
                format_name = f"format_str_{abs(hash(format_string))}"
                format_bytes = bytearray(format_string.encode("utf8")) + b"\00"
                format_type = ir.ArrayType(ir.IntType(8), len(format_bytes))
                
                if format_name in self.module.globals:
                    format_global = self.module.get_global(format_name)
                else:
                    format_global = ir.GlobalVariable(self.module, format_type, name=format_name)
                    format_global.linkage = 'internal'
                    format_global.global_constant = True
                    format_global.initializer = ir.Constant(format_type, format_bytes)
                
                format_arg = self.builder.bitcast(format_global, ir.IntType(8).as_pointer())
                
                # Create buffer for sprintf output
                buffer_size = 256  # Should be enough for most strings
                buffer_type = ir.ArrayType(ir.IntType(8), buffer_size)
                buffer = self.builder.alloca(buffer_type, name="sprintf_buffer")
                buffer_ptr = self.builder.bitcast(buffer, ir.IntType(8).as_pointer())
                
                # Get or create sprintf function
                sprintf = self.module.globals.get('sprintf')
                if not sprintf:
                    sprintf_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer(), ir.IntType(8).as_pointer()], var_arg=True)
                    sprintf = ir.Function(self.module, sprintf_ty, name="sprintf")
                
                # Call sprintf with format string and variables
                sprintf_args = [buffer_ptr, format_arg] + format_args
                self.builder.call(sprintf, sprintf_args)
                
                val = buffer_ptr
                is_string = True
            else:
                # No variables in template, treat as simple string
                processed_string = template
                debug_print(f"DEBUG: visit_print - no variables in format template: {processed_string}")
                
                # Create string literal
                name = f"str_{abs(hash(processed_string))}"
                str_bytes = bytearray(processed_string.encode("utf8")) + b"\00"
                str_type = ir.ArrayType(ir.IntType(8), len(str_bytes))
                
                if name in self.module.globals:
                    str_global = self.module.get_global(name)
                else:
                    str_global = ir.GlobalVariable(self.module, str_type, name=name)
                    str_global.linkage = 'internal'
                    str_global.global_constant = True
                    str_global.initializer = ir.Constant(str_type, str_bytes)
                
                val = self.builder.bitcast(str_global, ir.IntType(8).as_pointer())
                is_string = True
        elif (isinstance(expression, str) and
            expression.startswith('`') and 
            expression.endswith('`')):
            
            # Handle template string
            template = expression[1:-1]  # Remove backticks
            debug_print(f"DEBUG: visit_print - processing raw template string: {template}")
            
            # Implement proper template variable substitution (same logic as the other template handler)
            import re
            
            # Find all variables in the template string {variable_name}
            variable_patterns = re.findall(r'\{([^}]+)\}', template)
            debug_print(f"DEBUG: visit_print - found variables in template: {variable_patterns}")
            
            if variable_patterns:
                # Use sprintf to format the string with actual variable values
                format_string = template
                format_args = []
                
                # Replace each variable with appropriate format specifier based on type
                for var_name in variable_patterns:
                    # Determine format based on variable type
                    entry = self.get_variable(var_name)
                    if entry and len(entry) >= 2:
                        dtype = entry[1]
                        if dtype == 'float':
                            format_string = format_string.replace(f'{{{var_name}}}', '%f')
                        else:
                            format_string = format_string.replace(f'{{{var_name}}}', '%d')
                    else:
                        format_string = format_string.replace(f'{{{var_name}}}', '%d')
                    
                    # Get the variable value
                    try:
                        var_value = self.visit_ID({'type': 'ID', 'value': var_name})
                        if hasattr(var_value, 'type') and isinstance(var_value.type, ir.PointerType):
                            var_value = self.builder.load(var_value)
                        format_args.append(var_value)
                        debug_print(f"DEBUG: visit_print - added {var_name} = {var_value} to format args")
                    except Exception as e:
                        debug_print(f"DEBUG: visit_print - could not resolve variable {var_name}: {e}")
                        # Fall back to 0 if variable can't be resolved
                        format_args.append(ir.Constant(ir.IntType(32), 0))
                
                # Create format string
                format_name = f"format_str_{abs(hash(format_string))}"
                format_bytes = bytearray(format_string.encode("utf8")) + b"\00"
                format_type = ir.ArrayType(ir.IntType(8), len(format_bytes))
                
                if format_name in self.module.globals:
                    format_global = self.module.get_global(format_name)
                else:
                    format_global = ir.GlobalVariable(self.module, format_type, name=format_name)
                    format_global.linkage = 'internal'
                    format_global.global_constant = True
                    format_global.initializer = ir.Constant(format_type, format_bytes)
                
                format_arg = self.builder.bitcast(format_global, ir.IntType(8).as_pointer())
                
                # Create buffer for sprintf output
                buffer_size = 256  # Should be enough for most strings
                buffer_type = ir.ArrayType(ir.IntType(8), buffer_size)
                buffer = self.builder.alloca(buffer_type, name="sprintf_buffer")
                buffer_ptr = self.builder.bitcast(buffer, ir.IntType(8).as_pointer())
                
                # Get or create sprintf function
                sprintf = self.module.globals.get('sprintf')
                if not sprintf:
                    sprintf_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer(), ir.IntType(8).as_pointer()], var_arg=True)
                    sprintf = ir.Function(self.module, sprintf_ty, name="sprintf")
                
                # Call sprintf with format string and variables
                sprintf_args = [buffer_ptr, format_arg] + format_args
                self.builder.call(sprintf, sprintf_args)
                
                val = buffer_ptr
                is_string = True
            else:
                # No variables in template, treat as simple string
                processed_string = template
                debug_print(f"DEBUG: visit_print - no variables in template: {processed_string}")
                
                # Create string literal
                name = f"str_{abs(hash(processed_string))}"
                str_bytes = bytearray(processed_string.encode("utf8")) + b"\00"
                str_type = ir.ArrayType(ir.IntType(8), len(str_bytes))
                
                if name in self.module.globals:
                    str_global = self.module.get_global(name)
                else:
                    str_global = ir.GlobalVariable(self.module, str_type, name=name)
                    str_global.linkage = 'internal'
                    str_global.global_constant = True
                    str_global.initializer = ir.Constant(str_type, str_bytes)
                
                val = self.builder.bitcast(str_global, ir.IntType(8).as_pointer())
                is_string = True
            name = f"str_{abs(hash(processed_string))}"
            str_bytes = bytearray(processed_string.encode("utf8")) + b"\00"
            str_type = ir.ArrayType(ir.IntType(8), len(str_bytes))
            
            if name in self.module.globals:
                str_global = self.module.get_global(name)
            else:
                str_global = ir.GlobalVariable(self.module, str_type, name=name)
                str_global.linkage = 'internal'
                str_global.global_constant = True
                str_global.initializer = ir.Constant(str_type, str_bytes)
            
            val = self.builder.bitcast(str_global, ir.IntType(8).as_pointer())
            is_string = True
        # Check if this is a template string in literal node format
        elif (isinstance(expression, dict) and 
            expression.get('type') == 'literal' and 
            isinstance(expression.get('value'), str) and
            expression['value'].startswith('`') and 
            expression['value'].endswith('`')):
            
            # Handle template string
            template = expression['value'][1:-1]  # Remove backticks
            debug_print(f"TEMPLATE DEBUG: Processing template: '{template}'")
            debug_print(f"DEBUG: visit_print - processing template string: {template}")
            
            # Implement proper template variable substitution
            import re
            
            # Find all variables in the template string {variable_name}
            variable_patterns = re.findall(r'\{([^}]+)\}', template)
            debug_print(f"DEBUG: visit_print - found variables in template: {variable_patterns}")
            
            if variable_patterns:
                # Use sprintf to format the string with actual variable values
                format_string = template
                format_args = []
                
                # Replace each variable with appropriate format specifier based on type
                for var_name in variable_patterns:
                    # Determine format based on variable type
                    entry = self.get_variable(var_name)
                    if entry and len(entry) >= 2:
                        dtype = entry[1]
                        if dtype == 'float':
                            format_string = format_string.replace(f'{{{var_name}}}', '%f')
                        else:
                            format_string = format_string.replace(f'{{{var_name}}}', '%d')
                    else:
                        format_string = format_string.replace(f'{{{var_name}}}', '%d')
                    
                    # Get the variable value
                    try:
                        var_value = self.visit_ID({'type': 'ID', 'value': var_name})
                        if hasattr(var_value, 'type') and isinstance(var_value.type, ir.PointerType):
                            var_value = self.builder.load(var_value)
                        format_args.append(var_value)
                        debug_print(f"DEBUG: visit_print - added {var_name} = {var_value} to format args")
                    except Exception as e:
                        debug_print(f"DEBUG: visit_print - could not resolve variable {var_name}: {e}")
                        # Fall back to 0 if variable can't be resolved
                        format_args.append(ir.Constant(ir.IntType(32), 0))
                
                # Create format string
                format_name = f"format_str_{abs(hash(format_string))}"
                format_bytes = bytearray(format_string.encode("utf8")) + b"\00"
                format_type = ir.ArrayType(ir.IntType(8), len(format_bytes))
                
                if format_name in self.module.globals:
                    format_global = self.module.get_global(format_name)
                else:
                    format_global = ir.GlobalVariable(self.module, format_type, name=format_name)
                    format_global.linkage = 'internal'
                    format_global.global_constant = True
                    format_global.initializer = ir.Constant(format_type, format_bytes)
                
                format_arg = self.builder.bitcast(format_global, ir.IntType(8).as_pointer())
                
                # Create buffer for sprintf output
                buffer_size = 256  # Should be enough for most strings
                buffer_type = ir.ArrayType(ir.IntType(8), buffer_size)
                buffer = self.builder.alloca(buffer_type, name="sprintf_buffer")
                buffer_ptr = self.builder.bitcast(buffer, ir.IntType(8).as_pointer())
                
                # Get or create sprintf function
                sprintf = self.module.globals.get('sprintf')
                if not sprintf:
                    sprintf_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer(), ir.IntType(8).as_pointer()], var_arg=True)
                    sprintf = ir.Function(self.module, sprintf_ty, name="sprintf")
                
                # Call sprintf with format string and variables
                sprintf_args = [buffer_ptr, format_arg] + format_args
                self.builder.call(sprintf, sprintf_args)
                
                val = buffer_ptr
                is_string = True
            else:
                # No variables in template, treat as simple string
                processed_string = template
                debug_print(f"DEBUG: visit_print - no variables in template: {processed_string}")
                
                # Create string literal
                name = f"str_{abs(hash(processed_string))}"
                str_bytes = bytearray(processed_string.encode("utf8")) + b"\00"
                str_type = ir.ArrayType(ir.IntType(8), len(str_bytes))
                
                if name in self.module.globals:
                    str_global = self.module.get_global(name)
                else:
                    str_global = ir.GlobalVariable(self.module, str_type, name=name)
                    str_global.linkage = 'internal'
                    str_global.global_constant = True
                    str_global.initializer = ir.Constant(str_type, str_bytes)
                
                val = self.builder.bitcast(str_global, ir.IntType(8).as_pointer())
                is_string = True
        else:
            # Handle regular expressions
            val = self.visit(expression)
            # Detect if val is a string pointer or int
            is_string = False
            if isinstance(expression, dict) and expression.get('type') == 'literal':
                if isinstance(expression['value'], str):
                    is_string = True
        
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

        # Build scanf format string: one %d per variable, separated by spaces
        scanf_format = ' '.join(['%d'] * len(var_names)) + '\0'
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
        for var_name in var_names:
            entry = self.get_variable(var_name, prefer_globals=True)
            if entry is None:
                raise Exception(f"Undefined variable in SCAN: {var_name}")
            var_ptr, dtype, is_constant = entry
            debug_print(f"DEBUG: visit_scan - var '{var_name}' ptr type: {getattr(var_ptr, 'type', None)}, dtype: {dtype}")

            # Ensure we pass a pointer to i32 for %d
            if not hasattr(var_ptr, 'type') or not isinstance(var_ptr.type, ir.PointerType):
                raise Exception(f"Variable '{var_name}' is not addressable for SCAN")
            if not isinstance(var_ptr.type.pointee, ir.IntType) or var_ptr.type.pointee.width != 32:
                raise Exception(f"SCAN currently supports only int variables. '{var_name}' has type: {var_ptr.type}")
            scanf_args.append(var_ptr)

        # Declare or get scanf
        scanf = self.module.globals.get('scanf')
        if not scanf:
            scanf_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()], var_arg=True)
            scanf = ir.Function(self.module, scanf_ty, name="scanf")

        # Call scanf
        debug_print(f"DEBUG: visit_scan - calling scanf with {len(scanf_args)-1} variables")
        self.builder.call(scanf, scanf_args)

    def visit_ID(self, node: Dict[str, Any], prefer_globals: bool = False) -> ir.Value:
        name = node['value']
        debug_print(f"DEBUG: visit_ID searching for '{name}', prefer_globals={prefer_globals}")
        debug_print(f"DEBUG: visit_ID - current locals: {list(self.locals.keys())}")
        debug_print(f"DEBUG: visit_ID - current globals: {list(self.globals.keys())}")
        entry = self.get_variable(name, prefer_globals)
        if entry is None:
            raise Exception(f"Undefined variable: {name}")
        
        ptr, dtype, is_constant = entry
        debug_print(f"DEBUG: visit_ID for '{name}', dtype={dtype}, ptr type={getattr(ptr, 'type', None)}")
        debug_print(f"DEBUG: visit_ID - ptr value: {ptr}")

        # Use dtype to determine how to load or return the value
        if dtype == 'semaphore':
            # Always return the pointer as-is for semaphores
            return ptr
        elif dtype == 'mutex':
            # Always return the pointer as-is for mutexes
            return ptr
        elif dtype == 'barrier':
            # Always return the pointer as-is for barriers
            # If this is a global barrier storage, we need to bitcast it to i8*
            if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
                pointee = ptr.type.pointee
                if isinstance(pointee, ir.ArrayType) and pointee.element == ir.IntType(8):
                    # This is barrier storage - bitcast to i8*
                    barrier_ty = ir.IntType(8).as_pointer()
                    barrier_ptr = self.builder.bitcast(ptr, barrier_ty)
                    debug_print(f"DEBUG: visit_ID - generated bitcast for barrier: {barrier_ptr}")
                    return barrier_ptr
            debug_print(f"DEBUG: visit_ID - returning barrier pointer: {ptr}")
            return ptr
        elif dtype == 'variant':
            # For variants, return the pointer to the variant struct
            # Runtime functions will handle extracting values
            return ptr
        elif dtype == 'int':
            # Load the value if it's a pointer
            if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
                return self.builder.load(ptr)
            return ptr
        elif dtype == 'float':
            if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
                return self.builder.load(ptr)
            return ptr
        elif dtype == 'string':
            # Strings are pointers, return as-is
            return ptr
        elif dtype is not None:
            # For other types, try to load if pointer
            if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
                return self.builder.load(ptr)
            return ptr
        # Fallback to previous logic if dtype is not set
        if hasattr(ptr, 'type') and isinstance(ptr.type, ir.PointerType):
            pointee = ptr.type.pointee
            if pointee == ir.IntType(8):
                debug_print(f"DEBUG: visit_ID returning i8* pointer for '{name}'")
                return ptr
            if isinstance(pointee, ir.PointerType) and pointee.pointee == ir.IntType(8):
                loaded = self.builder.load(ptr)
                debug_print(f"DEBUG: visit_ID loaded i8* from i8** for '{name}'")
                return loaded
            if isinstance(pointee, ir.IntType) and pointee.width == 32:
                loaded = self.builder.load(ptr)
                debug_print(f"DEBUG: visit_ID loaded i32 value for '{name}'")
                return loaded
            if isinstance(pointee, ir.DoubleType):
                loaded = self.builder.load(ptr)
                debug_print(f"DEBUG: visit_ID loaded double value for '{name}'")
                return loaded
        debug_print(f"DEBUG: visit_ID returning ptr as-is for '{name}' (type: {getattr(ptr, 'type', None)})")
        return ptr

    def visit_func_call(self, node: Dict[str, Any]) -> ir.Value:
        # Special handling for create_threads, create_thread, wait, and signal
        func_name = node['name']['value'] if isinstance(node['name'], dict) else node['name']
        if func_name == 'create_threads':
            # New argument order: create_threads(thread_count, target_func)
            thread_count_arg = node['arguments'][0]
            target_func_arg = node['arguments'][1]
            target_func = target_func_arg['value'] if isinstance(target_func_arg, dict) else target_func_arg
            if isinstance(thread_count_arg, dict) and thread_count_arg.get('type') == 'literal':
                thread_count_value = thread_count_arg['value']
                # If it's a string, treat it as a variable name and look it up
                if isinstance(thread_count_value, str):
                    # Look up the variable in globals or locals
                    if thread_count_value in self.globals:
                        var_ptr, var_type, _ = self.globals[thread_count_value]
                        thread_count = self.builder.load(var_ptr) if var_type in ('int', 'float') or var_type is None else var_ptr
                    elif thread_count_value in self.locals:
                        var_ptr, var_type, _ = self.locals[thread_count_value]
                        thread_count = self.builder.load(var_ptr) if var_type in ('int', 'float') or var_type is None else var_ptr
                    else:
                        raise Exception(f"Undefined variable in create_threads: {thread_count_value}")
                else:
                    # It's a numeric literal
                    thread_count = ir.Constant(ir.IntType(32), thread_count_value)
            else:
                # Process normally if it's not a literal
                thread_count = self.visit(thread_count_arg)
                
            if target_func not in self.funcs:
                raise Exception(f"Undefined function: {target_func}")
            target_func_obj = self.funcs[target_func]
            
            # Validate that the target function has at least one parameter (for thread_number)
            if len(target_func_obj.args) == 0:
                raise Exception(f"Function '{target_func}' called by create_threads must have at least one parameter (thread_number)")
            
            return create_threads(self.builder, self.module, thread_count, target_func_obj)
        elif func_name == 'create_thread':
            target_func_arg = node['arguments'][0]
            target_func = target_func_arg['value'] if isinstance(target_func_arg, dict) else target_func_arg
            
            # Process all arguments after the function name
            args = []
            for i in range(1, len(node['arguments'])):
                arg_value = self.visit(node['arguments'][i])
                args.append(arg_value)
            
            if target_func not in self.funcs:
                raise Exception(f"Undefined function: {target_func}")
            target_func_obj = self.funcs[target_func]
            
            # Validate that the target function has the right number of parameters
            if len(target_func_obj.args) != len(args):
                raise Exception(f"Function '{target_func}' expects {len(target_func_obj.args)} arguments, but got {len(args)}")
            
            debug_print(f"DEBUG: create_thread - calling create_thread with target_func: {target_func}, args: {args}")
            result = create_thread(self.builder, self.module, target_func_obj, thread_args=args)
            debug_print(f"DEBUG: create_thread - returned: {result}, type: {getattr(result, 'type', type(result))}")
            return result
        elif func_name == 'join_thread':
            # Join a single thread using pthread_join
            if len(node['arguments']) != 1:
                raise Exception(f"join_thread() requires exactly 1 argument (thread handle), got {len(node['arguments'])}")
            
            debug_print(f"DEBUG: join_thread function call - raw argument: {node['arguments'][0]}")
            thread_arg = self.visit(node['arguments'][0])
            debug_print(f"DEBUG: join_thread() - thread_arg: {thread_arg}, type: {getattr(thread_arg, 'type', type(thread_arg))}")
            
            # Use the join_thread function from threading_utils
            return join_thread(self.builder, self.module, thread_arg)
        elif func_name == 'wait':
            # Semaphore wait operation - maps to sem_wait
            arg0 = node['arguments'][0]
            debug_print(f"DEBUG: wait() - arg0: {arg0}")
            # If argument is a string literal, treat it as a variable name
            if isinstance(arg0, dict) and arg0.get('type') == 'literal' and isinstance(arg0.get('value'), str):
                debug_print(f"DEBUG: wait() - treating arg0 as variable name: {arg0['value']}")
                sem_ptr = self.visit_ID({'type': 'ID', 'value': arg0['value']}, prefer_globals=True)
            elif isinstance(arg0, dict) and arg0.get('type') == 'ID':
                debug_print(f"DEBUG: wait() - treating arg0 as ID")
                sem_ptr = self.visit_ID(arg0, prefer_globals=True)
            else:
                debug_print(f"DEBUG: wait() - visiting arg0 normally")
                sem_ptr = self.visit(arg0)
            debug_print(f"DEBUG: wait() - sem_ptr: {sem_ptr}, type: {getattr(sem_ptr, 'type', type(sem_ptr))}")
            sem_ty = ir.IntType(8).as_pointer()
            if not hasattr(sem_ptr, 'type') or not isinstance(sem_ptr.type, ir.PointerType):
                raise Exception(f"Semaphore argument is not a pointer. Got type: {getattr(sem_ptr, 'type', type(sem_ptr))}")
            if sem_ptr.type != sem_ty:
                sem_ptr = self.builder.bitcast(sem_ptr, sem_ty)
            sem_wait = self.module.globals.get('sem_wait')
            if not sem_wait:
                sem_wait_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()])
                sem_wait = ir.Function(self.module, sem_wait_ty, name='sem_wait')
            debug_print(f"DEBUG: wait() - about to call sem_wait with: {sem_ptr}")
            try:
                result = self.builder.call(sem_wait, [sem_ptr])
                debug_print(f"DEBUG: wait() - sem_wait call succeeded")
                return result
            except Exception as e:
                debug_print(f"DEBUG: wait() - sem_wait call failed: {e}")
                debug_print(f"DEBUG: wait() - sem_ptr type: {getattr(sem_ptr, 'type', type(sem_ptr))}")
                raise
        elif func_name == 'signal':
            # Semaphore signal operation - maps to sem_post
            arg0 = node['arguments'][0]
            if isinstance(arg0, dict) and arg0.get('type') == 'literal' and isinstance(arg0.get('value'), str):
                sem_ptr = self.visit_ID({'type': 'ID', 'value': arg0['value']}, prefer_globals=True)
            elif isinstance(arg0, dict) and arg0.get('type') == 'ID':
                sem_ptr = self.visit_ID(arg0, prefer_globals=True)
            else:
                sem_ptr = self.visit(arg0)
            debug_print(f"DEBUG: signal() sem_ptr type: {getattr(sem_ptr, 'type', type(sem_ptr))}")
            sem_ty = ir.IntType(8).as_pointer()
            if not hasattr(sem_ptr, 'type') or not isinstance(sem_ptr.type, ir.PointerType):
                raise Exception(f"Semaphore argument to signal() is not a pointer. Got type: {getattr(sem_ptr, 'type', type(sem_ptr))} and value: {sem_ptr}")
            if sem_ptr.type != sem_ty:
                sem_ptr = self.builder.bitcast(sem_ptr, sem_ty)
            sem_post = self.module.globals.get('sem_post')
            if not sem_post:
                sem_post_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()])
                sem_post = ir.Function(self.module, sem_post_ty, name='sem_post')
            return self.builder.call(sem_post, [sem_ptr])
        elif func_name == 'barrier_wait':
            # Barrier wait operation - maps to pthread_barrier_wait
            if len(node['arguments']) != 1:
                raise Exception(f"barrier_wait() requires exactly 1 argument (barrier), got {len(node['arguments'])}")
            arg0 = node['arguments'][0]
            debug_print(f"DEBUG: barrier_wait - arg0: {arg0}")
            if isinstance(arg0, dict) and arg0.get('type') == 'literal' and isinstance(arg0.get('value'), str):
                barrier_ptr = self.visit_ID({'type': 'ID', 'value': arg0['value']}, prefer_globals=True)
            elif isinstance(arg0, dict) and arg0.get('type') == 'ID':
                barrier_ptr = self.visit_ID(arg0, prefer_globals=True)
            elif isinstance(arg0, dict) and arg0.get('type') == 'array_access':
                barrier_ptr = self.visit_array_access(arg0)
            else:
                barrier_ptr = self.visit(arg0)
            debug_print(f"DEBUG: barrier_wait - barrier_ptr: {barrier_ptr}, type: {getattr(barrier_ptr, 'type', None)}")
            barrier_ty = ir.IntType(8).as_pointer()
            if not hasattr(barrier_ptr, 'type') or not isinstance(barrier_ptr.type, ir.PointerType):
                raise Exception(f"barrier_wait() argument is not a pointer. Got type: {getattr(barrier_ptr, 'type', type(barrier_ptr))}")
            if barrier_ptr.type != barrier_ty:
                barrier_ptr = self.builder.bitcast(barrier_ptr, barrier_ty)
            debug_print(f"DEBUG: barrier_wait - final barrier_ptr: {barrier_ptr}, type: {getattr(barrier_ptr, 'type', None)}")
            pthread_barrier_wait = self.module.globals.get('pthread_barrier_wait')
            if not pthread_barrier_wait:
                pthread_barrier_wait_ty = ir.FunctionType(ir.IntType(32), [barrier_ty])
                pthread_barrier_wait = ir.Function(self.module, pthread_barrier_wait_ty, name='pthread_barrier_wait')
            return self.builder.call(pthread_barrier_wait, [barrier_ptr])
        elif func_name == 'lock':
            # Mutex lock operation - maps to pthread_mutex_lock  
            arg0 = node['arguments'][0]
            debug_print(f"DEBUG: lock() - arg0: {arg0}")
            # If argument is a string literal, treat it as a variable name
            if isinstance(arg0, dict) and arg0.get('type') == 'literal' and isinstance(arg0.get('value'), str):
                debug_print(f"DEBUG: lock() - treating arg0 as variable name: {arg0['value']}")
                mutex_ptr = self.visit_ID({'type': 'ID', 'value': arg0['value']}, prefer_globals=True)
            elif isinstance(arg0, dict) and arg0.get('type') == 'ID':
                debug_print(f"DEBUG: lock() - treating arg0 as ID")
                mutex_ptr = self.visit_ID(arg0, prefer_globals=True)
            elif isinstance(arg0, dict) and arg0.get('type') == 'array_access':
                debug_print(f"DEBUG: lock() - treating arg0 as array access")
                mutex_ptr = self.visit_array_access(arg0)
            else:
                debug_print(f"DEBUG: lock() - visiting arg0 normally")
                mutex_ptr = self.visit(arg0)
            debug_print(f"DEBUG: lock() - mutex_ptr: {mutex_ptr}, type: {getattr(mutex_ptr, 'type', type(mutex_ptr))}")
            mutex_ty = ir.IntType(8).as_pointer()
            if not hasattr(mutex_ptr, 'type') or not isinstance(mutex_ptr.type, ir.PointerType):
                raise Exception(f"Mutex argument is not a pointer. Got type: {getattr(mutex_ptr, 'type', type(mutex_ptr))}")
            if mutex_ptr.type != mutex_ty:
                mutex_ptr = self.builder.bitcast(mutex_ptr, mutex_ty)
            pthread_mutex_lock = self.module.globals.get('pthread_mutex_lock')
            if not pthread_mutex_lock:
                pthread_mutex_lock_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()])
                pthread_mutex_lock = ir.Function(self.module, pthread_mutex_lock_ty, name='pthread_mutex_lock')
            debug_print(f"DEBUG: lock() - about to call pthread_mutex_lock with: {mutex_ptr}")
            try:
                result = self.builder.call(pthread_mutex_lock, [mutex_ptr])
                debug_print(f"DEBUG: lock() - pthread_mutex_lock call succeeded")
                return result
            except Exception as e:
                debug_print(f"DEBUG: lock() - pthread_mutex_lock call failed: {e}")
                debug_print(f"DEBUG: lock() - mutex_ptr type: {getattr(mutex_ptr, 'type', type(mutex_ptr))}")
                raise
        elif func_name == 'unlock':
            # Mutex unlock operation - maps to pthread_mutex_unlock
            arg0 = node['arguments'][0]
            debug_print(f"DEBUG: unlock() - arg0: {arg0}")
            # If argument is a string literal, treat it as a variable name
            if isinstance(arg0, dict) and arg0.get('type') == 'literal' and isinstance(arg0.get('value'), str):
                debug_print(f"DEBUG: unlock() - treating arg0 as variable name: {arg0['value']}")
                mutex_ptr = self.visit_ID({'type': 'ID', 'value': arg0['value']}, prefer_globals=True)
            elif isinstance(arg0, dict) and arg0.get('type') == 'ID':
                debug_print(f"DEBUG: unlock() - treating arg0 as ID")
                mutex_ptr = self.visit_ID(arg0, prefer_globals=True)
            elif isinstance(arg0, dict) and arg0.get('type') == 'array_access':
                debug_print(f"DEBUG: unlock() - treating arg0 as array access")
                mutex_ptr = self.visit_array_access(arg0)
            else:
                debug_print(f"DEBUG: unlock() - visiting arg0 normally")
                mutex_ptr = self.visit(arg0)
            debug_print(f"DEBUG: unlock() - mutex_ptr: {mutex_ptr}, type: {getattr(mutex_ptr, 'type', type(mutex_ptr))}")
            mutex_ty = ir.IntType(8).as_pointer()
            if not hasattr(mutex_ptr, 'type') or not isinstance(mutex_ptr.type, ir.PointerType):
                raise Exception(f"Mutex argument is not a pointer. Got type: {getattr(mutex_ptr, 'type', type(mutex_ptr))}")
            if mutex_ptr.type != mutex_ty:
                mutex_ptr = self.builder.bitcast(mutex_ptr, mutex_ty)
            pthread_mutex_unlock = self.module.globals.get('pthread_mutex_unlock')
            if not pthread_mutex_unlock:
                pthread_mutex_unlock_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()])
                pthread_mutex_unlock = ir.Function(self.module, pthread_mutex_unlock_ty, name='pthread_mutex_unlock')
            debug_print(f"DEBUG: unlock() - about to call pthread_mutex_unlock with: {mutex_ptr}")
            try:
                result = self.builder.call(pthread_mutex_unlock, [mutex_ptr])
                debug_print(f"DEBUG: unlock() - pthread_mutex_unlock call succeeded")
                return result
            except Exception as e:
                debug_print(f"DEBUG: unlock() - pthread_mutex_unlock call failed: {e}")
                debug_print(f"DEBUG: unlock() - mutex_ptr type: {getattr(mutex_ptr, 'type', type(mutex_ptr))}")
                raise
        elif func_name == 'join_threads':
            # Join multiple threads using pthread_join in a loop
            threads_arg = node['arguments'][0]
            
            # Get thread_count - if not provided as second argument, try to get from globals
            if len(node['arguments']) > 1:
                thread_count = self.visit(node['arguments'][1])
            else:
                # Try to get thread_count from globals
                if 'thread_count' in self.globals:
                    thread_count_ptr, dtype, _ = self.globals['thread_count']
                    thread_count = self.builder.load(thread_count_ptr)
                else:
                    thread_count = ir.Constant(ir.IntType(32), 1)  # Default to 1
            
            if isinstance(threads_arg, dict) and threads_arg.get('type') == 'literal' and isinstance(threads_arg.get('value'), str):
                # Thread array variable name as string literal
                threads_name = threads_arg['value']
                if threads_name in self.locals:
                    threads_ptr, dtype, _ = self.locals[threads_name]
                elif threads_name in self.globals:
                    threads_ptr, dtype, _ = self.globals[threads_name]
                else:
                    raise Exception(f"Undefined thread array variable: {threads_name}")
            elif isinstance(threads_arg, dict) and threads_arg.get('type') == 'ID':
                # For join_threads, we need the pointer to the array, not the loaded value
                threads_name = threads_arg['value']
                if threads_name in self.locals:
                    threads_ptr, dtype, _ = self.locals[threads_name]
                    # If it's a thread_array, we already have the pointer to the array
                    # Don't load it - just pass the pointer directly
                    debug_print(f"DEBUG: join_threads - found thread_array '{threads_name}' in locals, dtype: {dtype}, threads_ptr: {threads_ptr}")
                elif threads_name in self.globals:
                    threads_ptr, dtype = self.globals[threads_name]
                    debug_print(f"DEBUG: join_threads - found thread_array '{threads_name}' in globals, dtype: {dtype}, threads_ptr: {threads_ptr}")
                else:
                    raise Exception(f"Undefined thread array variable: {threads_name}")
            else:
                threads_ptr = self.visit(threads_arg)
            join_threads(self.builder, self.module, threads_ptr, thread_count)
            return ir.Constant(ir.IntType(32), 0)  # Return success code
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
            
            # Determine element type
            if isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'semaphore':
                element_type = 'semaphore'
                element_llvm_type = ir.ArrayType(ir.IntType(8), 32)  # sem_t storage
            elif isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'mutex':
                element_type = 'mutex'
                element_llvm_type = ir.ArrayType(ir.IntType(8), 40)  # pthread_mutex_t storage
            elif isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'barrier':
                element_type = 'barrier'
                element_llvm_type = ir.ArrayType(ir.IntType(8), 128)  # pthread_barrier_t storage (opaque)
            elif isinstance(element_init, dict) and element_init.get('type') == 'function_call' and element_init.get('name') == 'thread':
                element_type = 'thread'
                element_llvm_type = ir.IntType(8).as_pointer()  # pthread_t as void*
            elif isinstance(element_init, dict) and element_init.get('type') == 'literal' and element_init.get('value') == 'thread':
                element_type = 'thread'
                element_llvm_type = ir.IntType(8).as_pointer()  # pthread_t as void*
            elif isinstance(element_init, dict) and element_init.get('type') == 'literal' and element_init.get('value') == '"thread"':
                element_type = 'thread'  
                element_llvm_type = ir.IntType(8).as_pointer()  # pthread_t as void*
            else:
                # For now, assume int if not semaphore, mutex, or thread
                element_type = 'int'
                element_llvm_type = ir.IntType(32)
            
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
                # Get or create atoi function
                atoi = self.module.globals.get('atoi')
                if not atoi:
                    atoi_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()])
                    atoi = ir.Function(self.module, atoi_ty, name="atoi")
                
                # Call atoi with the string argument
                result = self.builder.call(atoi, [arg])
                debug_print(f"DEBUG: int() conversion - called atoi, result: {result}")
                return result
            
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

            # Duration (expects integer)
            duration_val = self.visit(args[0])
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

            # Declare or get nanosleep
            nanosleep = self.module.globals.get('nanosleep')
            if not nanosleep:
                nanosleep_ty = ir.FunctionType(ir.IntType(32), [self.timespec_ty.as_pointer(), self.timespec_ty.as_pointer()])
                nanosleep = ir.Function(self.module, nanosleep_ty, name='nanosleep')

            null_rem = ir.Constant(self.timespec_ty.as_pointer(), None)
            debug_print(f"DEBUG: sleep() calling nanosleep with tv_sec/tv_nsec")
            return self.builder.call(nanosleep, [ts_ptr, null_rem])
        elif func_name == 'seed':
            # Remove explicit seeding API in favor of automatic OS-entropy seeding on first rand() use
            raise Exception("seed() was removed. rand() now auto-seeds from OS entropy on first use.")
        elif func_name == 'rand':
            # Random integer generator using POSIX random() for wider range than C rand()
            # Auto-seeds from OS entropy (getrandom) on first use; falls back to time(NULL) if needed.
            # Usage:
            #   rand() -> int in [0, RAND_MAX-ish] (truncated from 31/63-bit random)
            #   rand(max) -> int in [0, max)
            #   rand(min, max) -> int in [min, max) (order-agnostic, half-open interval)
            args = node.get('arguments', [])
            if len(args) not in (0, 1, 2):
                raise Exception(f"rand() requires 0, 1 or 2 arguments, got {len(args)}")

            i32 = ir.IntType(32)
            i64 = ir.IntType(64)

            # Ensure we seed the PRNG once using OS entropy
            seeded_g = self.module.globals.get('__alecci_random_seeded')
            if not seeded_g:
                seeded_g = ir.GlobalVariable(self.module, i32, name='__alecci_random_seeded')
                seeded_g.linkage = 'internal'
                seeded_g.initializer = ir.Constant(i32, 0)
            seeded_val = self.builder.load(seeded_g)
            need_seed = self.builder.icmp_signed('==', seeded_val, ir.Constant(i32, 0))

            cur_func = self.builder.function
            seed_bb = cur_func.append_basic_block(name='rand_seed')
            cont_bb = cur_func.append_basic_block(name='rand_cont')
            self.builder.cbranch(need_seed, seed_bb, cont_bb)

            # Seed block
            self.builder.position_at_end(seed_bb)
            # Try getrandom(void* buf, size_t buflen, unsigned int flags) -> ssize_t
            getrandom_fn = self.module.globals.get('getrandom')
            if not getrandom_fn:
                getrandom_ty = ir.FunctionType(i64, [ir.IntType(8).as_pointer(), i64, i32])
                getrandom_fn = ir.Function(self.module, getrandom_ty, name='getrandom')
            # srandom(unsigned int)
            srandom_fn = self.module.globals.get('srandom')
            if not srandom_fn:
                srandom_ty = ir.FunctionType(ir.VoidType(), [i32])
                srandom_fn = ir.Function(self.module, srandom_ty, name='srandom')
            # time_t time(time_t*) -> assume i64 time_t
            time_fn = self.module.globals.get('time')
            if not time_fn:
                time_ty = ir.FunctionType(i64, [i64.as_pointer()])
                time_fn = ir.Function(self.module, time_ty, name='time')

            seed_tmp = self.builder.alloca(i32, name='seed_tmp')
            seed_buf = self.builder.bitcast(seed_tmp, ir.IntType(8).as_pointer())
            gr_n = self.builder.call(getrandom_fn, [seed_buf, ir.Constant(i64, 4), ir.Constant(i32, 0)])

            ok_bb = cur_func.append_basic_block(name='rand_seed_ok')
            fb_bb = cur_func.append_basic_block(name='rand_seed_fb')
            done_seed_bb = cur_func.append_basic_block(name='rand_seed_done')

            got_4 = self.builder.icmp_signed('==', gr_n, ir.Constant(i64, 4))
            self.builder.cbranch(got_4, ok_bb, fb_bb)

            # OK: use hardware entropy
            self.builder.position_at_end(ok_bb)
            seed_val32 = self.builder.load(seed_tmp)
            self.builder.call(srandom_fn, [seed_val32])
            self.builder.branch(done_seed_bb)

            # Fallback: use time(NULL)
            self.builder.position_at_end(fb_bb)
            null_time_ptr = ir.Constant(i64.as_pointer(), None)
            t = self.builder.call(time_fn, [null_time_ptr])
            t32 = self.builder.trunc(t, i32)
            self.builder.call(srandom_fn, [t32])
            self.builder.branch(done_seed_bb)

            # Mark seeded and continue
            self.builder.position_at_end(done_seed_bb)
            self.builder.store(ir.Constant(i32, 1), seeded_g)
            self.builder.branch(cont_bb)

            # Continue after seeding (or if already seeded)
            self.builder.position_at_end(cont_bb)

            # Declare or get POSIX random() -> long
            random_func = self.module.globals.get('random')
            if not random_func:
                random_ty = ir.FunctionType(i64, [])
                random_func = ir.Function(self.module, random_ty, name='random')

            rand64 = self.builder.call(random_func, [])

            # Helpers to coerce arguments to i64 ints
            def ensure_i64(val):
                v = val
                if not hasattr(v, 'type'):
                    raise Exception("rand() argument must be an integer expression")
                if isinstance(v.type, ir.PointerType):
                    v = self.builder.load(v)
                if not isinstance(v.type, ir.IntType):
                    raise Exception("rand() argument must be an integer expression")
                if v.type.width == 64:
                    return v
                if v.type.width < 64:
                    return self.builder.zext(v, i64)
                return self.builder.trunc(v, i64)

            if len(args) == 0:
                # Truncate to 32-bit result for language int
                return self.builder.trunc(rand64, i32)
            if len(args) == 1:
                max_v64 = ensure_i64(self.visit(args[0]))
                zero64 = ir.Constant(i64, 0)
                one64 = ir.Constant(i64, 1)
                # Avoid division by zero at runtime: if max == 0 use 1
                safe_mod = self.builder.select(self.builder.icmp_signed('==', max_v64, zero64), one64, max_v64)
                mod64 = self.builder.srem(rand64, safe_mod)
                return self.builder.trunc(mod64, i32)
            else:  # len(args) == 2
                min_v64 = ensure_i64(self.visit(args[0]))
                max_v64 = ensure_i64(self.visit(args[1]))
                one64 = ir.Constant(i64, 1)
                zero64 = ir.Constant(i64, 0)
                # Normalize order to get lo <= hi
                ge = self.builder.icmp_signed('>=', max_v64, min_v64)
                hi = self.builder.select(ge, max_v64, min_v64)
                lo = self.builder.select(ge, min_v64, max_v64)
                # range = hi - lo (half-open interval [lo, hi))
                rng = self.builder.sub(hi, lo)
                # Protect against zero or negative range
                safe_rng = self.builder.select(self.builder.icmp_signed('<=', rng, zero64), one64, rng)
                mod64 = self.builder.srem(rand64, safe_rng)
                res64 = self.builder.add(mod64, lo)
                return self.builder.trunc(res64, i32)
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
        
        # Use element_type to determine if we should load or return pointer
        if isinstance(element_type, str):
            # For array types, extract the actual element type
            if element_type.startswith('array_'):
                actual_element_type = element_type[6:]  # Remove 'array_' prefix
                if actual_element_type == 'semaphore':
                    # Return pointer to semaphore storage for wait/signal operations
                    debug_print(f"DEBUG: visit_array_access - returning semaphore pointer: {element_ptr}")
                    return element_ptr
                elif actual_element_type == 'mutex':
                    # Return pointer to mutex storage for lock/unlock operations
                    debug_print(f"DEBUG: visit_array_access - returning mutex pointer: {element_ptr}")
                    return element_ptr
                elif actual_element_type == 'thread':
                    # Load and return the thread handle (i8*) from the array element
                    result = self.builder.load(element_ptr)
                    debug_print(f"DEBUG: visit_array_access - thread array access: element_ptr={element_ptr}, result={result}")
                    debug_print(f"DEBUG: visit_array_access - result type: {getattr(result, 'type', 'no-type')}")
                    return result
                elif actual_element_type == 'barrier':
                    # Return pointer to barrier storage for barrier_wait operations
                    debug_print(f"DEBUG: visit_array_access - returning barrier pointer: {element_ptr}")
                    return element_ptr
                elif actual_element_type in ('int', 'float'):
                    result = self.builder.load(element_ptr)
                    debug_print(f"DEBUG: visit_array_access - returning loaded {actual_element_type}: {result}")
                    return result
                else:
                    debug_print(f"DEBUG: visit_array_access - returning element_ptr for type {actual_element_type}: {element_ptr}")
                    return element_ptr
            elif element_type in ('int', 'float'):
                result = self.builder.load(element_ptr)
                debug_print(f"DEBUG: visit_array_access - returning loaded {element_type}: {result}")
                return result
            else:
                debug_print(f"DEBUG: visit_array_access - returning element_ptr for unknown type {element_type}: {element_ptr}")
                return element_ptr
        result = self.builder.load(element_ptr)
        debug_print(f"DEBUG: visit_array_access - returning loaded default: {result}")
        return result

    def visit_return(self, node: Dict[str, Any]) -> None:
        # Mark that we've seen an explicit return in this body
        self.has_explicit_return = True
        if 'value' in node and node['value'] is not None:
            val = self.visit(node['value'])
            self.builder.ret(val)
        else:
            self.builder.ret_void()

    def visit_record_init(self, node: Dict[str, Any]) -> None:
        # Not implemented: just a stub for record initialization
        raise NotImplementedError("Record initialization not implemented yet.")

    def visit_pointer_type(self, node: Dict[str, Any]) -> None:
        # Not implemented: just a stub for pointer types
        raise NotImplementedError("Pointer types not implemented yet.")

    def visit_dereference(self, node: Dict[str, Any]) -> None:
        # Not implemented: just a stub for dereferencing
        raise NotImplementedError("Dereference not implemented yet.")

    def visit_reference(self, node: Dict[str, Any]) -> None:
        # Not implemented: just a stub for references
        raise NotImplementedError("Reference not implemented yet.")

    def _store_variant_value(self, variant_ptr, value, type_tag, type_hint=None):
        """Store a value in a variant structure using runtime functions"""
        debug_print(f"DEBUG: _store_variant_value - storing value: {value}, type_tag: {type_tag}, type_hint: {type_hint}")
        from .base_types import get_variant_type
        variant_ty = get_variant_type()
        
        # Check if this is a variant struct being assigned to another variant first
        if hasattr(value, 'type') and str(value.type) == str(variant_ty):
            debug_print(f"DEBUG: _store_variant_value - direct store of variant struct")
            # Simply store the variant value directly
            self.builder.store(value, variant_ptr)
            debug_print(f"DEBUG: _store_variant_value - stored variant directly")
            return
        
        # Use runtime functions to create variants properly
        if hasattr(value, 'type'):
            if isinstance(value.type, ir.IntType) and value.type.width == 32:
                # Create variant using runtime function
                debug_print(f"DEBUG: _store_variant_value - creating int variant using runtime")
                func_name = 'variant_create_int'
                func = self.module.globals.get(func_name)
                if not func:
                    func_ty = ir.FunctionType(variant_ty, [ir.IntType(32)])
                    func = ir.Function(self.module, func_ty, name=func_name)
                created_variant = self.builder.call(func, [value])
                self.builder.store(created_variant, variant_ptr)
                
            elif isinstance(value.type, ir.DoubleType):
                # Create variant using runtime function
                debug_print(f"DEBUG: _store_variant_value - creating float variant using runtime")
                func_name = 'variant_create_float'
                func = self.module.globals.get(func_name)
                if not func:
                    func_ty = ir.FunctionType(variant_ty, [ir.DoubleType()])
                    func = ir.Function(self.module, func_ty, name=func_name)
                created_variant = self.builder.call(func, [value])
                self.builder.store(created_variant, variant_ptr)
                
            elif isinstance(value.type, ir.PointerType) and value.type.pointee == ir.IntType(8):
                # Create string variant using runtime function
                debug_print(f"DEBUG: _store_variant_value - creating string variant using runtime")
                func_name = 'variant_create_string'
                func = self.module.globals.get(func_name)
                if not func:
                    func_ty = ir.FunctionType(variant_ty, [ir.IntType(8).as_pointer()])
                    func = ir.Function(self.module, func_ty, name=func_name)
                created_variant = self.builder.call(func, [value])
                self.builder.store(created_variant, variant_ptr)
                
            else:
                # Fall back to null variant for unknown types
                debug_print(f"DEBUG: _store_variant_value - creating null variant for unknown type")
                func_name = 'variant_create_null'
                func = self.module.globals.get(func_name)
                if not func:
                    func_ty = ir.FunctionType(variant_ty, [])
                    func = ir.Function(self.module, func_ty, name=func_name)
                created_variant = self.builder.call(func, [])
                self.builder.store(created_variant, variant_ptr)

    def _extract_variant_value(self, variant_ptr, expected_type='int'):
        """Extract a raw value from a variant for operations"""
        # Load the variant struct first
        from .base_types import get_variant_type
        variant_ty = get_variant_type()
        variant_value = self.builder.load(variant_ptr)
        
        # Use variant runtime functions to get the value
        if expected_type == 'int':
            func_name = 'variant_get_int'
        elif expected_type == 'float':
            func_name = 'variant_get_float'
        elif expected_type == 'string':
            func_name = 'variant_get_string'
        else:
            func_name = 'variant_get_int'  # Default
        
        # Get or declare the runtime function
        func = self.module.globals.get(func_name)
        if not func:
            from .base_types import get_raw_type
            return_ty = get_raw_type(expected_type)
            func_ty = ir.FunctionType(return_ty, [variant_ty])
            func = ir.Function(self.module, func_ty, name=func_name)
        
        return self.builder.call(func, [variant_value])

    def _auto_extract_value(self, value, prefer_type='int'):
        """Automatically extract value from variant if needed"""
        debug_print(f"DEBUG: _auto_extract_value - input value: {value}, type: {getattr(value, 'type', 'no-type')}, prefer_type: {prefer_type}")
        
        # If prefer_type is 'auto', just return the raw value for type inspection
        if prefer_type == 'auto':
            if isinstance(value.type, ir.PointerType):
                loaded = self.builder.load(value)
                debug_print(f"DEBUG: _auto_extract_value - auto mode, loaded: {loaded}, type: {getattr(loaded, 'type', 'no-type')}")
                return loaded
            return value
        
        if not hasattr(value, 'type'):
            debug_print(f"DEBUG: _auto_extract_value - no type, returning as-is")
            return value
            
        # If it's a pointer to a variant struct, extract the value
        from .base_types import get_variant_type
        variant_ty = get_variant_type()
        
        debug_print(f"DEBUG: _auto_extract_value - variant_ty: {variant_ty}")
        debug_print(f"DEBUG: _auto_extract_value - value.type: {value.type}")
        debug_print(f"DEBUG: _auto_extract_value - is PointerType: {isinstance(value.type, ir.PointerType)}")
        debug_print(f"DEBUG: _auto_extract_value - is variant struct: {value.type == variant_ty}")
        
        if value.type == variant_ty:
            # This is a variant struct value - need to store it to extract
            debug_print(f"DEBUG: _auto_extract_value - handling variant struct value")
            temp_var = self.builder.alloca(variant_ty, name="temp_variant")
            self.builder.store(value, temp_var)
            return self._extract_variant_value(temp_var, prefer_type)
        elif (isinstance(value.type, ir.PointerType) and 
              value.type.pointee == variant_ty):
            # This is a variant pointer - extract the value
            debug_print(f"DEBUG: _auto_extract_value - extracting from variant pointer")
            return self._extract_variant_value(value, prefer_type)
        elif isinstance(value.type, ir.PointerType):
            # Regular pointer - load the value
            debug_print(f"DEBUG: _auto_extract_value - loading from regular pointer")
            loaded = self.builder.load(value)
            debug_print(f"DEBUG: _auto_extract_value - loaded: {loaded}, type: {getattr(loaded, 'type', 'no-type')}")
            # Check if the loaded value is a variant struct
            if hasattr(loaded, 'type') and loaded.type == variant_ty:
                debug_print(f"DEBUG: _auto_extract_value - loaded value is variant struct, need to extract")
                # We need to create a temporary alloca and store the loaded variant, then extract
                temp_var = self.builder.alloca(variant_ty, name="temp_variant")
                self.builder.store(loaded, temp_var)
                return self._extract_variant_value(temp_var, prefer_type)
            return loaded
        else:
            # Already a value
            debug_print(f"DEBUG: _auto_extract_value - already a value, returning as-is")
            return value

    def _store_null_variant(self, variant_ptr):
        """Store a null variant"""
        from .base_types import get_variant_type_tag_enum
        type_tags = get_variant_type_tag_enum()
        null_tag = type_tags['null']
        
        # Store null type tag
        tag_ptr = self.builder.gep(variant_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
        self.builder.store(ir.Constant(ir.IntType(32), null_tag), tag_ptr)
        
        # Zero out data
        data_ptr = self.builder.gep(variant_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
        data_array_ptr = self.builder.bitcast(data_ptr, ir.IntType(8).as_pointer())
        # Memset to zero
        for i in range(16):
            elem_ptr = self.builder.gep(data_array_ptr, [ir.Constant(ir.IntType(32), i)])
            self.builder.store(ir.Constant(ir.IntType(8), 0), elem_ptr)

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
