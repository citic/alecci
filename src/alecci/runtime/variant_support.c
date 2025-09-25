#include <string.h>
#include <stdlib.h>
#include <stdio.h>

// Variant type definition
typedef struct alecci_variant {
    int type_tag;
    char value_data[16];  // 16 bytes for value storage
} alecci_variant;

// Type tag constants
typedef enum alecci_type_tag {
    ALECCI_TYPE_INT = 0,
    ALECCI_TYPE_FLOAT = 1,
    ALECCI_TYPE_STRING = 2,
    ALECCI_TYPE_SEMAPHORE = 3,
    ALECCI_TYPE_MUTEX = 4,
    ALECCI_TYPE_BARRIER = 5,
    ALECCI_TYPE_THREAD = 6,
    ALECCI_TYPE_ARRAY = 7,
    ALECCI_TYPE_NULL = 8
} alecci_type_tag;

// Creation functions
alecci_variant variant_create_int(int value) {
    alecci_variant var;
    var.type_tag = ALECCI_TYPE_INT;
    memset(var.value_data, 0, 16);
    memcpy(var.value_data, &value, sizeof(int));
    return var;
}

alecci_variant variant_create_float(double value) {
    alecci_variant var;
    var.type_tag = ALECCI_TYPE_FLOAT;
    memset(var.value_data, 0, 16);
    memcpy(var.value_data, &value, sizeof(double));
    return var;
}

alecci_variant variant_create_string(char* value) {
    alecci_variant var;
    var.type_tag = ALECCI_TYPE_STRING;
    memset(var.value_data, 0, 16);
    memcpy(var.value_data, &value, sizeof(char*));
    return var;
}

alecci_variant variant_create_pointer(void* value, alecci_type_tag tag) {
    alecci_variant var;
    var.type_tag = tag;
    memset(var.value_data, 0, 16);
    memcpy(var.value_data, &value, sizeof(void*));
    return var;
}

alecci_variant variant_create_semaphore(void* value) {
    return variant_create_pointer(value, ALECCI_TYPE_SEMAPHORE);
}

alecci_variant variant_create_mutex(void* value) {
    return variant_create_pointer(value, ALECCI_TYPE_MUTEX);
}

alecci_variant variant_create_barrier(void* value) {
    return variant_create_pointer(value, ALECCI_TYPE_BARRIER);
}

alecci_variant variant_create_thread(void* value) {
    return variant_create_pointer(value, ALECCI_TYPE_THREAD);
}

alecci_variant variant_create_array(void* value) {
    return variant_create_pointer(value, ALECCI_TYPE_ARRAY);
}

alecci_variant variant_create_null() {
    alecci_variant var;
    var.type_tag = ALECCI_TYPE_NULL;
    memset(var.value_data, 0, 16);
    return var;
}

// Type checking functions
char* variant_type(alecci_variant var) {
    switch (var.type_tag) {
        case ALECCI_TYPE_INT: return "int";
        case ALECCI_TYPE_FLOAT: return "float";
        case ALECCI_TYPE_STRING: return "string";
        case ALECCI_TYPE_SEMAPHORE: return "semaphore";
        case ALECCI_TYPE_MUTEX: return "mutex";
        case ALECCI_TYPE_BARRIER: return "barrier";
        case ALECCI_TYPE_THREAD: return "thread";
        case ALECCI_TYPE_ARRAY: return "array";
        case ALECCI_TYPE_NULL: return "null";
        default: return "unknown";
    }
}

int variant_is_int(alecci_variant var) {
    return var.type_tag == ALECCI_TYPE_INT;
}

int variant_is_float(alecci_variant var) {
    return var.type_tag == ALECCI_TYPE_FLOAT;
}

int variant_is_string(alecci_variant var) {
    return var.type_tag == ALECCI_TYPE_STRING;
}

int variant_is_semaphore(alecci_variant var) {
    return var.type_tag == ALECCI_TYPE_SEMAPHORE;
}

int variant_is_mutex(alecci_variant var) {
    return var.type_tag == ALECCI_TYPE_MUTEX;
}

int variant_is_barrier(alecci_variant var) {
    return var.type_tag == ALECCI_TYPE_BARRIER;
}

int variant_is_thread(alecci_variant var) {
    return var.type_tag == ALECCI_TYPE_THREAD;
}

int variant_is_array(alecci_variant var) {
    return var.type_tag == ALECCI_TYPE_ARRAY;
}

