import pytest

from translit_core import detect_source_script

pytestmark = pytest.mark.script_detection


@pytest.mark.parametrize(
    "name, expected",
    [
        ("たなか", "ja"),
        ("さくら", "ja"),
        ("ひろし", "ja"),
        ("あいうえお", "ja"),
        ("ん", "ja"),
    ],
)
def test_pure_hiragana_is_ja(name, expected):
    assert detect_source_script(name) == expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("タナカ", "ja"),
        ("サクラ", "ja"),
        ("ヒロシ", "ja"),
        ("カナ", "ja"),
    ],
)
def test_pure_katakana_is_ja(name, expected):
    assert detect_source_script(name) == expected


@pytest.mark.parametrize(
    "name",
    ["田中", "山田", "鈴木", "佐藤", "高橋", "王明", "李華"],
)
def test_pure_kanji_defaults_to_zh(name):
    """Pure CJK without kana defaults to 'zh'. The caller must hint source_lang='ja'
    to route these through pykakasi. Anchored because the disambiguation contract
    lives in transliterate(), not here."""
    assert detect_source_script(name) == "zh"


@pytest.mark.parametrize(
    "name",
    ["田中ひろし", "山田さくら", "佐藤タロウ", "鈴木ユキ", "兄ちゃん", "田中様くん"],
)
def test_mixed_kana_and_kanji_is_ja(name):
    """Presence of any kana alongside kanji disambiguates to Japanese —
    Chinese never mixes hiragana/katakana with hanzi."""
    assert detect_source_script(name) == "ja"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Tanaka", "latin"),
        ("John Smith", "latin"),
        ("Sakura", "latin"),
        ("hello", "latin"),
        ("Борис", "ru"),
        ("Москва", "ru"),
        ("김민수", "ko"),
        ("안녕", "ko"),
        ("สวัสดี", "th"),
        ("مرحبا", "ar"),
        ("नमस्ते", "hi"),
    ],
)
def test_non_japanese_scripts(name, expected):
    assert detect_source_script(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "123", "！？。、", "\t\n"])
def test_empty_or_non_alpha_returns_none(name):
    """No alpha chars means no signal — return None rather than guess."""
    assert detect_source_script(name) is None


def test_majority_latin_wins_over_minority_cjk():
    """A name that is mostly Latin with a CJK fragment is classified as Latin.
    Downstream transliterate() will refuse to romanize it (already Latin)."""
    assert detect_source_script("Tanaka田中") == "latin"


def test_kana_kanji_mix_beats_majority_threshold():
    """Hiragana presence forces 'ja' regardless of kanji/kana ratio."""
    assert detect_source_script("あ田中田中田中") == "ja"
