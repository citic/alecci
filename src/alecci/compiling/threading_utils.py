from llvmlite import ir

from parsing.globals import debug_print

def _get_pthread_create(module):
    # pthread_t is typically a pointer type (void* or equivalent)
    thread_type = ir.IntType(8).as_pointer()  # pthread_t as void*
    voidptr_ty = ir.IntType(8).as_pointer()
    # Function pointer type: void* (*)(void*)
    func_ptr_ty = ir.FunctionType(voidptr_ty, [voidptr_ty]).as_pointer()
    pthread_create = module.globals.get('pthread_create')
    if not pthread_create:
        # pthread_create signature: int pthread_create(pthread_t *thread, const pthread_attr_t *attr, void *(*start_routine)(void *), void *arg)
        pthread_create_ty = ir.FunctionType(
            ir.IntType(32),
            [thread_type.as_pointer(), voidptr_ty, func_ptr_ty, voidptr_ty]
        )
        pthread_create = ir.Function(module, pthread_create_ty, name='pthread_create')
    return pthread_create, thread_type, voidptr_ty


def create_thread(builder, module, target_func, thread_args=None):
    """
    Create a single thread using pthread_create.
    Args:
        builder: The IRBuilder instance.
        module: The LLVM module.
        target_func: The function to run in the thread (LLVM function pointer).
        thread_args: Optional list of arguments to pass to the thread.
    Returns:
        thread_ptr: Pointer to the thread handle.
    """
    debug_print("[DEBUG] Entering create_thread")
    pthread_create, thread_type, voidptr_ty = _get_pthread_create(module)
    debug_print(f"[DEBUG] pthread_create: {pthread_create}, thread_type: {thread_type}, voidptr_ty: {voidptr_ty}")
    thread_ptr = builder.alloca(thread_type, name="thread")
    debug_print(f"[DEBUG] Allocated thread_ptr: {thread_ptr}")
    
    # Create a structure to hold all thread arguments
    # For create_thread, we pass the arguments as-is (no automatic thread_number)
    arg_types = []
    if thread_args:
        for arg in thread_args:
            if hasattr(arg, 'type'):
                arg_types.append(arg.type)
            else:
                arg_types.append(ir.IntType(32))  # Default to i32
    
    # Create struct type for thread arguments
    thread_arg_struct_type = ir.LiteralStructType(arg_types)
    
    # Create a wrapper function with pthread signature that calls the user function
    wrapper_name = f"_thread_wrapper_{target_func.name}_with_args"
    wrapper_func = module.globals.get(wrapper_name)
    if not wrapper_func:
        # Create wrapper: void* wrapper(void* arg_struct_ptr) { 
        #   struct* args = (struct*)arg_struct_ptr;
        #   user_func(args->arg1, args->arg2, ...); 
        #   return NULL; 
        # }
        # Note: For create_thread, we pass arguments as-is (no automatic thread_number)
        wrapper_ty = ir.FunctionType(voidptr_ty, [voidptr_ty])
        wrapper_func = ir.Function(module, wrapper_ty, name=wrapper_name)
        
        # Build the wrapper function body
        wrapper_block = wrapper_func.append_basic_block('entry')
        wrapper_builder = ir.IRBuilder(wrapper_block)
        
        # Cast void* argument back to struct pointer
        arg_struct_ptr_param = wrapper_func.args[0]
        arg_struct_ptr = wrapper_builder.bitcast(arg_struct_ptr_param, thread_arg_struct_type.as_pointer())
        
        # Extract arguments from struct and pass ALL arguments to the target function
        call_args = []
        debug_print(f"[DEBUG] create_thread wrapper: arg_types length: {len(arg_types)}")
        debug_print(f"[DEBUG] create_thread wrapper: target_func args length: {len(target_func.args)}")
        for i in range(len(arg_types)):
            field_ptr = wrapper_builder.gep(arg_struct_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)])
            field_value = wrapper_builder.load(field_ptr)
            call_args.append(field_value)
            debug_print(f"[DEBUG] create_thread wrapper: added arg {i}: {field_value}")
        
        # Fix: Reverse the argument order to match expected parameter order
        # This addresses an issue where arguments were being passed in reverse order
        call_args.reverse()
        debug_print(f"[DEBUG] create_thread wrapper: final call_args length: {len(call_args)}")
        
        # Call the original function with the provided arguments
        result = wrapper_builder.call(target_func, call_args)
        
        # If the function returns a value (not void), we need to box it as void*
        # For now, we'll store it in a heap-allocated variant structure
        if target_func.return_value.type != ir.VoidType():
            # Import variant type
            from .base_types import get_variant_type
            variant_ty = get_variant_type()
            
            # Allocate variant on heap using malloc
            malloc_func = module.globals.get('malloc')
            if not malloc_func:
                malloc_ty = ir.FunctionType(voidptr_ty, [ir.IntType(64)])
                malloc_func = ir.Function(module, malloc_ty, name='malloc')
            
            # Use a fixed size for the variant structure (20 bytes is sufficient for the variant type)
            variant_size = ir.Constant(ir.IntType(64), 20)
            variant_ptr_void = wrapper_builder.call(malloc_func, [variant_size])
            variant_ptr = wrapper_builder.bitcast(variant_ptr_void, variant_ty.as_pointer())
            
            # Store the return value into the variant
            # Determine type tag based on return type
            type_tag_ptr = wrapper_builder.gep(variant_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
            data_ptr = wrapper_builder.gep(variant_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
            
            if isinstance(result.type, ir.IntType) and result.type.width == 32:
                # Integer type
                wrapper_builder.store(ir.Constant(ir.IntType(32), 0), type_tag_ptr)  # Type tag 0 = int
                data_as_int_ptr = wrapper_builder.bitcast(data_ptr, ir.IntType(32).as_pointer())
                wrapper_builder.store(result, data_as_int_ptr)
            elif isinstance(result.type, ir.DoubleType):
                # Float type
                wrapper_builder.store(ir.Constant(ir.IntType(32), 1), type_tag_ptr)  # Type tag 1 = float
                data_as_float_ptr = wrapper_builder.bitcast(data_ptr, ir.DoubleType().as_pointer())
                wrapper_builder.store(result, data_as_float_ptr)
            elif isinstance(result.type, ir.PointerType):
                # String/pointer type
                wrapper_builder.store(ir.Constant(ir.IntType(32), 2), type_tag_ptr)  # Type tag 2 = string
                data_as_ptr_ptr = wrapper_builder.bitcast(data_ptr, ir.IntType(8).as_pointer().as_pointer())
                casted_result = wrapper_builder.bitcast(result, ir.IntType(8).as_pointer())
                wrapper_builder.store(casted_result, data_as_ptr_ptr)
            else:
                # Variant or unknown - just store the variant as-is if it's already a variant
                if result.type == variant_ty:
                    wrapper_builder.store(result, variant_ptr)
                else:
                    # Unknown type - store NULL
                    wrapper_builder.store(ir.Constant(ir.IntType(32), 8), type_tag_ptr)  # Type tag 8 = null
            
            # Return the variant pointer as void*
            wrapper_builder.ret(variant_ptr_void)
        else:
            # Return NULL for void functions
            null_ret = ir.Constant(voidptr_ty, None)
            wrapper_builder.ret(null_ret)
    
    start_routine = wrapper_func
    debug_print(f"[DEBUG] start_routine wrapper: {start_routine}")
    
    # Create argument structure for this thread
    arg_struct = builder.alloca(thread_arg_struct_type, name="thread_args")
    
    # Set all arguments in the structure
    if thread_args:
        for i, arg in enumerate(thread_args):
            arg_field_ptr = builder.gep(arg_struct, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)])
            builder.store(arg, arg_field_ptr)
    
    # Convert argument structure pointer to void*
    arg_struct_as_voidptr = builder.bitcast(arg_struct, voidptr_ty)
    debug_print(f"[DEBUG] arg_struct_as_voidptr: {arg_struct_as_voidptr}")

    debug_print(f"[DEBUG] Calling pthread_create with: thread_ptr={thread_ptr}, attr=None, start_routine={start_routine}, arg_struct_as_voidptr={arg_struct_as_voidptr}")
    builder.call(pthread_create, [thread_ptr, ir.Constant(voidptr_ty, None), start_routine, arg_struct_as_voidptr])
    debug_print("[DEBUG] pthread_create call emitted")
    
    # Load the thread handle from the allocated space and return it
    thread_handle = builder.load(thread_ptr)
    debug_print(f"[DEBUG] Loaded thread handle: {thread_handle}, type: {thread_handle.type}")
    return thread_handle


