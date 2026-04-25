"""English (Latin script) → Japanese (katakana) via alkana.

Coverage gaps are intentional: alkana ships an ASCII-only English dictionary;
diacritics, hyphens, apostrophes, and unknown words return None rather than
producing best-effort garbage. Multi-word names join with '・', the standard
separator for foreign names rendered in Japanese.
"""
import pytest

from translit_core import transliterate


# --- Common single-word names ----------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("John", "ジョン"),
        ("Michael", "マイケル"),
        ("Sarah", "サラ"),
        ("Christopher", "クリストファー"),
        ("Smith", "スミス"),
        ("Phoenix", "フェニックス"),
        ("Schwarzenegger", "シュワルツェネッガー"),
    ],
)
def test_common_english_names(name, expected):
    assert transliterate(name, "ja") == expected


# --- Common English words --------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("computer", "コンピューター"),
        ("music", "ミュージック"),
        ("hello", "ハロー"),
    ],
)
def test_common_english_words(name, expected):
    assert transliterate(name, "ja") == expected


# --- Case insensitivity (katakana has no case) -----------------------------

@pytest.mark.parametrize("variant", ["John", "JOHN", "john", "jOhN"])
def test_input_case_does_not_change_output(variant):
    assert transliterate(variant, "ja") == "ジョン"


# --- Multi-word names join with ・ ------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("John Smith", "ジョン・スミス"),
        ("Michael Phoenix", "マイケル・フェニックス"),
    ],
)
def test_multi_word_names_use_middle_dot(name, expected):
    assert transliterate(name, "ja") == expected


def test_three_word_name():
    out = transliterate("Mary Jane Watson", "ja")
    assert out is not None
    assert out.count("・") == 2
    assert out.startswith("メアリー・")


# --- Fail-soft: any unknown word → None entire response --------------------

def test_unknown_word_returns_none():
    """Joaquin (Spanish-origin name) is not in alkana's dictionary."""
    assert transliterate("Joaquin", "ja") is None


def test_partial_miss_returns_none_not_partial():
    """Mixing a known word with an unknown one returns None entirely
    rather than '<known>・None' garble."""
    assert transliterate("John Joaquin", "ja") is None


# --- Diacritics & punctuation: alkana is ASCII-only ------------------------

@pytest.mark.parametrize("name", ["Müller", "café", "O'Brien", "Mary-Jane"])
def test_non_ascii_or_punctuated_returns_none(name):
    """alkana's dict is ASCII-only — non-ASCII or punctuated names miss."""
    assert transliterate(name, "ja") is None


# --- Empty / whitespace ----------------------------------------------------

@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_empty_or_whitespace(name):
    assert transliterate(name, "ja") is None


# --- Other source scripts → ja: out of scope -------------------------------

def test_japanese_to_japanese_returns_none():
    """Transliterating Japanese to Japanese is meaningless; engine refuses."""
    assert transliterate("たなか", "ja") is None


def test_chinese_to_katakana_not_supported():
    assert transliterate("王明", "ja", source_lang="zh") is None


# --- supported_pairs reflects the new route --------------------------------

def test_supported_pairs_includes_en_ja():
    from translit_core import supported_pairs
    pairs = supported_pairs()
    assert any(p["source"] == "en" and p["target"] == "ja" for p in pairs)
