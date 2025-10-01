#!/usr/bin/env python3
"""
Setup script for the Alecci Programming Language Compiler
"""

from setuptools import setup, find_packages
import os

# Read the README file for the long description
def read_readme():
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "Alecci Programming Language Compiler"

# Read requirements from requirements.txt if it exists
def read_requirements():
    req_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    if os.path.exists(req_path):
        with open(req_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip() and not line.startswith('#')]
    return [
        'llvmlite>=0.40.0',
        'ply>=3.11',
        # Add other dependencies as needed
    ]

setup(
    # Basic package information
    name="alecci",
    version="1.0.0",
    author="Bryan Ulate",
    author_email="bryan.ulate@ucr.ac.cr",
    description="A compiler for the Alecci programming language",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/citic/alecci",
    
    # Package structure
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    
    # Include non-Python files
    package_data={
        "": ["*.txt", "*.md"],
        "runtime": ["*.c", "*.h"],
    },
    include_package_data=True,
    
    # Dependencies
    install_requires=read_requirements(),
    
    # Python version requirement
    python_requires=">=3.8",
    
    # Console script entry points
    entry_points={
        "console_scripts": [
            "alecci=alecci:main",
            "alecci-compile=alecci:main",
        ],
    },
    
    # Classification
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Compilers",
        "Topic :: Software Development :: Code Generators",
        "Operating System :: OS Independent",
        "Environment :: Console",
    ],
    
    # Additional metadata
    keywords="compiler programming-language concurrency threading llvm",

)
