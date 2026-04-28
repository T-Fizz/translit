"""Thai (Thai script) → Latin via Royal Thai General System (RTGS).

`pythainlp.transliterate.romanize` does the linguistically-hard parts:
tone stripping (RTGS doesn't preserve tones), vowel reordering (Thai
writes some vowels visually before the consonant they phonologically
follow), final-consonant devoicing (จ/ษ/ช → t finally), and consonant
cluster handling.

Our wrapper handles the boundary work: pre-strip non-Thai chars,
reject mixed Thai+Latin alphabetic input, title-case per word.
"""
import pytest

from translit_core import detect_source_script, supported_pairs, transliterate


# === Detection ============================================================

@pytest.mark.parametrize(
    "name", ["สมชาย", "ทักษิณ", "ประยุทธ์ จันทร์โอชา"]
)
def test_thai_detected_as_th(name):
    assert detect_source_script(name) == "th"


# === Common given names ===================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("สมชาย", "Somchai"),
        ("สมหญิง", "Somying"),
        ("ทักษิณ", "Thaksin"),
        ("ประยุทธ์", "Prayut"),
        ("กมล", "Kamon"),
        ("ปรีดี", "Pridi"),
    ],
)
def test_common_names(name, expected):
    """Press output for common names matches the RTGS our library produces."""
    assert transliterate(name, "en", source_lang="th") == expected


# === Final-consonant devoicing rules ======================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("กิจ", "Kit"),     # final จ → t
        ("รัก", "Rak"),     # final ก stays k
        ("ลาภ", "Lap"),     # final ภ → p
    ],
)
def test_final_consonant_devoicing(name, expected):
    """RTGS rules: aspirated stops at final position devoice. The library
    handles this — we just verify it lands."""
    assert transliterate(name, "en", source_lang="th") == expected


# === Complex vowels (some written before the consonant) ===================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("เพื่อน", "Phuean"),    # complex vowel เื อ around the consonant
        ("เกียรติ", "Kianti"),   # vowel เ written before, library handles
    ],
)
def test_complex_vowels(name, expected):
    """Some Thai vowels are visually written BEFORE the consonant they
    follow phonologically (เ, แ, โ, ใ, ไ). pythainlp reorders them."""
    assert transliterate(name, "en", source_lang="th") == expected


# === Multi-name (per-word handling preserved) =============================

def test_multi_word_name():
    assert (
        transliterate("สมชาย ทักษิณ", "en", source_lang="th")
        == "Somchai Thaksin"
    )


# === Punctuation, Thai digits stripped ====================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("สมชาย!", "Somchai"),
        ("สมชาย.", "Somchai"),
        ("สมชาย๑๒๓", "Somchai"),     # Thai digits U+0E50-U+0E59
        ("สมชาย123", "Somchai"),     # ASCII digits
        ("«สมชาย»", "Somchai"),      # quote brackets
    ],
)
def test_non_letter_chars_stripped(name, expected):
    """Punctuation, ASCII digits, and Thai digits all stripped before
    pythainlp sees the input."""
    assert transliterate(name, "en", source_lang="th") == expected


# === Refuses mixed Thai + Latin alphabetic ================================

@pytest.mark.parametrize(
    "name",
    ["Tanaka สมชาย", "สมชาย Smith", "abc สมชาย"],
)
def test_refuses_mixed_alphabets(name):
    """Mixed Thai + Latin alphabetic input — the engine refuses rather
    than passing the Latin letters through pythainlp (which would emit
    them unchanged in the output)."""
    assert transliterate(name, "en", source_lang="th") is None


# === Empty / non-Thai input ===============================================

@pytest.mark.parametrize("name", ["", "   ", "!!!", "123", "Tanaka"])
def test_empty_or_no_thai_returns_none(name):
    assert transliterate(name, "en", source_lang="th") is None


# === supported_pairs reflects the new route ===============================

def test_supported_pairs_includes_th_en():
    pairs = supported_pairs()
    assert any(p["source"] == "th" and p["target"] == "latin" for p in pairs)


# === Documented limitation: famous-person spellings deviate from RTGS ====

def test_famous_person_spelling_uses_rtgs_not_press():
    """Some Thai political figures have established English-press
    spellings that diverge from strict RTGS:
    - ยิ่งลักษณ์ → press 'Yingluck', RTGS 'yinglakt'
    - อภิสิทธิ์ → press 'Abhisit', RTGS 'phisit'
    Recovering press-style would need a personal-name override
    dictionary; out of scope. We emit RTGS as the deterministic
    baseline."""
    out = transliterate("ยิ่งลักษณ์", "en", source_lang="th")
    # Should be the RTGS form, not 'Yingluck'
    assert out is not None
    assert "Yingluck" not in out  # confirm we're NOT giving the press spelling
