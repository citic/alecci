from llvmlite import ir
import re

# Cache for variant type to ensure we use the same struct type everywhere
_variant_type_cache = None

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
        'null': 8
    }

def get_type(type_str : str):
    """Get LLVM type from string representation, including array types"""
    # For transparent variant system, most variables should be variants
    if type_str == "semaphore":
        return ir.IntType(8).as_pointer()  # sem_t* (opaque pointer)
    elif type_str == "barrier":
        # pthread_barrier_t* (opaque pointer)
        return ir.IntType(8).as_pointer()
    elif type_str == "thread":
        return ir.IntType(8).as_pointer()  # pthread_t* (opaque pointer)
    elif type_str == "mutex":
        return ir.IntType(8).as_pointer()  # pthread_mutex_t* (opaque pointer)
    elif is_array_type(type_str):
        # Parse array type: "array[size] of element_type" or "array of element_type"
        element_type, size = parse_array_type(type_str)
        base_type = get_type(element_type)
        if size is not None:
            return ir.ArrayType(base_type, size)
        else:
            # Dynamic array - return pointer to element type
            return base_type.as_pointer()
    else:
        # For explicitly typed variables, use the actual type
        if type_str == "int":
            return ir.IntType(32)
        elif type_str == "float":
            return ir.DoubleType()
        elif type_str == "string":
            return ir.IntType(8).as_pointer()
        elif type_str == "variant":
            return get_variant_type()
        else:
            # For unspecified types, default to variant
            return get_variant_type()

def get_raw_type(type_str : str):
    """Get the original LLVM type without variant wrapping (for internal use)"""
    if type_str == "int":
        return ir.IntType(32)
    elif type_str == "float":
        return ir.DoubleType()
    elif type_str == "string":
        return ir.IntType(8).as_pointer()
    elif type_str == "semaphore":
        return ir.IntType(8).as_pointer()  # sem_t* (opaque pointer)
    elif type_str == "barrier":
        # pthread_barrier_t* (opaque pointer)
        return ir.IntType(8).as_pointer()
    elif type_str == "thread":
        return ir.IntType(8).as_pointer()  # pthread_t* (opaque pointer)
    elif type_str == "mutex":
        return ir.IntType(8).as_pointer()  # pthread_mutex_t* (opaque pointer)
    elif type_str == "variant":
        return get_variant_type()
    elif is_array_type(type_str):
        # Parse array type: "array[size] of element_type" or "array of element_type"
        element_type, size = parse_array_type(type_str)
        base_type = get_raw_type(element_type)
        if size is not None:
            return ir.ArrayType(base_type, size)
        else:
            # Dynamic array - return pointer to element type
            return base_type.as_pointer()
    else:
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
