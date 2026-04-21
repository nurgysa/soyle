"""Download the Whisper model ahead of first run."""
from __future__ import annotations

import argparse
import sys

from faster_whisper import WhisperModel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="large-v3-turbo")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()

    print(f"Downloading {args.model} ({args.device}, {args.compute_type})…")
    WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
