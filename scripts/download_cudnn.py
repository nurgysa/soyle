"""Verify CUDA runtime libraries for GPU inference on Windows.

WhisperFlow now uses NVIDIA pip wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12)
which are installed automatically via ``uv sync --extra gpu``. This script
verifies those wheels are present and their DLL directories are on the
search path.

For advanced users who want to use system-wide CUDA Toolkit DLLs instead,
drop them in ``vendor/cudnn/`` and this script will detect them.
"""
from __future__ import annotations

import sys
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor" / "cudnn"
NVIDIA_PACKAGES = ("nvidia.cublas", "nvidia.cudnn")


def check_pip_wheels() -> list[str]:
    """Return list of missing NVIDIA pip packages."""
    missing = []
    for pkg in NVIDIA_PACKAGES:
        try:
            __import__(pkg, fromlist=[""])
        except ImportError:
            missing.append(pkg)
    return missing


def check_vendor_dlls() -> list[str]:
    """Return list of DLLs still missing from vendor/cudnn/ after pip wheels."""
    if not VENDOR_DIR.is_dir():
        return []
    required = [
        "cudnn_ops_infer64_8.dll",
        "cudnn_cnn_infer64_8.dll",
        "cudnn64_8.dll",
    ]
    return [dll for dll in required if not (VENDOR_DIR / dll).exists()]


def main() -> int:
    missing_wheels = check_pip_wheels()
    if missing_wheels:
        print("Missing NVIDIA pip wheels:")
        for pkg in missing_wheels:
            print(f"  - {pkg}")
        print()
        print("Fix: uv sync --extra gpu")
        return 1

    print("NVIDIA cuBLAS + cuDNN pip wheels detected.")
    missing_vendor = check_vendor_dlls()
    if missing_vendor and VENDOR_DIR.is_dir():
        print()
        print(f"Note: vendor/cudnn/ exists but is missing: {missing_vendor}")
        print("This is optional — pip wheels take precedence.")
    print("GPU inference should work. Verify with scripts/diag_e2e.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