def create_threads(builder, module, thread_count, target_func, thread_args=None):
    """
    Modularized thread creation logic for create_threads pseudo-function.
    Allocates an array for thread handles and emits a loop to call pthread_create.
    Args:
        builder: The IRBuilder instance.
        module: The LLVM module.
        thread_count: The number of threads to create (LLVM value).
        target_func: The function to run in each thread (must be an LLVM function pointer).
        thread_args: Optional list of additional arguments to pass to each thread.
    Returns:
        threads_ptr: Pointer to the array of thread handles.
    """
    pthread_create, thread_type, voidptr_ty = _get_pthread_create(module)
    threads_array_type = ir.ArrayType(thread_type, 1024)  # Max 1024 threads for now
    threads_ptr = builder.alloca(threads_array_type, name="threads")
    
    # Create a structure to hold thread arguments including thread_number
    # The structure will contain: thread_number (i32) + additional args
    arg_types = [ir.IntType(32)]  # thread_number is always first
    if thread_args:
        for arg in thread_args:
            if hasattr(arg, 'type'):
                arg_types.append(arg.type)
            else:
                arg_types.append(ir.IntType(32))  # Default to i32
    
    # Create struct type for thread arguments
    thread_arg_struct_type = ir.LiteralStructType(arg_types)
    
    # Create a wrapper function with pthread signature that calls the user function
    wrapper_name = f"_thread_wrapper_{target_func.name}_with_args"
    wrapper_func = module.globals.get(wrapper_name)
    if not wrapper_func:
        # Create wrapper: void* wrapper(void* arg_struct_ptr) { 
        #   struct* args = (struct*)arg_struct_ptr;
        #   user_func(args->thread_number, args->arg1, args->arg2, ...); 
        #   return NULL; 
        # }
        wrapper_ty = ir.FunctionType(voidptr_ty, [voidptr_ty])
        wrapper_func = ir.Function(module, wrapper_ty, name=wrapper_name)
        
        # Build the wrapper function body
        wrapper_block = wrapper_func.append_basic_block('entry')
        wrapper_builder = ir.IRBuilder(wrapper_block)
        
        # Cast void* argument back to struct pointer
        arg_struct_ptr_param = wrapper_func.args[0]
        arg_struct_ptr = wrapper_builder.bitcast(arg_struct_ptr_param, thread_arg_struct_type.as_pointer())
        
        # Extract arguments from struct
        call_args = []
        for i, arg_type in enumerate(arg_types):
            field_ptr = wrapper_builder.gep(arg_struct_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)])
            field_value = wrapper_builder.load(field_ptr)
            call_args.append(field_value)
        
        # Fix: Reverse the argument order to match expected parameter order
        # This addresses an issue where arguments were being passed in reverse order
        call_args.reverse()
        
        # Call the original function with the extracted arguments
        result = wrapper_builder.call(target_func, call_args)
        
        # If the function returns a value (not void), we need to box it as void*
        if target_func.return_value.type != ir.VoidType():
            # Import variant type
            from .base_types import get_variant_type
            variant_ty = get_variant_type()
            
            # Allocate variant on heap using malloc
            malloc_func = module.globals.get('malloc')
            if not malloc_func:
                malloc_ty = ir.FunctionType(voidptr_ty, [ir.IntType(64)])
                malloc_func = ir.Function(module, malloc_ty, name='malloc')
            
            # Use a fixed size for the variant structure (20 bytes is sufficient for the variant type)
            variant_size = ir.Constant(ir.IntType(64), 20)
            variant_ptr_void = wrapper_builder.call(malloc_func, [variant_size])
            variant_ptr = wrapper_builder.bitcast(variant_ptr_void, variant_ty.as_pointer())
            
            # Store the return value into the variant
            # Determine type tag based on return type
            type_tag_ptr = wrapper_builder.gep(variant_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
            data_ptr = wrapper_builder.gep(variant_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
            
            if isinstance(result.type, ir.IntType) and result.type.width == 32:
                # Integer type
                wrapper_builder.store(ir.Constant(ir.IntType(32), 0), type_tag_ptr)  # Type tag 0 = int
                data_as_int_ptr = wrapper_builder.bitcast(data_ptr, ir.IntType(32).as_pointer())
                wrapper_builder.store(result, data_as_int_ptr)
            elif isinstance(result.type, ir.DoubleType):
                # Float type
                wrapper_builder.store(ir.Constant(ir.IntType(32), 1), type_tag_ptr)  # Type tag 1 = float
                data_as_float_ptr = wrapper_builder.bitcast(data_ptr, ir.DoubleType().as_pointer())
                wrapper_builder.store(result, data_as_float_ptr)
            elif isinstance(result.type, ir.PointerType):
                # String/pointer type
                wrapper_builder.store(ir.Constant(ir.IntType(32), 2), type_tag_ptr)  # Type tag 2 = string
                data_as_ptr_ptr = wrapper_builder.bitcast(data_ptr, ir.IntType(8).as_pointer().as_pointer())
                casted_result = wrapper_builder.bitcast(result, ir.IntType(8).as_pointer())
                wrapper_builder.store(casted_result, data_as_ptr_ptr)
            else:
                # Variant or unknown - just store the variant as-is if it's already a variant
                if result.type == variant_ty:
                    wrapper_builder.store(result, variant_ptr)
                else:
                    # Unknown type - store NULL
                    wrapper_builder.store(ir.Constant(ir.IntType(32), 8), type_tag_ptr)  # Type tag 8 = null
            
            # Return the variant pointer as void*
            wrapper_builder.ret(variant_ptr_void)
        else:
            # Return NULL for void functions
            null_ret = ir.Constant(voidptr_ty, None)
            wrapper_builder.ret(null_ret)
    
    start_routine = wrapper_func
    
    # Allocate an array of argument structures for all threads (max 1024)
    arg_structs_array_type = ir.ArrayType(thread_arg_struct_type, 1024)
    arg_structs_array = builder.alloca(arg_structs_array_type, name="all_thread_args")
    
    # Manual loop implementation to create threads
    current_func = builder.function
    loop_cond_bb = current_func.append_basic_block('thread_spawn_loop_cond')
    loop_body_bb = current_func.append_basic_block('thread_spawn_loop_body')
    loop_end_bb = current_func.append_basic_block('thread_spawn_loop_end')
    
    # Initialize loop counter
    idx_ptr = builder.alloca(ir.IntType(32), name='spawn_loop_idx')
    builder.store(ir.Constant(ir.IntType(32), 0), idx_ptr)
    
    # Jump to condition check
    builder.branch(loop_cond_bb)
    
    # Condition check
    builder.position_at_start(loop_cond_bb)
    idx = builder.load(idx_ptr)
    cond = builder.icmp_signed('<', idx, thread_count)
    builder.cbranch(cond, loop_body_bb, loop_end_bb)
    
    # Loop body
    builder.position_at_start(loop_body_bb)
    idx = builder.load(idx_ptr)
    thread_ptr = builder.gep(threads_ptr, [ir.Constant(ir.IntType(32), 0), idx])
    
    # Get the argument structure for this specific thread from the array
    arg_struct_ptr = builder.gep(arg_structs_array, [ir.Constant(ir.IntType(32), 0), idx])
    
    # Set thread_number (always the first field)
    thread_number_ptr = builder.gep(arg_struct_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
    builder.store(idx, thread_number_ptr)
    
    # Set additional arguments if provided
    if thread_args:
        for i, arg in enumerate(thread_args):
            arg_field_ptr = builder.gep(arg_struct_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i + 1)])
            builder.store(arg, arg_field_ptr)
    
    # Convert argument structure pointer to void*
    arg_struct_as_voidptr = builder.bitcast(arg_struct_ptr, voidptr_ty)
    
    # Pass start_routine as the function pointer, argument structure as argument
    builder.call(pthread_create, [thread_ptr, ir.Constant(voidptr_ty, None), start_routine, arg_struct_as_voidptr])
    
    # Increment counter
    next_idx = builder.add(idx, ir.Constant(ir.IntType(32), 1))
    builder.store(next_idx, idx_ptr)
    builder.branch(loop_cond_bb)
    
    # After loop
    builder.position_at_start(loop_end_bb)
    
    return threads_ptr


def _get_pthread_join(module):
    """Get or create pthread_join function declaration"""
    thread_type = ir.IntType(8).as_pointer()  # pthread_t as void*
    voidptr_ty = ir.IntType(8).as_pointer()
    pthread_join = module.globals.get('pthread_join')
    if not pthread_join:
        # pthread_join signature: int pthread_join(pthread_t thread, void **retval)
        pthread_join_ty = ir.FunctionType(
            ir.IntType(32),
            [thread_type, voidptr_ty.as_pointer()]
        )
        pthread_join = ir.Function(module, pthread_join_ty, name='pthread_join')
    return pthread_join, thread_type


def join_thread(builder, module, thread_handle):
    """
    Join a single thread using pthread_join and return its return value.
    Args:
        builder: The IRBuilder instance.
        module: The LLVM module.
        thread_handle: The thread handle to join (LLVM value).
    Returns:
        The return value from the thread (as a variant)
    """
    debug_print("[DEBUG] Entering join_thread")
    debug_print(f"[DEBUG] join_thread received thread_handle: {thread_handle}, type: {getattr(thread_handle, 'type', type(thread_handle))}")
    
    # Check if thread_handle is None
    if thread_handle is None:
        raise Exception("join_thread called with None thread handle - this indicates an array access or assignment issue")
    
    pthread_join, thread_type = _get_pthread_join(module)
    voidptr_ty = ir.IntType(8).as_pointer()
    
    # Allocate space to receive the return value pointer
    retval_ptr_storage = builder.alloca(voidptr_ty, name="thread_retval_ptr")
    
    # Debug: Print types before calling pthread_join
    debug_print(f"[DEBUG] join_thread - thread_handle type: {thread_handle.type}")
    debug_print(f"[DEBUG] join_thread - retval_ptr_storage type: {retval_ptr_storage.type}")
    debug_print(f"[DEBUG] join_thread - pthread_join expected types: {pthread_join.function_type.args}")
    
    # Call pthread_join with the thread handle and retval pointer
    builder.call(pthread_join, [thread_handle, retval_ptr_storage])
    
    # Load the return value pointer
    retval_void_ptr = builder.load(retval_ptr_storage)
    
    # Import variant type
    from .base_types import get_variant_type
    variant_ty = get_variant_type()
    
    # Cast void* to variant*
    variant_ptr = builder.bitcast(retval_void_ptr, variant_ty.as_pointer())
    
    # Load the variant value
    variant_value = builder.load(variant_ptr)
    
    # Free the heap-allocated variant
    free_func = module.globals.get('free')
    if not free_func:
        free_ty = ir.FunctionType(ir.VoidType(), [voidptr_ty])
        free_func = ir.Function(module, free_ty, name='free')
    builder.call(free_func, [retval_void_ptr])
    
    debug_print("[DEBUG] join_thread completed, returning variant value")
    return variant_value


def join_threads(builder, module, threads_ptr, thread_count):
    """
    Join multiple threads using pthread_join in a loop.
    Args:
        builder: The IRBuilder instance.
        module: The LLVM module.
        threads_ptr: Pointer to the array of thread handles.
        thread_count: The number of threads to join (LLVM value).
    Returns:
        None
    """
    debug_print("[DEBUG] Entering join_threads")
    debug_print(f"[DEBUG] join_threads received threads_ptr: {threads_ptr}, type: {getattr(threads_ptr, 'type', type(threads_ptr))}")
    pthread_join, thread_type = _get_pthread_join(module)
    voidptr_ty = ir.IntType(8).as_pointer()
    null_retval = ir.Constant(voidptr_ty.as_pointer(), None)
    
    # If threads_ptr is a pointer to a pointer to an array, load it first
    if hasattr(threads_ptr, 'type') and isinstance(threads_ptr.type, ir.PointerType) and isinstance(threads_ptr.type.pointee, ir.PointerType):
        threads_array_ptr = builder.load(threads_ptr)
        debug_print(f"[DEBUG] Loaded threads_array_ptr: {threads_array_ptr}, type: {getattr(threads_array_ptr, 'type', type(threads_array_ptr))}")
    else:
        threads_array_ptr = threads_ptr
    
    # Use the provided thread_count parameter
    debug_print(f"[DEBUG] Using provided thread_count: {thread_count}")
    
    # Manual loop implementation to join threads
    current_func = builder.function
    loop_cond_bb = current_func.append_basic_block('thread_join_loop_cond')
    loop_body_bb = current_func.append_basic_block('thread_join_loop_body')
    loop_end_bb = current_func.append_basic_block('thread_join_loop_end')
    
    # Initialize loop counter
    idx_ptr = builder.alloca(ir.IntType(32), name='join_loop_idx')
    builder.store(ir.Constant(ir.IntType(32), 0), idx_ptr)
    
    # Jump to condition check
    builder.branch(loop_cond_bb)
    
    # Condition check
    builder.position_at_start(loop_cond_bb)
    idx = builder.load(idx_ptr)
    cond = builder.icmp_signed('<', idx, thread_count)
    builder.cbranch(cond, loop_body_bb, loop_end_bb)
    
    # Loop body
    builder.position_at_start(loop_body_bb)
    idx = builder.load(idx_ptr)
    debug_print(f"DEBUG: join_threads threads_array_ptr type: {getattr(threads_array_ptr, 'type', type(threads_array_ptr))}")
    debug_print(f"DEBUG: join_threads idx type: {getattr(idx, 'type', type(idx))}")
    thread_ptr = builder.gep(threads_array_ptr, [ir.Constant(ir.IntType(32), 0), idx])
    thread_handle = builder.load(thread_ptr)
    debug_print(f"DEBUG: join_threads thread_handle type: {getattr(thread_handle, 'type', type(thread_handle))}")
    builder.call(pthread_join, [thread_handle, null_retval])
    
    # Increment counter
    next_idx = builder.add(idx, ir.Constant(ir.IntType(32), 1))
    builder.store(next_idx, idx_ptr)
    builder.branch(loop_cond_bb)
    
    # After loop
    builder.position_at_start(loop_end_bb)
    
    debug_print("[DEBUG] join_threads completed")