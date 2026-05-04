# Alecci Programming Language

Alecci is a compiled programming language designed for teaching concurrent and parallel programming. It provides built-in primitives for threading, synchronization, and inter-thread communication, and compiles to native code via LLVM.

The language is used in operating systems and parallel programming courses to help students write, analyze, and debug concurrent programs without the overhead of a general-purpose systems language.

## Installation

```bash
pip install alecci
```

If the `alecci` command is not found after installation, add the user bin directory to your PATH:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

You can also invoke the compiler directly without installing the command:

```bash
python3 -m alecci
```

## System Requirements

- Python 3.8 or later
- LLVM 14 or later (provided via `llvmlite`)
- GCC or Clang for linking

## Usage

```bash
alecci program.ale -o program
./program
```

### Sanitizer options

ThreadSanitizer is enabled by default to detect data races at runtime:

```bash
alecci program.ale -o program          # ThreadSanitizer enabled (default)
alecci program.ale --no-tsan -o program  # Sanitizers disabled
```

## Language Overview

### Variables

```alecci
mutable x := 42
const message := "Hello"
mutable arr := array(10, 0)
```

### Procedures and functions

```alecci
procedure main(argc, argv)
  print("Hello, Alecci!")
end procedure
```

### Threads

```alecci
procedure worker(thread_number as int)
  print `Worker {thread_number} running`
end procedure

procedure main(argc, argv)
  shared const thread_count := 4
  mutable threads := create_threads(thread_count, worker)
  join_threads(threads)
  print("All workers done")
end procedure
```

### Synchronization primitives

```alecci
shared mutable counter := 0
shared mutable mtx as mutex := mutex()

procedure increment(thread_number as int)
  lock(mtx)
  counter := counter + 1
  unlock(mtx)
end procedure
```

Available primitives: `mutex`, `semaphore`, `barrier`, `queue`, `thread`.

## Concurrency Validation

The package includes a test suite (`concurrency_validation/`) with annotated example programs covering common concurrency patterns and bugs, including data races, deadlocks, and thread leaks. These are used to evaluate ThreadSanitizer detection rates.

## Source

Source code is available at [github.com/citic/alecci](https://github.com/citic/alecci).
