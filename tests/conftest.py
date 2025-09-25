from __future__ import annotations
import sys
from pathlib import Path
import shutil
import subprocess
import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    # tests/ lives at repo_root/tests
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def bin_dir(repo_root: Path) -> Path:
    d = repo_root / "bin"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_cmd(cmd: list[str], *, cwd: Path | None = None, stdin: str | None = None) -> tuple[int, str, str]:
    p = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.PIPE if stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = p.communicate(stdin)
    return p.returncode, out, err


@pytest.fixture(scope="session")
def compile_pseudo_fn(repo_root: Path):
    def _compile(src_file: Path, out_path: Path, *, debug: bool = False, tsan: bool = False) -> tuple[int, str]:
        # Always use the current Python to run the compiler, no venv assumptions
        cmd = [
            sys.executable,
            "-m",
            "alecci",
            str(src_file),
            "-o",
            str(out_path),
        ]
        if debug:
            cmd.append("--debug")
        if not tsan:
            cmd.append("--no-tsan")
        rc, out, err = run_cmd(cmd, cwd=repo_root)
        out_combined = out + err
        # If the executable wasn't produced (e.g., clang missing in user environment),
        # try to link manually using clang if available.
        if not out_path.exists():
            ll_path = src_file.with_suffix('.ll')
            clang = shutil.which('clang')
            if ll_path.exists() and clang:
                link_cmd = [clang, str(ll_path), '-o', str(out_path), '-lpthread']
                if not tsan:
                    # nothing extra
                    pass
                lrc, lout, lerr = run_cmd(link_cmd, cwd=repo_root)
                out_combined += "\n" + lout + lerr
                return lrc, out_combined
            # If we get here and no exe, indicate failure (caller may assert/skip)
            return 1, out_combined + "\nExecutable not produced and clang not available."
        return rc, out_combined
    return _compile


@pytest.fixture(scope="session")
def run_exe_fn(repo_root: Path):
    def _run(exe_path: Path, args: list[str] | None = None, *, stdin: str | None = None) -> tuple[int, str]:
        cmd = [str(exe_path)] + list(map(str, args or []))
        rc, out, err = run_cmd(cmd, cwd=repo_root, stdin=stdin)
        return rc, out + err
    return _run
