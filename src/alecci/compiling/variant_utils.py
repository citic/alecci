"""
variant_utils.py — Standalone helpers for the Alecci variant type system.

These functions accept explicit `builder` and `module` arguments so they can
be used from inside CodeGenerator without coupling to `self`. CodeGenerator
provides thin wrapper methods (_store_variant_value, _extract_variant_value,
etc.) that simply forward to these helpers.
"""

from llvmlite import ir
from .base_types import get_variant_type, get_variant_type_tag_enum, get_raw_type


# ---------------------------------------------------------------------------
# External function declaration helper
# ---------------------------------------------------------------------------

def declare_external_fn(module: ir.Module, name: str, return_ty, arg_tys,
                         var_arg: bool = False) -> ir.Function:
    """Get or declare an external C function in *module*.

    The function is declared only once even if called multiple times with the
    same *name*. This replaces the 20+ repeated ``module.globals.get() / if not
    fn: ir.Function(...)`` boilerplate scattered throughout compiler.py.
    """
    fn = module.globals.get(name)
    if not fn:
        fn_ty = ir.FunctionType(return_ty, arg_tys, var_arg=var_arg)
        fn = ir.Function(module, fn_ty, name=name)
    return fn


# ---------------------------------------------------------------------------
# Variant store
# ---------------------------------------------------------------------------

def store_variant(builder: ir.IRBuilder, module: ir.Module, variant_ptr,
                  value) -> None:
    """Store *value* into the variant struct at *variant_ptr*.

    Dispatches to the appropriate ``variant_create_*`` runtime function based
    on the LLVM type of *value*. If *value* is already a variant struct, it is
    stored directly without conversion.
    """
    variant_ty = get_variant_type()

    # Direct variant-to-variant copy (by value)
    if hasattr(value, 'type') and str(value.type) == str(variant_ty):
        builder.store(value, variant_ptr)
        return

    # Pointer-to-variant: load the variant then store
    if (hasattr(value, 'type') and isinstance(value.type, ir.PointerType) and
            str(value.type.pointee) == str(variant_ty)):
        builder.store(builder.load(value), variant_ptr)
        return

    if not hasattr(value, 'type'):
        # Nothing useful to store
        return

    if isinstance(value.type, ir.IntType) and value.type.width == 32:
        fn = declare_external_fn(module, 'variant_create_int',
                                  variant_ty, [ir.IntType(32)])
        created = builder.call(fn, [value])

    elif isinstance(value.type, ir.DoubleType):
        fn = declare_external_fn(module, 'variant_create_float',
                                  variant_ty, [ir.DoubleType()])
        created = builder.call(fn, [value])

    elif (isinstance(value.type, ir.PointerType) and
          value.type.pointee == ir.IntType(8)):
        fn = declare_external_fn(module, 'variant_create_string',
                                  variant_ty, [ir.IntType(8).as_pointer()])
        created = builder.call(fn, [value])

    else:
        fn = declare_external_fn(module, 'variant_create_null',
                                  variant_ty, [])
        created = builder.call(fn, [])

    builder.store(created, variant_ptr)


# ---------------------------------------------------------------------------
# Variant extract
# ---------------------------------------------------------------------------

def extract_variant(builder: ir.IRBuilder, module: ir.Module, variant_ptr,
                    expected_type: str = 'int') -> ir.Value:
    """Extract a raw typed value from the variant pointer *variant_ptr*.

    For numeric types the runtime ``variant_to_int`` / ``variant_to_float``
    conversion functions are used so that cross-type coercion works correctly
    (e.g. a float stored in a variant can be read as int and vice versa).
    """
    variant_ty = get_variant_type()

    if expected_type == 'float':
        to_fn = declare_external_fn(module, 'variant_to_float',
                                     variant_ty, [variant_ty.as_pointer()])
        converted = builder.call(to_fn, [variant_ptr])
        tmp = builder.alloca(variant_ty, name="conv_variant")
        builder.store(converted, tmp)
        get_fn = declare_external_fn(module, 'variant_get_float',
                                      ir.DoubleType(), [variant_ty.as_pointer()])
        return builder.call(get_fn, [tmp])

    elif expected_type == 'int':
        to_fn = declare_external_fn(module, 'variant_to_int',
                                     variant_ty, [variant_ty.as_pointer()])
        converted = builder.call(to_fn, [variant_ptr])
        tmp = builder.alloca(variant_ty, name="conv_variant")
        builder.store(converted, tmp)
        get_fn = declare_external_fn(module, 'variant_get_int',
                                      ir.IntType(32), [variant_ty.as_pointer()])
        return builder.call(get_fn, [tmp])

    else:
        # string / thread / other pointer types
        func_name = 'variant_get_string'
        return_ty = get_raw_type(expected_type)
        get_fn = declare_external_fn(module, func_name, return_ty,
                                      [variant_ty.as_pointer()])
        return builder.call(get_fn, [variant_ptr])


