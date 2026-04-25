"""Japanese → Latin romanization tests (Hepburn via pykakasi).

Scope for v1 is name-shaped input — single or compound names. Sentence-level
input is out of scope (see TENETS.md §7 on dictionary-driven growth).
"""
import pytest

from translit_core import transliterate

pytestmark = pytest.mark.ja


# --- Pure hiragana names ----------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("たなか", "Tanaka"),
        ("さくら", "Sakura"),
        ("ゆき", "Yuki"),
        ("あい", "Ai"),
        ("けん", "Ken"),
        ("じゅん", "Jun"),
        ("りん", "Rin"),
        ("はな", "Hana"),
        ("みお", "Mio"),
    ],
)
def test_hiragana_names(name, expected):
    assert transliterate(name, "en") == expected


# --- Pure katakana names ----------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("タナカ", "Tanaka"),
        ("サクラ", "Sakura"),
        ("ユキ", "Yuki"),
        ("カナ", "Kana"),
    ],
)
def test_katakana_names(name, expected):
    assert transliterate(name, "en") == expected


# --- Kanji names — require source_lang='ja' to overrule zh default ----------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("田中", "Tanaka"),
        ("山田", "Yamada"),
        ("鈴木", "Suzuki"),
        ("佐藤", "Sato"),      # long vowel (satou) folded at end
        ("高橋", "Takahashi"),
        ("伊藤", "Ito"),       # itou → Ito
        ("渡辺", "Watanabe"),
        ("中村", "Nakamura"),
        ("小林", "Kobayashi"),
    ],
)
def test_kanji_surnames_with_ja_hint(name, expected):
    assert transliterate(name, "en", source_lang="ja") == expected


def test_kanji_without_hint_defaults_to_zh():
    """Script detector treats bare kanji as zh — caller must hint ja for
    Japanese readings. This is a deliberate contract per DESIGN.md."""
    assert transliterate("田中", "en") == "Tian Zhong"
    assert transliterate("田中", "en", source_lang="zh") == "Tian Zhong"


def test_ja_hint_overrides_zh_detection():
    """Caller hint wins even when detector disagrees."""
    assert transliterate("田中", "en", source_lang="ja") == "Tanaka"
    # 王明 read as ja = ōmei → "Omei" in simplified/passport romanization.
    assert transliterate("王明", "en", source_lang="ja") == "Omei"


# --- Mixed kana + kanji -----------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("田中ひろし", "Tanaka Hiroshi"),
        ("山田さくら", "Yamada Sakura"),
    ],
)
def test_mixed_kana_kanji(name, expected):
    """Kanji+kana names tokenize cleanly at the kanji/kana boundary —
    each token romanizes independently and we join with a space."""
    assert transliterate(name, "en") == expected


# --- Long-vowel folding at end-of-string ------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("さとう", "Sato"),   # satou → Sato
        ("こう", "Ko"),        # kou  → Ko
        ("しょう", "Sho"),     # shou → Sho
        ("りょう", "Ryo"),     # ryou → Ryo
        ("しゅう", "Shu"),     # shuu → Shu
        ("ゆう", "Yu"),        # yuu  → Yu
    ],
)
def test_end_of_string_long_vowel_folded(name, expected):
    assert transliterate(name, "en") == expected


# --- Small tsu (gemination) -------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("さっぽろ", "Sapporo"),
        ("がっこう", "Gakko"),  # gakkou → Gakko (end-fold)
        ("きっさ", "Kissa"),
        ("はっぱ", "Happa"),
        ("まっちゃ", "Matcha"),
    ],
)
def test_small_tsu_gemination(name, expected):
    assert transliterate(name, "en") == expected


# --- Hepburn edge cases -----------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("し", "Shi"),
        ("ち", "Chi"),
        ("つ", "Tsu"),
        ("ふ", "Fu"),
        ("じ", "Ji"),
        ("しゅ", "Shu"),
        ("ちゃ", "Cha"),
        ("きょ", "Kyo"),
    ],
)
def test_hepburn_consonant_mappings(name, expected):
    assert transliterate(name, "en") == expected


# --- Capitalization ---------------------------------------------------------

def test_first_letter_is_capitalized():
    assert transliterate("たなか", "en")[0].isupper()


def test_single_token_no_internal_caps():
    """Single-token names get title-case on the first letter only."""
    out = transliterate("たなか", "en")
    assert out == "Tanaka"
    assert out[1:] == "anaka"


# --- Multi-kanji name spacing (pykakasi morpheme boundaries) ---------------

def test_multi_kanji_name_spacing():
    """pykakasi's name dictionary recognizes family+given boundaries for
    common kanji names — 山田太郎 tokenizes as [山田, 太郎]."""
    assert transliterate("山田太郎", "en", source_lang="ja") == "Yamada Taro"


def test_given_and_family_name_spaced():
    assert transliterate("中村花子", "en", source_lang="ja") == "Nakamura Hanako"


# --- Mid-string long vowels (passport mode folds inside single tokens) -----

def test_mid_string_long_vowel_folded_in_single_token():
    """Pure-kana compound names tokenize as one unit (pykakasi can't segment
    unsegmented kana), but passport-mode folds internal long vowels:
    satou+hiroshi → 'satohiroshi'. Space-splitting compound kana would need
    a separate word-boundary detector — not attempted here."""
    assert transliterate("さとうひろし", "en") == "Satohiroshi"
