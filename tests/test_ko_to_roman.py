"""Korean (Hangul) → Latin via Revised Romanization + traditional surname overlay.

The traditional overlay layer matters because real-world Korean names appear
in their established Western spellings (Kim, Lee, Park) on passports, news,
business cards — not in pure RR (Gim, I, Bak) which would feel wrong to any
reader. Pure RR is still the fallback for unknown surnames.
"""
import pytest

from translit_core import detect_source_script, supported_pairs, transliterate


# === Script detection ======================================================

@pytest.mark.parametrize("name", ["김", "이민호", "박지성", "안녕"])
def test_hangul_detected_as_ko(name):
    assert detect_source_script(name) == "ko"


# === Common surname overlay (the traditional spellings) ===================

@pytest.mark.parametrize(
    "family, expected",
    [
        ("김", "Kim"),     # RR: Gim
        ("이", "Lee"),     # RR: I
        ("박", "Park"),    # RR: Bak
        ("최", "Choi"),    # RR: Choe
        ("정", "Jung"),    # RR: Jeong
        ("강", "Kang"),    # RR: Gang
        ("조", "Cho"),     # RR: Jo
        ("윤", "Yoon"),    # RR: Yun
        ("문", "Moon"),    # RR: Mun
        ("백", "Baek"),    # RR: Baek (close)
        ("서", "Seo"),     # same
        ("안", "Ahn"),     # RR: An
    ],
)
def test_traditional_surname_spelling(family, expected):
    """Single-syllable input matches the traditional Latin spelling
    rather than strict RR (which would produce 'Gim', 'I', 'Bak')."""
    assert transliterate(family, "en", source_lang="ko") == expected


# === Famous full names (press style) ======================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("김정은", "Kim Jeong-eun"),
        ("이민호", "Lee Min-ho"),
        ("박지성", "Park Ji-seong"),
        ("문재인", "Moon Jae-in"),
        ("윤석열", "Yoon Seok-yeol"),
        ("박근혜", "Park Geun-hye"),
        ("류현진", "Ryu Hyeon-jin"),
        ("손흥민", "Son Heung-min"),
    ],
)
def test_full_names_press_style(name, expected):
    """Press convention: surname + space + given-name (hyphenated, second
    syllable lowercase)."""
    assert transliterate(name, "en", source_lang="ko") == expected


# === Two-syllable family names ============================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("남궁민", "Namgoong Min"),
        ("황보영", "Hwangbo Yeong"),
        ("사공준호", "Sagong Jun-ho"),
        ("제갈공명", "Jegal Gong-myeong"),
    ],
)
def test_two_syllable_family_names(name, expected):
    """남궁/황보/사공/제갈/선우/독고 are 2-syllable family names — overlay
    lookup beats the default 1-syllable family heuristic."""
    assert transliterate(name, "en", source_lang="ko") == expected


def test_two_syllable_family_alone():
    """남궁 alone (no given-name part) emits just the family overlay form,
    not split into 'Nam Gung'."""
    assert transliterate("남궁", "en", source_lang="ko") == "Namgoong"


# === Unknown family names → RR fallback ===================================

def test_unknown_family_falls_back_to_rr():
    """Surnames not in the overlay get romanized via RR per syllable.
    동방신기 isn't a real surname (it's a band name) but exercises the path."""
    assert transliterate("동방신기", "en", source_lang="ko") == "Dong Bang-sin-gi"


def test_rare_known_surname_overlay():
    """Less-common but tracked surname."""
    assert transliterate("심청", "en", source_lang="ko") == "Shim Cheong"


# === Single-syllable input ================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("김", "Kim"),    # overlay
        ("박", "Park"),   # overlay
        ("나", "Na"),     # not in overlay → RR
    ],
)
def test_single_syllable_input(name, expected):
    """Single Hangul block: emit the family form (overlay or RR), no
    given-name part."""
    assert transliterate(name, "en", source_lang="ko") == expected


# === name_order swap ======================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("박지성", "Ji-seong Park"),
        ("김정은", "Jeong-eun Kim"),
        ("문재인", "Jae-in Moon"),
    ],
)
def test_given_first_order(name, expected):
    """name_order='given-first' flips to 'Given-name Family'."""
    assert (
        transliterate(name, "en", source_lang="ko", name_order="given-first")
        == expected
    )


def test_given_first_with_two_syllable_family():
    assert (
        transliterate("남궁민", "en", source_lang="ko", name_order="given-first")
        == "Min Namgoong"
    )


def test_given_first_no_op_for_single_syllable():
    """Single-syllable input has nothing to swap with — emits unchanged."""
    assert (
        transliterate("김", "en", source_lang="ko", name_order="given-first")
        == "Kim"
    )