int variant_is_null(alecci_variant var) {
    return var.type_tag == ALECCI_TYPE_NULL;
}

// Value extraction functions
int variant_get_int(alecci_variant var) {
    if (var.type_tag != ALECCI_TYPE_INT) {
        fprintf(stderr, "Error: variant_get_int called on non-int variant (type: %s)\n", variant_type(var));
        return 0;
    }
    int value;
    memcpy(&value, var.value_data, sizeof(int));
    return value;
}

double variant_get_float(alecci_variant var) {
    if (var.type_tag != ALECCI_TYPE_FLOAT) {
        fprintf(stderr, "Error: variant_get_float called on non-float variant (type: %s)\n", variant_type(var));
        return 0.0;
    }
    double value;
    memcpy(&value, var.value_data, sizeof(double));
    return value;
}

char* variant_get_string(alecci_variant var) {
    if (var.type_tag != ALECCI_TYPE_STRING) {
        fprintf(stderr, "Error: variant_get_string called on non-string variant (type: %s)\n", variant_type(var));
        return NULL;
    }
    char* value;
    memcpy(&value, var.value_data, sizeof(char*));
    return value;
}

void* variant_get_pointer(alecci_variant var) {
    if (var.type_tag < ALECCI_TYPE_STRING || var.type_tag > ALECCI_TYPE_ARRAY) {
        fprintf(stderr, "Error: variant_get_pointer called on non-pointer variant (type: %s)\n", variant_type(var));
        return NULL;
    }
    void* value;
    memcpy(&value, var.value_data, sizeof(void*));
    return value;
}

// Utility functions
alecci_variant variant_copy(alecci_variant var) {
    alecci_variant copy;
    copy.type_tag = var.type_tag;
    memcpy(copy.value_data, var.value_data, 16);
    return copy;
}

int variant_equals(alecci_variant a, alecci_variant b) {
    if (a.type_tag != b.type_tag) {
        return 0;
    }
    return memcmp(a.value_data, b.value_data, 16) == 0;
}

char* variant_to_string(alecci_variant* var_ptr) {
    static char buffer[256];
    alecci_variant var = *var_ptr;  // Dereference the pointer
    
    switch (var.type_tag) {
        case ALECCI_TYPE_INT:
            snprintf(buffer, sizeof(buffer), "%d", variant_get_int(var));
            break;
        case ALECCI_TYPE_FLOAT:
            snprintf(buffer, sizeof(buffer), "%f", variant_get_float(var));
            break;
        case ALECCI_TYPE_STRING:
            snprintf(buffer, sizeof(buffer), "%s", variant_get_string(var));
            break;
        case ALECCI_TYPE_SEMAPHORE:
            snprintf(buffer, sizeof(buffer), "semaphore@%p", variant_get_pointer(var));
            break;
        case ALECCI_TYPE_MUTEX:
            snprintf(buffer, sizeof(buffer), "mutex@%p", variant_get_pointer(var));
            break;
        case ALECCI_TYPE_BARRIER:
            snprintf(buffer, sizeof(buffer), "barrier@%p", variant_get_pointer(var));
            break;
        case ALECCI_TYPE_THREAD:
            snprintf(buffer, sizeof(buffer), "thread@%p", variant_get_pointer(var));
            break;
        case ALECCI_TYPE_ARRAY:
            snprintf(buffer, sizeof(buffer), "array@%p", variant_get_pointer(var));
            break;
        case ALECCI_TYPE_NULL:
            snprintf(buffer, sizeof(buffer), "null");
            break;
        default:
            snprintf(buffer, sizeof(buffer), "unknown(tag=%d)", var.type_tag);
    }
    return buffer;
}

// Type conversion functions with safety checks
alecci_variant variant_to_int(alecci_variant var) {
    switch (var.type_tag) {
        case ALECCI_TYPE_INT:
            return var;
        case ALECCI_TYPE_FLOAT:
            return variant_create_int((int)variant_get_float(var));
        default:
            fprintf(stderr, "Error: Cannot convert %s to int\n", variant_type(var));
            return variant_create_null();
    }
}

alecci_variant variant_to_float(alecci_variant var) {
    switch (var.type_tag) {
        case ALECCI_TYPE_FLOAT:
            return var;
        case ALECCI_TYPE_INT:
            return variant_create_float((double)variant_get_int(var));
        default:
            fprintf(stderr, "Error: Cannot convert %s to float\n", variant_type(var));
            return variant_create_null();
    }
}
