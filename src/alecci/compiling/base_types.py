from llvmlite import ir
import re

# Cache for variant type to ensure we use the same struct type everywhere
_variant_type_cache = None

# Registry for user-defined record types
_record_registry = {}  # name → {'fields': [{'name': str, 'type': str}], 'llvm_type': LiteralStructType}

def get_variant_type():
    """Get the LLVM struct type for variant values"""
    global _variant_type_cache
    if _variant_type_cache is None:
        # Create variant struct: { i32 type_tag, [16 x i8] value_data }
        # The value_data is large enough to hold any basic type or pointer
        type_tag = ir.IntType(32)
        value_data = ir.ArrayType(ir.IntType(8), 16)  # 16 bytes for value storage
        _variant_type_cache = ir.LiteralStructType([type_tag, value_data])
    return _variant_type_cache

def get_variant_type_tag_enum():
    """Get the type tag constants for variant types"""
    return {
        'int': 0,
        'float': 1,
        'string': 2,
        'semaphore': 3,
        'mutex': 4,
        'barrier': 5,
        'thread': 6,
        'array': 7,
        'null': 8,
        'condvar': 9,
        'record': 10,
    }

# Shared map of named scalar types used by both get_type and get_raw_type.
_SCALAR_TYPE_MAP = {
    "int":       lambda: ir.IntType(32),
    "float":     lambda: ir.DoubleType(),
    "char":      lambda: ir.IntType(8),
    "string":    lambda: ir.IntType(8).as_pointer(),
    "text":      lambda: ir.IntType(8).as_pointer(),  # user-facing alias for string
    "semaphore": lambda: ir.IntType(8).as_pointer(),
    "barrier":   lambda: ir.IntType(8).as_pointer(),
    "thread":    lambda: ir.IntType(8).as_pointer(),
    "mutex":     lambda: ir.IntType(8).as_pointer(),
    "condvar":   lambda: ir.IntType(8).as_pointer(),
    "variant":   get_variant_type,
}


def get_type(type_str: str):
    """Get LLVM type from string representation, including array types.

    For unknown / unspecified types the fallback is the variant struct so that
    untyped Alecci variables are transparently wrapped.
    """
    if type_str in _SCALAR_TYPE_MAP:
        return _SCALAR_TYPE_MAP[type_str]()
    if is_array_type(type_str):
        element_type, size = parse_array_type(type_str)
        base_type = get_type(element_type)
        return ir.ArrayType(base_type, size) if size is not None else base_type.as_pointer()
    if is_record_type(type_str):
        return get_record_llvm_type(type_str)
    # Unknown / untyped → variant
    return get_variant_type()


def get_raw_type(type_str: str):
    """Get the LLVM type without variant-wrapping fallback.

    Identical to :func:`get_type` for all known named types; falls back to
    ``i32`` (not variant) for unknown types.  Used internally where a concrete
    low-level type is required.
    """
    if type_str in _SCALAR_TYPE_MAP:
        return _SCALAR_TYPE_MAP[type_str]()
    if is_array_type(type_str):
        element_type, size = parse_array_type(type_str)
        base_type = get_raw_type(element_type)
        return ir.ArrayType(base_type, size) if size is not None else base_type.as_pointer()
    return ir.IntType(32)  # default to int

def is_array_type(type_str: str) -> bool:
    """Check if type string represents an array type"""
    if type_str is None:
        return False
    return type_str.startswith("array")

def parse_array_type(type_str: str) -> tuple:
    """Parse array type string and return (element_type, size)"""
    if type_str is None:
        return 'int', None
    
    # Match patterns like:
    # "array[10] of int" -> ("int", 10)
    # "array of int" -> ("int", None)
    # "array[5] of float" -> ("float", 5)
    
    # Pattern with size: array[size] of element_type
    sized_pattern = r'array\[(\d+)\]\s+of\s+(\w+)'
    match = re.match(sized_pattern, type_str.strip())
    if match:
        size = int(match.group(1))
        element_type = match.group(2)
        return element_type, size
    
    # Pattern without size: array of element_type
    unsized_pattern = r'array\s+of\s+(\w+)'
    match = re.match(unsized_pattern, type_str.strip())
    if match:
        element_type = match.group(1)
        return element_type, None
    
    # Fallback - assume it's "array of int" if we can't parse
    return "int", None