# === Per-syllable RR correctness ==========================================

@pytest.mark.parametrize(
    "name, expected",
    [
        # Initial ㄹ → 'r' (NOT 'l' as some rule sets get wrong)
        ("류재일", "Ryu Jae-il"),
        # Final ㄱ at pause → 'k' (RR), used in family + given via fallback
        ("학수", "Hak Su"),  # 학 isn't in overlay → RR family 'Hak', given 'Su'
        # Final ㅇ → 'ng' — exercise via given-name position so the
        # surname overlay doesn't fire on 정
        ("박정성", "Park Jeong-seong"),
    ],
)
def test_rr_per_syllable_edges(name, expected):
    """Spot-check our RR table on edge consonants."""
    assert transliterate(name, "en", source_lang="ko") == expected


# === Empty / non-Korean inputs ============================================

@pytest.mark.parametrize("name", ["", "   ", "Tanaka", "田中", "たなか"])
def test_non_korean_or_empty_returns_none_or_other_path(name):
    """Engine must not produce Korean output for non-Korean input.
    transliterate may route via other paths (e.g., 田中 → Tian Zhong via zh)
    but should never fire _ko_to_roman against non-Hangul content."""
    result = transliterate(name, "en", source_lang="ko")
    # Either None or a non-Korean-style output — never a hyphenated KO form.
    if result is not None:
        # If routed to another path, accept; just check it's not garbage.
        assert "-" not in result or " " not in result


# === Mixed Hangul + non-Hangul ============================================

def test_hangul_with_trailing_punctuation():
    """Punctuation strips out, just like in ja path."""
    assert transliterate("김정은。", "en", source_lang="ko") == "Kim Jeong-eun"


def test_hangul_with_digits():
    """Digits are non-Hangul; stripped before romanization."""
    assert transliterate("박지성7", "en", source_lang="ko") == "Park Ji-seong"


# === Korean honorifics =====================================================

@pytest.mark.parametrize(
    "name, expected",
    [
        ("박지성씨", "Park Ji-seong-ssi"),
        ("김민수님", "Kim Min-su-nim"),
        ("이선생님", "Lee-seonsaengnim"),  # single-syl family + 3-syl honorific
        ("박씨", "Park-ssi"),               # single-syl family + ssi
        ("남궁민씨", "Namgoong Min-ssi"),    # 2-syl family
    ],
)
def test_korean_honorifics(name, expected):
    """씨/님/선생님 strip from the end and re-attach as -ssi/-nim/-seonsaengnim."""
    assert transliterate(name, "en", source_lang="ko") == expected


def test_compound_honorific_outranks_simple():
    """선생님 (3 chars) must match before 님 (1 char) — longest-suffix-wins."""
    out = transliterate("이선생님", "en", source_lang="ko")
    assert out.endswith("-seonsaengnim")
    assert "Lee" in out


def test_bare_honorific_not_stripped():
    """씨 alone (no name to attach to) doesn't strip — falls through to RR."""
    assert transliterate("씨", "en", source_lang="ko") == "Ssi"
    assert transliterate("님", "en", source_lang="ko") == "Nim"


# === Hanja form of Korean names is out of scope (documented limit) ========

def test_hanja_korean_names_route_through_chinese():
    """金正恩 (the Hanja form of 김정은 'Kim Jong-un') routes through
    pypinyin because the engine has no Hanja → Korean-reading dictionary.
    Output is the Mandarin pinyin of those characters, not the Korean
    reading. Caller must supply Hangul to get a Korean transliteration."""
    out = transliterate("金正恩", "en", source_lang="zh")
    assert out is not None and "Jin" in out  # Mandarin Jin, not Korean Kim


# === Press-style vowel renderings differ from RR (documented) =============

@pytest.mark.parametrize(
    "name, rr, press_alt",
    [
        ("김정일", "Kim Jeong-il", "Kim Jong-il"),
        ("노무현", "Noh Mu-hyeon", "Roh Moo-hyun"),
        ("이명박", "Lee Myeong-bak", "Lee Myung-bak"),
    ],
)
def test_rr_vowel_choice(name, rr, press_alt):
    """We emit RR consistently. Press style varies by individual and
    isn't recoverable from the Hangul. RR is the deterministic baseline."""
    assert transliterate(name, "en", source_lang="ko") == rr


# === supported_pairs reflects the new route ================================

def test_supported_pairs_includes_ko_en():
    pairs = supported_pairs()
    assert any(p["source"] == "ko" and p["target"] == "latin" for p in pairs)
