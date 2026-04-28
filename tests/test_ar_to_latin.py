"""Arabic (Naskh script) → Latin via curated name dictionary.

Arabic written without short vowels (the normal form) is fundamentally
under-determined for romanization — there's no way to derive 'Muhammad'
from م-ح-م-د via rules. This implementation is a curated overlay of
~50 common Arabic names with their established press spellings; names
not in the dictionary return None (fail-soft) rather than emit
consonant-only Buckwalter-style garbage.

The trade-off: covers ~70-80% of names English readers encounter in
press, near-zero noise on those, but a hard cliff for unknown names.
A name dataset of thousands of entries would extend coverage; an
LLM-fallback Tier 2 would catch the long tail entirely.
"""
import pytest

from translit_core import detect_source_script, supported_pairs, transliterate


# === Detection ============================================================

@pytest.mark.parametrize(
    "name", ["محمد", "أحمد", "فاطمة", "عبد الله"]
)
def test_arabic_detected_as_ar(name):
    assert detect_source_script(name) == "ar"


# === Common male names ====================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("محمد", "Muhammad"),
        ("أحمد", "Ahmad"),
        ("علي", "Ali"),
        ("عمر", "Omar"),
        ("حسن", "Hassan"),
        ("حسين", "Hussein"),
        ("خالد", "Khalid"),
        ("صالح", "Saleh"),
        ("إبراهيم", "Ibrahim"),
        ("يوسف", "Yusuf"),
        ("سلمان", "Salman"),
        ("محمود", "Mahmoud"),
        ("طارق", "Tariq"),
        ("فيصل", "Faisal"),
        ("بلال", "Bilal"),
    ],
)
def test_common_male_names(name, expected):
    """Curated overlay returns the established press spelling."""
    assert transliterate(name, "en", source_lang="ar") == expected


# === Common female names ==================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("فاطمة", "Fatima"),
        ("عائشة", "Aisha"),
        ("خديجة", "Khadija"),
        ("مريم", "Mariam"),
        ("ليلى", "Layla"),
        ("سارة", "Sara"),
        ("نور", "Nour"),
        ("زينب", "Zaynab"),
        ("ياسمين", "Yasmin"),
        ("سلمى", "Salma"),
        ("نادية", "Nadia"),
    ],
)
def test_common_female_names(name, expected):
    assert transliterate(name, "en", source_lang="ar") == expected


# === Compound (multi-token) names =========================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("عبد الله", "Abdullah"),
        ("عبد الرحمن", "Abdul-Rahman"),
        ("عبد العزيز", "Abdul-Aziz"),
        ("عبد الكريم", "Abdul-Karim"),
        ("أبو بكر", "Abu Bakr"),
        ("أم كلثوم", "Umm Kulthum"),
    ],
)
def test_compound_names_match_whole_input(name, expected):
    """Compound names like 'عبد الله' are stored as full-input keys —
    whole-input lookup wins over per-word fallback (which would fail
    because 'عبد' alone isn't in the dict)."""
    assert transliterate(name, "en", source_lang="ar") == expected


# === Multi-name (per-word lookup) =========================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("محمد علي", "Muhammad Ali"),
        ("عمر محمد", "Omar Muhammad"),
        ("فاطمة سارة", "Fatima Sara"),
    ],
)
def test_multi_name_per_word_lookup(name, expected):
    """Two unrelated names with whitespace between → look up each word
    independently, join with space."""
    assert transliterate(name, "en", source_lang="ar") == expected


# === Tashkeel (vowel diacritics) stripped before lookup ===================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("مُحَمَّد", "Muhammad"),    # full vowelization
        ("عَلِي", "Ali"),
        ("فَاطِمَة", "Fatima"),
        ("أَحْمَد", "Ahmad"),
    ],
)
def test_tashkeel_stripped(name, expected):
    """Vowel marks (fatha, damma, kasra, sukun, shadda, etc.) are
    stripped before dictionary lookup — vowelized and unvowelized
    forms of the same name produce identical output."""
    assert transliterate(name, "en", source_lang="ar") == expected


# === Alif-variant normalization ===========================================

def test_hamza_alif_normalized():
    """أحمد (with hamza-bearing alif), إحمد (with hamza below), and
    احمد (plain alif) all normalize to the same dictionary key."""
    out_with = transliterate("أحمد", "en", source_lang="ar")
    out_without = transliterate("احمد", "en", source_lang="ar")
    assert out_with == out_without == "Ahmad"


# === Tatweel (kashida) stripped ===========================================

def test_tatweel_stripped():
    """Tatweel (ـ U+0640) is a visual stretch, not a real character —
    'محمـد' should look up the same as 'محمد'."""
    assert transliterate("محمـد", "en", source_lang="ar") == "Muhammad"


# === Unknown names: fail-soft =============================================

@pytest.mark.parametrize(
    "name",
    [
        "زياده",              # Made-up name (Ziyada — not in dict)
        "محمد زياده",         # Mix of known + unknown → None entirely
        "ﷲ",                  # Allah ligature — in dict it'd be 'الله' alone, not stored
        "xyz",
    ],
)
def test_unknown_names_return_none(name):
    """Names outside the curated overlay return None. Caller should
    treat as 'unsupported' and either fall back to LLM or surface the
    original."""
    assert transliterate(name, "en", source_lang="ar") is None


# === Empty / whitespace ===================================================

@pytest.mark.parametrize("name", ["", "   ", "!!!", "123"])
def test_empty_or_no_arabic_returns_none(name):
    assert transliterate(name, "en", source_lang="ar") is None


# === supported_pairs reflects the new route ===============================

def test_supported_pairs_includes_ar_en():
    pairs = supported_pairs()
    assert any(p["source"] == "ar" and p["target"] == "latin" for p in pairs)


# === Document the fundamental limitation ==================================

def test_unvowelized_unknown_name_explicitly_unsupported():
    """The hard truth: Arabic without vowels cannot be deterministically
    romanized. زياده (a real Arabic word but not in our overlay) returns
    None even though it's perfectly valid Arabic. This is by design —
    the alternative is emitting consonant-only Buckwalter (zyadh) which
    isn't useful for English readers."""
    assert transliterate("زياده", "en", source_lang="ar") is None
