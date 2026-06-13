"""Make the pip-installed NVIDIA CUDA DLLs (cuBLAS/cuDNN) discoverable on Windows.

ctranslate2 loads cublas64_12.dll / cudnn_*.dll by name. The nvidia-*-cu12 wheels
drop these inside site-packages\nvidia\<lib>\bin, which Windows does not search by
default. Calling enable() once (before faster_whisper is imported) fixes that.
"""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path

_enabled = False


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    for p in site.getsitepackages() + [site.getusersitepackages()]:
        roots.append(Path(p) / "nvidia")
    # venv layout fallback
    roots.append(Path(sys.prefix) / "Lib" / "site-packages" / "nvidia")
    return roots


def enable() -> None:
    global _enabled
    if _enabled or os.name != "nt":
        _enabled = True
        return
    for root in _candidate_roots():
        if not root.is_dir():
            continue
        for bin_dir in root.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except (FileNotFoundError, OSError):
                pass
            # also prepend to PATH for good measure
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    _enabled = True
