/*
 * ThreadSanitizer Default Options for Alecci
 * 
 * This file provides default TSan options optimized for detecting
 * concurrency bugs in educational/teaching contexts.
 * 
 * TSan will call __tsan_default_options() at startup to get these settings.
 * 
 * Note: If you see "WARNING: ThreadSanitizer: memory layout is incompatible",
 * TSan will automatically re-execute with a fixed address space. This is normal.
 */

const char* __tsan_default_options() {
    return "force_seq_cst_atomics=1:"      // Stronger memory ordering
           "flush_memory_ms=1:"             // Flush shadow memory frequently
           "memory_limit_mb=10000:"         // Allow more memory for tracking
           "report_bugs=1:"                 // Report all bugs
           "halt_on_error=0:"               // Don't stop at first error
           "history_size=7:"                // Maximum history for race detection
           "io_sync=0:"                     // Don't synchronize on I/O (can hide races)
           "detect_deadlocks=1:"            // Enable deadlock detection
           "second_deadlock_stack=1";       // Show second stack for deadlocks
}
