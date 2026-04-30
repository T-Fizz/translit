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


# --- Phonetic fallback: alkana misses go through the rules-based engine ----

def test_unknown_word_uses_phonetic_fallback():
    """Joaquin (Spanish-origin name) isn't in alkana, but the phonetic
    fallback produces a katakana approximation rather than None."""
    out = transliterate("Joaquin", "ja")
    assert out is not None
    assert all(0x30A0 <= ord(c) <= 0x30FF or c == "・" for c in out)


def test_partial_miss_now_handled_by_fallback():
    """Mixing alkana-known and alkana-unknown words now produces output
    via fallback (alkana for the known word, phonetic engine for the
    unknown). Joined with ・ as usual."""
    out = transliterate("John Joaquin", "ja")
    assert out is not None
    assert "・" in out
    assert out.startswith("ジョン")  # John from alkana


def test_apostrophe_names_handled_via_fallback():
    """Names with apostrophes (O'Brien, D'Angelo) now go through the
    phonetic fallback (apostrophe stripped, then orthographic mapping)."""
    assert transliterate("O'Brien", "ja") is not None


# --- Diacritics still excluded ---------------------------------------------

@pytest.mark.parametrize("name", ["Müller", "café"])
def test_non_ascii_returns_none(name):
    """Diacritics aren't ASCII; phonetic engine refuses them. A name
    dictionary or normalization layer would be needed to handle these
    properly (Müller → ミューラー)."""
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
