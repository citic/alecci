# Alecci Programming Language

A modern programming language with built-in concurrency support, compiled to native code via LLVM.

## Features

- 🚀 **High Performance**: Compiles to optimized native code via LLVM
- 🧵 **Built-in Concurrency**: Native threading, mutexes, barriers, and semaphores
- 🔧 **Modern Syntax**: Clean, readable syntax with type inference
- 🛡️ **Memory Safety**: Variant types and safe array operations
- 🔄 **Sanitizer Support**: Built-in ThreadSanitizer for race conditions and AddressSanitizer for memory safety

## Quick Start

### Installation

```bash
pip install alecci --break-system-packages
```

**Note**: If the `alecci` command is not found after installation, you may need to add the user bin directory to your PATH:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Alternatively, you can run the compiler directly:
```bash
python3 -m alecci
```

### Your First Program

Create a file called `hello.ale`:

```alecci
procedure main(argc, argv)
    print("Hello, Alecci!")
end procedure
```

Compile and run:

```bash
alecci hello.ale -o hello
./hello
```

#### Sanitizer Options

- **Thread Sanitizer (default)**: Detects race conditions and threading issues
  ```bash
  alecci hello.ale -o hello  # TSan enabled by default
  ```

- **AddressSanitizer**: Detects memory errors like buffer overflows
  ```bash
  alecci hello.ale --use-asan -o hello
  ```

- **No Sanitizer**: Disable all sanitizers for maximum performance
  ```bash
  alecci hello.ale --no-tsan -o hello
  ```

### Threading Example

```alecci
procedure worker(thread_number as int)
    print `Worker {thread_number} is running`
end procedure

procedure main(argc, argv)
    shared const thread_count := 4
    
    mutable threads := create_threads(thread_count, worker)
    join_threads(threads)
    
    print("All workers completed!")
end procedure
```

## Language Features

### Variables and Types
```alecci
mutable x := 42          // Mutable integer
const message := "Hello" // Immutable string
mutable arr := array(10, 0) // Array of 10 zeros
```

### Functions
```alecci
function add(a as int, b as int) -> int
    return a + b
end function
```

### Concurrency
```alecci
shared mutable counter := 0
shared mutable mtx := mutex()

procedure increment()
    lock(mtx)
    counter := counter + 1
    unlock(mtx)
end procedure
```

## Installation from Source

If you want to build from source:

```bash
git clone https://github.com/yourusername/alecci.git
cd alecci
pip install -e . --break-system-packages
```

If needed, add the local bin directory to your PATH:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Requirements

- Python 3.8+
- LLVM 14+ (for llvmlite)
- GCC or Clang (for linking)

## Documentation

- [Language Reference](docs/language-reference.md)
- [Concurrency Guide](docs/concurrency.md)
- [Examples](examples/)

## License

MIT License - see [LICENSE](LICENSE) file for details.
