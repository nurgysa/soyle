"""Extract translatable strings from src/soyle into .ts files.

Runs pyside6-lupdate over the package and writes/updates the per-language
.ts sources in src/soyle/i18n/. `ru` is the identity locale and has no
.ts file. Run after adding or changing any tr()-wrapped string.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "soyle"
I18N = SRC / "i18n"
LANGS = ("kk", "en")


def main() -> int:
    I18N.mkdir(parents=True, exist_ok=True)
    sources = [str(p) for p in SRC.rglob("*.py")]
    ts_args: list[str] = []
    for lang in LANGS:
        ts_args += ["-ts", str(I18N / f"soyle_{lang}.ts")]
    cmd = ["pyside6-lupdate", *sources, *ts_args]
    print(" ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
