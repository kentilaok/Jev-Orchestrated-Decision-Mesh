"""Local Qwen physical concurrency guard for low-VRAM workstations.

No promise of speedup. Parallelism is blocked without an explicit opt-in,
a verified GPU-memory reading and sufficient measured free VRAM.
"""
from __future__ import annotations
import subprocess


def free_vram_mib(*, runner=None):
    argv = ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"]
    try:
        if runner is None:
            proc = subprocess.run(argv, shell=False, capture_output=True,
                                  text=True, timeout=5, check=False)
            if proc.returncode:
                return None
            text = proc.stdout
        else:
            text = runner(argv)
        values = [int(x.strip()) for x in text.splitlines() if x.strip().isdigit()]
        return min(values) if values else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def enforce_parallel_limit(requested, *, consent=False, free_mib=None, min_free_mib=1536):
    if type(requested) is not int or requested not in (1, 2):
        raise ValueError("invalid_parallel_limit")
    if requested == 1:
        return 1
    if consent is not True:
        raise ValueError("parallel_local_opt_in_required")
    free_mib = free_vram_mib() if free_mib is None else free_mib
    if type(free_mib) is not int or free_mib < min_free_mib:
        raise ValueError("insufficient_verified_vram_for_parallel")
    return 2
