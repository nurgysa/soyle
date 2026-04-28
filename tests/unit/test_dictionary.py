"""Tests for DictionaryStore."""
from __future__ import annotations

from pathlib import Path

import pytest

from soyle.core.config import default_config_path
from soyle.core.dictionary import MAX_TERMS, DictionaryStore, default_dictionary_path


@pytest.fixture
def store(tmp_path: Path) -> DictionaryStore:
    return DictionaryStore(path=tmp_path / "dictionary.toml")


def test_empty_when_missing(store: DictionaryStore) -> None:
    assert store.load() == []
    assert store.as_whisper_prompt() == ""
    assert store.as_llm_instruction() == ""


def test_dictionary_path_co_located_with_config() -> None:
    """Dictionary must live in the same directory as config.toml.

    Regression test: dictionary.py used to declare its own APP_NAME constant
    (with the umlaut) while config.py used APP_SLUG (ASCII), causing the two
    files to land in different %APPDATA% subfolders ('Söyle' vs 'Soyle') and
    silently desyncing the user's data after the WhisperFlow → Söyle rebrand.
    """
    assert default_dictionary_path().parent == default_config_path().parent
    assert default_dictionary_path().name == "dictionary.toml"


def test_add_and_persist(store: DictionaryStore) -> None:
    store.add("Söyle")
    store.add("OpenRouter")
    assert store.load() == ["Söyle", "OpenRouter"]
    # file persists across instances
    reloaded = DictionaryStore(path=store.path).load()
    assert reloaded == ["Söyle", "OpenRouter"]


def test_add_dedupes_case_insensitively(store: DictionaryStore) -> None:
    store.add("Söyle")
    store.add("soyle")  # duplicate by casefold
    assert store.load() == ["Söyle"]


def test_add_strips_whitespace(store: DictionaryStore) -> None:
    store.add("  Söyle  ")
    assert store.load() == ["Söyle"]


def test_add_ignores_empty(store: DictionaryStore) -> None:
    store.add("")
    store.add("   ")
    assert store.load() == []


def test_remove_existing(store: DictionaryStore) -> None:
    store.save(["A", "B", "C"])
    store.remove("B")
    assert store.load() == ["A", "C"]


def test_remove_absent_is_noop(store: DictionaryStore) -> None:
    store.save(["A", "B"])
    store.remove("Z")
    assert store.load() == ["A", "B"]


def test_clear(store: DictionaryStore) -> None:
    store.save(["A", "B"])
    store.clear()
    assert store.load() == []


def test_max_terms_enforced(store: DictionaryStore) -> None:
    store.save([f"term{i}" for i in range(MAX_TERMS + 50)])
    assert len(store.load()) == MAX_TERMS


def test_broken_file_recovered(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.toml"
    path.write_text("not a valid [[ toml", encoding="utf-8")
    store = DictionaryStore(path=path)
    assert store.load() == []
    backups = list(tmp_path.glob("dictionary.toml.broken-*"))
    assert len(backups) == 1


def test_whisper_prompt_format(store: DictionaryStore) -> None:
    store.save(["Söyle", "OpenRouter", "Astana"])
    prompt = store.as_whisper_prompt()
    assert prompt.startswith("Glossary:")
    assert "Söyle" in prompt
    assert "OpenRouter" in prompt
    assert "Astana" in prompt


def test_llm_instruction_format(store: DictionaryStore) -> None:
    store.save(["Söyle", "Astana"])
    instr = store.as_llm_instruction()
    assert "verbatim" in instr.lower()
    assert "Söyle" in instr
    assert "Astana" in instr


def test_save_dedupes_order_preserved(store: DictionaryStore) -> None:
    store.save(["A", "B", "A", "C", "b"])
    # 'A' kept on first appearance; 'b' filtered as case-dup of 'B'
    assert store.load() == ["A", "B", "C"]
