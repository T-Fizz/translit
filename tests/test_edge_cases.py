"""Edge cases surfaced by a wide-net probe of the engine.

Each case here documents real behavior the engine commits to:
  - Fixed cases are regression tests — they would re-break if reverted.
  - xfail cases pin the *desired* behavior for issues we deferred — they'll
    flip to PASSED when fixed and the strict=True will alert us.
"""
import pytest

from translit_core import transliterate, detect_source_script


# === Half-width katakana (NFKC normalization) ==============================

def test_halfwidth_katakana_detected_as_ja():
    assert detect_source_script("ｶﾅ") == "ja"


def test_halfwidth_katakana_romanized():
    """Half-width katakana (U+FF65–U+FF9F) is folded to full-width via NFKC
    before pykakasi sees it."""
    assert transliterate("ｶﾅ", "en") == "Kana"


def test_halfwidth_voiced_katakana():
    """ｶﾞ (ka + voicing mark) NFKC-normalizes to ガ (ga)."""
    assert transliterate("ｶﾞ", "en") == "Ga"


def test_halfwidth_katakana_honorific_stripped():
    """Half-width ﾁｬﾝ (chan) honorific should fold and strip just like カナちゃん."""
    assert transliterate("田中ﾁｬﾝ", "en") == "Tanaka-chan"


# === Full-width Latin (NFKC normalization) =================================

def test_fullwidth_latin_detected_and_routed():
    """Ｊｏｈｎ (full-width) NFKC-normalizes to John ASCII and routes via alkana."""
    assert transliterate("Ｊｏｈｎ", "ja") == "ジョン"


# === Punctuation stripping in ja → en =====================================

def test_trailing_punctuation_dropped():
    """田中。 emits 'Tanaka', not 'Tanaka .'"""
    assert transliterate("田中。", "en", source_lang="ja") == "Tanaka"


def test_quote_brackets_dropped():
    """「田中」 emits 'Tanaka', not '( Tanaka )'."""
    assert transliterate("「田中」", "en", source_lang="ja") == "Tanaka"


def test_digits_dropped():
    """田中123 emits 'Tanaka' — digits aren't part of the name. If callers
    need digits preserved they can split before calling."""
    assert transliterate("田中123", "en", source_lang="ja") == "Tanaka"


# === Silent kanji dropout (coverage check) =================================

def test_unknown_4byte_kanji_returns_none():
    """𠮷 (U+20BB7) isn't in pykakasi's dictionary; it gets silently dropped
    from the output. Engine refuses rather than emitting just the readable
    portion of the name."""
    assert transliterate("𠮷田", "en", source_lang="ja") is None


def test_rare_kanji_variant_with_no_reading():
    """髙 (U+9AD9) is a tall-form 高 variant; pykakasi knows the codepoint
    but has no reading. End result: empty hepburn, all-or-nothing returns None."""
    assert transliterate("髙橋", "en", source_lang="ja") is None


# === Whitespace handling ===================================================

def test_full_width_space_treated_as_space():
    """U+3000 ideographic space — pykakasi handles it; we get spacing right."""
    assert transliterate("田中　ひろし", "en") == "Tanaka Hiroshi"


def test_internal_ascii_space():
    assert transliterate("田中 ひろし", "en") == "Tanaka Hiroshi"


def test_internal_newline_or_tab():
    """Newlines and tabs collapse to spacing — caller probably didn't mean
    them, but we don't refuse the input either."""
    assert transliterate("田中\nひろし", "en") is not None
    assert transliterate("田中\tひろし", "en") is not None


# === en → ja whitespace ====================================================

def test_en_to_ja_strips_outer_whitespace():
    assert transliterate("  John  ", "ja") == "ジョン"


def test_en_to_ja_collapses_inner_whitespace():
    assert transliterate("John  Smith", "ja") == "ジョン・スミス"
    assert transliterate("John\nSmith", "ja") == "ジョン・スミス"


# === Single-character / minimal input ======================================

def test_single_hiragana():
    assert transliterate("た", "en") == "Ta"


def test_single_kanji_via_ja_hint():
    assert transliterate("田", "en", source_lang="ja") == "Ta"


def test_bare_prolong_mark():
    """Lone ー (U+30FC) — pykakasi emits '-'; not a name in any meaningful
    sense, but the engine doesn't pretend otherwise."""
    out = transliterate("ー", "en")
    # Either None (after our isalpha filter) or '-' depending on pykakasi —
    # just assert it doesn't crash:
    assert out is None or isinstance(out, str)


# === Mixed scripts =========================================================

def test_mostly_latin_with_kanji_minority_routes_latin():
    """T田中 — 1 latin, 2 kanji. detect = 'zh' (kanji 2/3 = 0.66 over latin 1/3).
    Without ja hint it routes through pypinyin."""
    assert detect_source_script("T田中") == "zh"


def test_emoji_in_input():
    """Emoji is non-alphabetic; ignored by detection. The remaining text
    drives the result."""
    out = transliterate("田中🎌", "en", source_lang="ja")
    assert out == "Tanaka"


# === Long input ============================================================

def test_long_input_does_not_crash():
    """200-char input is valid (under our pydantic 500-char cap). Just shouldn't
    crash or hang."""
    out = transliterate("あ" * 200, "en")
    assert out is not None
    assert len(out) > 0


# === Round-trip lost-information cases (xfail) ============================

@pytest.mark.xfail(
    strict=True,
    reason="Round-trip katakana-loanword names (ヴィクター → 'Victor') need "
    "a Western-name dictionary, not raw kana romanization. Currently emits "
    "'Buikutaa'. Out of scope for v1.",
)
def test_katakana_western_name_round_trip():
    assert transliterate("ヴィクター", "en") == "Victor"


@pytest.mark.xfail(
    strict=True,
    reason="Acronyms aren't consistently in alkana's dictionary (FBI/USA "
    "miss; NASA/IBM hit). Letter-by-letter fallback (FBI → エフビーアイ) "
    "would close the gap. v1.1 candidate.",
)
def test_acronym_letter_by_letter_fallback():
    assert transliterate("FBI", "ja") == "エフビーアイ"


@pytest.mark.xfail(
    strict=True,
    reason="Punctuation in en input (Mr., Jr., O'Brien) breaks alkana lookup. "
    "Could split-and-strip before lookup — minor effort, deferred.",
)
def test_en_with_title_prefix():
    assert transliterate("Mr. Smith", "ja") == "ミスター・スミス"