def get_array_element_type(type_str: str) -> str:
    """Get the element type from an array type string"""
    if is_array_type(type_str):
        element_type, _ = parse_array_type(type_str)
        return element_type
    return type_str

def is_variant_type(type_str: str) -> bool:
    """Check if a type should be stored as a variant (transparent variant system)"""
    if type_str is None:
        return True  # Untyped variables become variants
    # Only explicit 'variant' type should be variants - all other types (int, float, string, etc.) remain native
    return type_str == 'variant'

def get_type_tag_for_value(value, type_hint=None):
    """Get the appropriate type tag for a value being stored in a variant"""
    from .base_types import get_variant_type_tag_enum
    type_tags = get_variant_type_tag_enum()
    
    if type_hint:
        if type_hint in type_tags:
            return type_tags[type_hint]
    
    if hasattr(value, 'type'):
        # LLVM value - check the type
        if isinstance(value.type, ir.IntType) and value.type.width == 32:
            return type_tags['int']
        elif isinstance(value.type, ir.DoubleType):
            return type_tags['float']
        elif isinstance(value.type, ir.PointerType) and value.type.pointee == ir.IntType(8):
            return type_tags['string']
    
    # Fallback to int
    return type_tags['int']


# ---------------------------------------------------------------------------
# Record type registry
# ---------------------------------------------------------------------------

def _normalise_field_type(type_str: str) -> str:
    """Normalise user-facing type aliases to canonical names."""
    return 'string' if type_str == 'text' else type_str


def register_record(name: str, fields: list) -> ir.LiteralStructType:
    """Register a record type and cache its LLVM struct type.

    *fields* is a list of {'name': str, 'type': str} dicts as produced by the
    parser's p_record_members rule.  Field types are normalised (text→string)
    before being stored so downstream comparisons use consistent names.
    """
    normalised = [{'name': f['name'], 'type': _normalise_field_type(f['type'])}
                  for f in fields]
    field_llvm_types = [get_type(f['type']) for f in normalised]
    llvm_type = ir.LiteralStructType(field_llvm_types)
    _record_registry[name] = {'fields': normalised, 'llvm_type': llvm_type}
    return llvm_type


def is_record_type(type_str) -> bool:
    """Return True if *type_str* names a registered record type."""
    return isinstance(type_str, str) and type_str in _record_registry


def get_record_llvm_type(name: str) -> ir.LiteralStructType:
    return _record_registry[name]['llvm_type']


def get_record_fields(name: str) -> list:
    """Return the normalised field list for *name*."""
    return _record_registry[name]['fields']


def get_record_field_index(record_name: str, field_name: str) -> int:
    """Return the 0-based index of *field_name* in *record_name*.

    Raises KeyError if either the record or the field is not found.
    """
    for idx, field in enumerate(_record_registry[record_name]['fields']):
        if field['name'] == field_name:
            return idx
    raise KeyError(f"field '{field_name}' not found in record '{record_name}'")


def make_zero_constant(llvm_type) -> 'ir.Constant':
    """Return an LLVM zero constant for *llvm_type* (recursive for structs/arrays)."""
    if isinstance(llvm_type, ir.IntType):
        return ir.Constant(llvm_type, 0)
    if isinstance(llvm_type, ir.DoubleType):
        return ir.Constant(llvm_type, 0.0)
    if isinstance(llvm_type, ir.PointerType):
        return ir.Constant(llvm_type, None)  # null pointer
    if isinstance(llvm_type, ir.ArrayType):
        elems = [make_zero_constant(llvm_type.element) for _ in range(llvm_type.count)]
        return ir.Constant(llvm_type, elems)
    if isinstance(llvm_type, ir.LiteralStructType):
        elems = [make_zero_constant(t) for t in llvm_type.elements]
        return ir.Constant(llvm_type, elems)
    # Fallback
    return ir.Constant(llvm_type, ir.Undefined)
