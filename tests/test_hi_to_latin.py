"""Hindi (Devanagari) → Latin via IAST + press-style fixups.

Pipeline: indic_transliteration emits academic IAST (with macrons /
underdots / vocalic-r); we strip those to ASCII and apply schwa
deletion (word-final 'a' drops after a single consonant unit).

Where 'press' style and IAST diverge:
- macrons: ā/ī/ū → a/i/u
- nasals: ṃ/ṅ/ñ/ṇ → n
- vocalic r: ṛ → ri (Krishna not Kṛṣṇa)
- retroflex stops collapse: ṭ/ḍ → t/d
- sibilants: ś/ṣ → sh
- palatal c: c → ch (Bachchan not Baccan)
- inherent schwa drops: rāma → Ram, amita → Amit
- consonant clusters preserve schwa: kṛṣṇa → Krishna, narendra → Narendra
- aspirated digraphs (bh/dh/gh/etc.) treated as single consonants for
  cluster detection (अमिताभ → Amitabh not Amitabha)
"""
import pytest

from translit_core import detect_source_script, supported_pairs, transliterate


# === Detection ============================================================

@pytest.mark.parametrize(
    "name", ["अमित", "राम", "नरेंद्र मोदी", "महात्मा गांधी"]
)
def test_devanagari_detected_as_hi(name):
    assert detect_source_script(name) == "hi"


# === Common given names (schwa-deleted) ===================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("अमित", "Amit"),     # rāma-pattern: drop final inherent 'a'
        ("राज", "Raj"),
        ("राम", "Ram"),
        ("शिव", "Shiv"),
        ("सूरज", "Suraj"),
        ("करण", "Karan"),
        ("रोहित", "Rohit"),
    ],
)
def test_short_names_schwa_dropped(name, expected):
    """Names ending in consonant + inherent 'a' drop the schwa per modern
    Hindi pronunciation."""
    assert transliterate(name, "en", source_lang="hi") == expected


# === Names ending in long vowel (schwa NOT applicable) ====================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("सुनीता", "Sunita"),    # explicit long ā at end → keep, strip macron
        ("दीपिका", "Dipika"),    # ends in long ā
        ("प्रीति", "Priti"),     # ends in long ī → drop macron
        ("राहुल", "Rahul"),      # ends in consonant 'l'
        ("अंजली", "Anjali"),
    ],
)
def test_names_with_explicit_long_vowels(name, expected):
    """When the input ends in an explicit long vowel (ā/ī/ū), the
    schwa-delete rule doesn't apply — the vowel stays and just loses
    its macron."""
    assert transliterate(name, "en", source_lang="hi") == expected


# === Consonant clusters preserve final schwa =============================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("कृष्ण", "Krishna"),       # cluster ṣ+ṇ before final a
        ("नरेंद्र", "Narendra"),    # cluster nd+r before final a
        ("लक्ष्मी", "Lakshmi"),     # ī ending, no schwa to delete
        ("शर्मा", "Sharma"),        # explicit ā
        ("वर्मा", "Varma"),
        ("बच्चन", "Bachchan"),     # geminate cc before n+a; schwa drops
                                     # (vowel between cc and n breaks "cluster")
    ],
)
def test_consonant_clusters_keep_schwa(name, expected):
    """Word-final 'a' after a true consonant cluster (e.g., ṣṇ in
    kṛṣṇa, nd+r in narendra) stays — the cluster signals the inherent
    vowel is pronounced."""
    assert transliterate(name, "en", source_lang="hi") == expected


# === Aspirated digraphs (bh/dh/gh) treated as single consonants ===========

@pytest.mark.parametrize(
    "name, expected",
    [
        ("अमिताभ", "Amitabh"),   # ends in -bha; bh is one phoneme so schwa drops
        ("लाभ", "Labh"),         # ends in -bha
        ("शुभ", "Shubh"),        # ends in -bha
        ("दूध", "Dudh"),         # ends in -dha
    ],
)
def test_aspirated_stops_not_treated_as_clusters(name, expected):
    """Aspirated stops (bh/dh/gh/jh/kh/ph/th/ch/ḍh/ṭh) are written as
    digraphs in IAST but are single consonants. The schwa-delete rule
    must treat them as one unit, otherwise 'अमिताभ' would emit
    'Amitabha' instead of 'Amitabh'."""
    assert transliterate(name, "en", source_lang="hi") == expected


# === Palatal stop c → ch ==================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("बच्चन", "Bachchan"),    # cc → chch
        ("चंद्रा", "Chandra"),    # word-initial c → ch
        ("चरण", "Charan"),
    ],
)
def test_palatal_c_renders_as_ch(name, expected):
    """IAST 'c' is the palatal stop /tʃ/ — English press writes it as
    'ch' (Bachchan, not Baccan; Chandra, not Candra)."""
    assert transliterate(name, "en", source_lang="hi") == expected


# === Famous full names ====================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("नरेंद्र मोदी", "Narendra Modi"),
        ("महात्मा गांधी", "Mahatma Gandhi"),
        ("राहुल गांधी", "Rahul Gandhi"),
        ("अमिताभ बच्चन", "Amitabh Bachchan"),
    ],
)
def test_famous_full_names(name, expected):
    assert transliterate(name, "en", source_lang="hi") == expected


# === Vocalic r (ṛ) renders as 'ri' ========================================

def test_vocalic_r_becomes_ri():
    """Sanskrit/Hindi vocalic r (ृ in Devanagari, ṛ in IAST) is written
    as 'ri' in modern English press (Krishna, not Kṛṣṇa or Krsna)."""
    assert transliterate("कृष्ण", "en", source_lang="hi") == "Krishna"


# === Punctuation / digits / Devanagari danda stripped ====================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("राम!", "Ram"),
        ("अमित।", "Amit"),       # Devanagari danda U+0964
        ("अमित॥", "Amit"),       # Double danda U+0965
        ("राम१२३", "Ram"),       # Devanagari digits U+0966-U+096F
        ("«अमित»", "Amit"),
    ],
)
def test_punctuation_and_digits_stripped(name, expected):
    """Non-letter chars in Devanagari block (danda, digits) plus generic
    punctuation are removed before romanization."""
    assert transliterate(name, "en", source_lang="hi") == expected


# === Empty / whitespace ===================================================

@pytest.mark.parametrize("name", ["", "   ", "।।।", "१२३"])
def test_empty_or_no_letters_returns_none(name):
    assert transliterate(name, "en", source_lang="hi") is None


# === Known limitation: anusvara-h (ṃh) — Singh vs Sinha ==================

def test_anusvara_h_emits_sinha_not_singh():
    """सिंह (Sikh surname) is universally written 'Singh' in English,
    but that's a fixed personal/community spelling — phonetically the
    Devanagari is 'siṃha' which our rules render as 'Sinha' (which is
    also a valid Hindi surname). Recovering 'Singh' would need a
    name-specific override dictionary; out of scope."""
    assert transliterate("सिंह", "en", source_lang="hi") == "Sinha"


# === supported_pairs reflects the new route ===============================

def test_supported_pairs_includes_hi_en():
    pairs = supported_pairs()
    assert any(p["source"] == "hi" and p["target"] == "latin" for p in pairs)
