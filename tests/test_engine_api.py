"""Public API contract for translit_core.

Covers transliterate()'s edge cases and the shape of supported_pairs().
"""
import pytest

from translit_core import supported_pairs, transliterate


# --- Empty / non-alpha inputs -----------------------------------------------

@pytest.mark.parametrize("name", ["", "   ", "\t", "\n"])
def test_empty_or_whitespace_returns_none(name):
    assert transliterate(name, "en") is None


def test_none_name_returns_none():
    """`if not name` guards against None/empty — engine degrades gracefully
    even though HTTP-layer Pydantic should reject None before it reaches here."""
    assert transliterate(None, "en") is None  # type: ignore[arg-type]


# --- Latin input (cannot re-romanize) ---------------------------------------

@pytest.mark.parametrize("name", ["Tanaka", "John Smith", "Sakura"])
def test_latin_input_returns_none(name):
    assert transliterate(name, "en") is None


# --- Unsupported target languages -------------------------------------------

@pytest.mark.parametrize("target", ["ja", "zh", "ko", "ar", "xx", ""])
def test_unsupported_targets_return_none(target):
    """Only Latin-script targets are supported in v1 (see _LATIN_TARGETS)."""
    assert transliterate("たなか", target) is None


@pytest.mark.parametrize("target", ["en", "es", "fr", "de", "it", "pt", "nl", "sv", "pl", "tr", "vi", "id", "tl"])
def test_all_latin_targets_accepted(target):
    """All declared Latin targets produce the same Hepburn romanization —
    the target column is advisory only for now (same output across Latin
    languages; DESIGN.md allows this to diverge once per-target conventions
    land)."""
    assert transliterate("たなか", target) == "Tanaka"


# --- Chinese (zh → en) ------------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("王明", "Wang Ming"),
        ("李華", "Li Hua"),
        ("张伟", "Zhang Wei"),
    ],
)
def test_zh_romanization(name, expected):
    assert transliterate(name, "en", source_lang="zh") == expected


def test_zh_multi_hanzi_is_space_separated():
    """pypinyin naturally produces one syllable per hanzi; join with spaces
    per Chinese-given-name convention (DESIGN.md competitive analysis)."""
    assert transliterate("王明", "en") == "Wang Ming"


# --- supported_pairs() shape ------------------------------------------------

def test_supported_pairs_shape():
    pairs = supported_pairs()
    assert isinstance(pairs, list)
    assert len(pairs) >= 2  # ja and zh at minimum
    for entry in pairs:
        assert set(entry.keys()) == {"source", "target", "method"}
        assert isinstance(entry["source"], str)
        assert isinstance(entry["target"], str)
        assert isinstance(entry["method"], str)


def test_supported_pairs_contains_ja_and_zh():
    sources = {p["source"] for p in supported_pairs()}
    assert "ja" in sources
    assert "zh" in sources
