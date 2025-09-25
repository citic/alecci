from .parsing import a_parser as parser
from .compiling import compiler
from .parsing import globals

import sys
import subprocess
import argparse

def main():
    #TODO Add support for passing arguments to the compiler
    #TODO: Add support for asan if no thread creation is detected
    parser_arg = argparse.ArgumentParser(description="Alecci Compiler")
    parser_arg.add_argument('filename', nargs='?', help='Source file to compile')
    parser_arg.add_argument('--print-ast', action='store_true', help='Print the AST')
    parser_arg.add_argument('--no-tsan', action='store_true', help='Disable thread sanitizer')
    parser_arg.add_argument('--use-asan', action='store_true', help='Use AddressSanitizer instead of ThreadSanitizer')
    parser_arg.add_argument('--debug', action='store_true', help='Enable debug output')
    parser_arg.add_argument('-o', '--output', help='Name of the output executable')
    args = parser_arg.parse_args()

    # Validate arguments
    if args.use_asan and args.no_tsan:
        print("Warning: --use-asan and --no-tsan are both specified. Using AddressSanitizer.")
    
    if args.filename:
        globals.filename = args.filename
    else:
        globals.filename = input("Please enter the filename: ")

    try:
        with open(globals.filename, 'r') as file:
            data = file.read()
    except FileNotFoundError:
        print(f"File {globals.filename} not found.")
        sys.exit(1)
    ast = parser.toAst(data)
    if args.print_ast:
        parser.pretty_print_ast(ast)
    
    # Set debug mode if requested
    if args.debug:
        compiler.set_debug(True)
    
    # Generate LLVM IR code
    compiled_ir = compiler.CodeGenerator().compile(ast)
    
    # Write the compiled IR code to a temporary .ll file
    output_ir_file = globals.filename.rsplit('.', 1)[0] + '.ll'
    if args.output:
        executable = args.output
    else:
        # Extract just the filename without path and extension for the executable
        import os
        base_filename = os.path.basename(globals.filename).rsplit('.', 1)[0]
        executable = base_filename
    
    with open(output_ir_file, 'w') as f:
        f.write(compiled_ir)
    
    # Call clang to compile the LLVM IR code into an executable
    clang_cmd = ['clang', output_ir_file, '-o', executable]
    
    # Detect if we're in WSL
    import platform
    import os
    is_wsl = False
    try:
        # Check for WSL in /proc/version or environment
        if os.path.exists('/proc/version'):
            with open('/proc/version', 'r') as f:
                version_info = f.read().lower()
                if 'microsoft' in version_info or 'wsl' in version_info:
                    is_wsl = True
        # Also check environment variables
        if 'WSL_DISTRO_NAME' in os.environ or 'WSLENV' in os.environ:
            is_wsl = True
    except:
        pass
    
    # Determine the actual platform (Linux for WSL, Windows for native Windows)
    is_linux = platform.system() == 'Linux' or is_wsl
    is_windows = platform.system() == 'Windows' and not is_wsl
    
    # Add sanitizer if requested and supported
    if args.use_asan:
        if is_linux:
            clang_cmd.extend(['-fsanitize=address', '-g'])
            print("Compiling with AddressSanitizer support")
        else:
            print("Note: AddressSanitizer not fully supported on Windows MSVC, compiling without it")
    elif not args.no_tsan:
        if is_linux:
            clang_cmd.extend(['-fsanitize=thread', '-g'])
            print("Compiling with thread sanitizer support")
        else:
            print("Note: Thread sanitizer not supported on Windows MSVC, compiling without it")
    
    # Add runtime and threading support
    if is_windows:
        # Real Windows: use Windows-specific setup
        if not executable.lower().endswith('.exe'):
            executable += '.exe'
            # Update the clang command with the new executable name
            clang_cmd[3] = executable
        # Add our Windows pthread runtime
        runtime_path = os.path.join(os.path.dirname(__file__), '..', 'runtime', 'windows_pthread.c')
        if os.path.exists(runtime_path):
            clang_cmd.append(runtime_path)
            print(f"Using Windows pthread runtime: {runtime_path}")
        else:
            # Fallback: try to link with pthread library
            clang_cmd.extend(['-lpthread'])
            print("Warning: Windows pthread runtime not found, trying -lpthread")
        
        # Add variant runtime support
        variant_runtime_path = os.path.join(os.path.dirname(__file__), 'runtime', 'variant_support.c')
        if os.path.exists(variant_runtime_path):
            clang_cmd.append(variant_runtime_path)
    else:
        # Linux (including WSL): use standard pthread
        clang_cmd.extend(['-lpthread'])
        
        # Add variant runtime support
        variant_runtime_path = os.path.join(os.path.dirname(__file__), 'runtime', 'variant_support.c')
        if os.path.exists(variant_runtime_path):
            clang_cmd.append(variant_runtime_path)
    
    try:
        result = subprocess.run(clang_cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"Compilation successful! Executable created: {executable}")
        else:
            print("Compilation failed:")
            print(result.stderr)
    except FileNotFoundError:
        print(f"LLVM IR generated successfully: {output_ir_file}")
        print("Note: Clang not found. To create executable, install Clang and run:")
        print(f"  clang {output_ir_file} -o {executable}")
        if args.use_asan:
            print(f"  (with AddressSanitizer: clang -fsanitize=address {output_ir_file} -o {executable})")
        elif not args.no_tsan:
            print(f"  (with thread sanitizer: clang -fsanitize=thread {output_ir_file} -o {executable})")




if __name__ == "__main__":
    main()