# ---------------------------------------------------------------------------
# Auto-extract (strips variant/pointer wrapping as needed)
# ---------------------------------------------------------------------------

def auto_extract(builder: ir.IRBuilder, module: ir.Module, value,
                 prefer_type: str = 'int') -> ir.Value:
    """Strip variant or pointer wrapping from *value*, returning a plain value.

    * ``prefer_type='auto'`` — load the raw pointer/value without variant
      extraction (used when the caller just needs the underlying LLVM value for
      type inspection).
    * ``prefer_type='int'`` or ``'float'`` — coerce through the variant
      conversion path.
    """
    variant_ty = get_variant_type()

    if prefer_type == 'auto':
        if hasattr(value, 'type') and isinstance(value.type, ir.PointerType):
            return builder.load(value)
        return value

    if not hasattr(value, 'type'):
        return value

    if value.type == variant_ty:
        # Variant struct by value — store temporarily then extract
        tmp = builder.alloca(variant_ty, name="tmp_variant")
        builder.store(value, tmp)
        return extract_variant(builder, module, tmp, prefer_type)

    elif (isinstance(value.type, ir.PointerType) and
          value.type.pointee == variant_ty):
        # Variant pointer — extract directly
        return extract_variant(builder, module, value, prefer_type)

    elif isinstance(value.type, ir.PointerType):
        # Regular pointer — load it
        loaded = builder.load(value)
        if hasattr(loaded, 'type') and loaded.type == variant_ty:
            tmp = builder.alloca(variant_ty, name="tmp_variant")
            builder.store(loaded, tmp)
            return extract_variant(builder, module, tmp, prefer_type)
        return loaded

    else:
        # Already a plain value
        return value


# ---------------------------------------------------------------------------
# store_value_to_variant  (infer type from LLVM value, then store)
# ---------------------------------------------------------------------------

def store_value_to_variant(builder: ir.IRBuilder, module: ir.Module,
                            variant_ptr, value) -> None:
    """Store *value* into the variant at *variant_ptr*, inferring the type from the LLVM type.

    This is a convenience wrapper around :func:`store_variant` for callers that
    just have a raw LLVM value and don't want to compute a type tag themselves.
    """
    store_variant(builder, module, variant_ptr, value)


# ---------------------------------------------------------------------------
# extract_for_array_type  (unwrap variant to match an array element type)
# ---------------------------------------------------------------------------

def extract_for_array_type(builder: ir.IRBuilder, module: ir.Module,
                            value, array_type: str) -> ir.Value:
    """Extract the concrete element from a variant to match *array_type*.

    *array_type* is the dtype string stored for the array variable, e.g.
    ``'array_int'``, ``'array_thread'``, ``'array_string'``.  If the value is
    already the right concrete type it is returned as-is.
    """
    variant_ty = get_variant_type()
    _ELEM = {'array_int': 'int', 'array_thread': 'thread', 'array_string': 'string'}
    extract_kind = _ELEM.get(array_type, 'int')

    if hasattr(value, 'type') and value.type == variant_ty:
        tmp = builder.alloca(variant_ty, name="tmp_arr_variant")
        builder.store(value, tmp)
        return extract_variant(builder, module, tmp, extract_kind)
    if (hasattr(value, 'type') and isinstance(value.type, ir.PointerType) and
            value.type.pointee == variant_ty):
        return extract_variant(builder, module, value, extract_kind)
    return value


# ---------------------------------------------------------------------------
# Null variant store
# ---------------------------------------------------------------------------

def store_null_variant(builder: ir.IRBuilder, variant_ptr) -> None:
    """Write a null variant (type_tag=8, zero data) to *variant_ptr*."""
    type_tags = get_variant_type_tag_enum()
    null_tag = type_tags['null']

    tag_ptr = builder.gep(variant_ptr,
                           [ir.Constant(ir.IntType(32), 0),
                            ir.Constant(ir.IntType(32), 0)])
    builder.store(ir.Constant(ir.IntType(32), null_tag), tag_ptr)

    data_ptr = builder.gep(variant_ptr,
                            [ir.Constant(ir.IntType(32), 0),
                             ir.Constant(ir.IntType(32), 1)])
    data_raw = builder.bitcast(data_ptr, ir.IntType(8).as_pointer())
    for i in range(16):
        elem = builder.gep(data_raw, [ir.Constant(ir.IntType(32), i)])
        builder.store(ir.Constant(ir.IntType(8), 0), elem)
