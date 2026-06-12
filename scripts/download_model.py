"""Download (and convert) Whisper models ahead of first run.

For the multilingual large-v3 default and other faster-whisper CT2
models, this just instantiates WhisperModel which triggers the HF
download into ~/.cache/huggingface/hub/.

For --model kz, it does an extra step:
  1. Download akuzdeuov/whisper-base.kk (HuggingFace Transformers format)
  2. Convert HF → CTranslate2 int8 via ctranslate2's programmatic
     TransformersConverter (requires `uv sync --extra setup` for the
     transformers+torch stack; ctranslate2 itself ships with faster-whisper)
  3. Save into %APPDATA%/Soyle/models/whisper-base-kk-ct2/ — Söyle's own
     app-data dir. NOT the HF hub cache: faster-whisper resolves
     slash-containing names as HF repo IDs, so a locally-converted model
     must be loaded by absolute path (see kz_model_dir() in
     soyle.core.transcriber).

The KZ model is ~290 MB on HF; the CT2 int8 conversion produces ~75 MB
on disk. Both fit comfortably alongside large-v3.
"""
from __future__ import annotations

import argparse
import shutil
import sys

from soyle.core.transcriber import kz_model_dir

KZ_HF_REPO = "akuzdeuov/whisper-base.kk"


def _download_and_convert_kz() -> bool:
    """Download akuzdeuov/whisper-base.kk and convert to CT2 int8.

    Returns True on success. The converted model lands in kz_model_dir().
    """
    try:
        from ctranslate2.converters import TransformersConverter
    except ImportError:
        print(
            "ERROR: ctranslate2 converter unavailable. This should ship with "
            "faster-whisper — check your environment.",
            file=sys.stderr,
        )
        return False

    # TransformersConverter imports transformers (and torch) internally.
    # Those are NOT runtime deps of Söyle — install via `uv sync --extra setup`.
    try:
        import transformers  # noqa: F401
    except ImportError:
        print(
            "ERROR: transformers/torch not installed. Run `uv sync --extra setup` "
            "and retry.",
            file=sys.stderr,
        )
        return False

    from faster_whisper import WhisperModel

    target = kz_model_dir()
    target.parent.mkdir(parents=True, exist_ok=True)

    # Convert into a sibling temp dir and swap at the end — a failed
    # re-run (offline, HF hiccup, mid-conversion crash) must never
    # destroy a previously working model at `target`.
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)

    print(f"Downloading {KZ_HF_REPO} and converting HF → CT2 int8 into: {target}")
    try:
        # The output must be SELF-CONTAINED, including the tokenizer.
        # Without tokenizer.json next to model.bin, faster-whisper falls
        # back to the GENERIC openai/whisper-tiny tokenizer fetched from
        # HF (transcribe.py:705-708) — a network dependency AND a
        # vocabulary mismatch risk: the KZ fine-tune ships added_tokens.
        #
        # The KZ repo has no tokenizer.json (slow-tokenizer sidecars
        # only: vocab.json, merges.txt, ... — codex P1 on PR #48), and
        # copy_files raises ValueError on absent entries. So: copy the
        # file that exists, and GENERATE tokenizer.json from the slow
        # files via transformers (slow→fast conversion preserves the
        # fine-tune's full vocabulary, added tokens included).
        converter = TransformersConverter(
            KZ_HF_REPO,
            copy_files=["preprocessor_config.json"],
        )
        converter.convert(str(tmp), quantization="int8", force=True)

        from transformers import WhisperTokenizerFast

        tokenizer = WhisperTokenizerFast.from_pretrained(KZ_HF_REPO)
        tokenizer.backend_tokenizer.save(str(tmp / "tokenizer.json"))
    except Exception as exc:
        print(f"ERROR: conversion failed: {exc}", file=sys.stderr)
        # Clean the partial TEMP output so a retry starts fresh; the
        # previous good model at `target` (if any) is untouched.
        shutil.rmtree(tmp, ignore_errors=True)
        return False

    if target.exists():
        shutil.rmtree(target)
    tmp.rename(target)

    # Smoke test — load the converted artifact exactly the way app.py will.
    print("Verifying converted model loads...")
    _ = WhisperModel(str(target), device="cpu", compute_type="int8")
    print(f"Done. KZ model available at: {target}")
    print(
        "Note: the ~290 MB HF source copy remains in ~/.cache/huggingface/hub "
        "(total ≈365 MB with the converted model). Delete the cache copy via "
        "`huggingface-cli delete-cache` if disk space matters."
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default="large-v3-turbo",
        help="Either a faster-whisper preset (large-v3-turbo, large-v3, "
        "medium, small) or 'kz' for akuzdeuov/whisper-base.kk fine-tune.",
    )
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--compute-type", default="int8")
    args = parser.parse_args()

    if args.model == "kz":
        return 0 if _download_and_convert_kz() else 1

    from faster_whisper import WhisperModel

    print(f"Downloading {args.model} ({args.device}, {args.compute_type})…")
    WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
