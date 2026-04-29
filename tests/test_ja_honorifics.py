"""Japanese honorific detection and romanization.

The engine strips a known trailing honorific from the name, romanizes the
stem via pykakasi, then appends the roman honorific form (`-san`, `-chan`, …).
Honorific dictionary lives in app/transliterate.py:_JA_HONORIFICS_RAW.
"""
import pytest

from translit_core import transliterate

pytestmark = [pytest.mark.ja, pytest.mark.honorifics]


# --- Formal honorifics (kana form) ------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("たなかさん", "Tanaka-san"),
        ("たなかくん", "Tanaka-kun"),
        ("たなかちゃん", "Tanaka-chan"),
        ("たなかさま", "Tanaka-sama"),
        ("たなかどの", "Tanaka-dono"),
        ("たなかせんせい", "Tanaka-sensei"),
        ("たなかはかせ", "Tanaka-hakase"),
        ("たなかせんぱい", "Tanaka-senpai"),
        ("たなかこうはい", "Tanaka-kouhai"),
    ],
)
def test_formal_honorifics_kana(name, expected):
    assert transliterate(name, "en") == expected


# --- Formal honorifics (kanji form) -----------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("たなか様", "Tanaka-sama"),
        ("たなか殿", "Tanaka-dono"),
        ("たなか先生", "Tanaka-sensei"),
        ("たなか博士", "Tanaka-hakase"),
        ("たなか先輩", "Tanaka-senpai"),
        ("たなか後輩", "Tanaka-kouhai"),
    ],
)
def test_formal_honorifics_kanji(name, expected):
    """Kanji honorific suffixes appended to a kana name — detector still
    reads 'ja' because the leading kana dominates script counts."""
    assert transliterate(name, "en") == expected


def test_kanji_name_with_kanji_honorific_needs_ja_hint():
    """Pure-kanji 田中先生 defaults to zh without a source hint."""
    assert transliterate("田中先生", "en", source_lang="ja") == "Tanaka-sensei"
    assert transliterate("田中様", "en", source_lang="ja") == "Tanaka-sama"


# --- Slang / moe honorifics -------------------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("たなかっち", "Tanaka-cchi"),
        ("たなかにゃん", "Tanaka-nyan"),
        ("たなかぴょん", "Tanaka-pyon"),
        ("たなかきゅん", "Tanaka-kyun"),
        ("たなかたん", "Tanaka-tan"),
        ("たなかちん", "Tanaka-chin"),
        ("たなかぽん", "Tanaka-pon"),
        ("たなかりん", "Tanaka-rin"),
        ("たなかぼん", "Tanaka-bon"),
    ],
)
def test_slang_honorifics(name, expected):
    assert transliterate(name, "en") == expected


# --- Katakana-variant honorific folding -------------------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("カナチャン", "Kana-chan"),
        ("ヒロシサン", "Hiroshi-san"),
        ("たなかサン", "Tanaka-san"),
        ("タナカちゃん", "Tanaka-chan"),
    ],
)
def test_katakana_honorific_folds_to_hiragana(name, expected):
    """Honorifics written in katakana should be detected via the katakana→
    hiragana fold in _katakana_to_hiragana."""
    assert transliterate(name, "en") == expected


# --- Compound family honorifics (longest-suffix-wins) -----------------------

def test_compound_honorific_on_name_stem():
    """When there's a stem before the compound, longest-suffix-first
    correctly picks the compound (e.g. '兄ちゃん' is 4 chars vs 'ちゃん' at 3)."""
    assert transliterate("田中兄さん", "en", source_lang="ja") == "Tanaka-niisan"
    assert transliterate("田中姉さん", "en", source_lang="ja") == "Tanaka-neesan"
    assert transliterate("田中にいさん", "en", source_lang="ja") == "Tanaka-niisan"
    assert transliterate("田中ねえさん", "en", source_lang="ja") == "Tanaka-neesan"


# --- Bare-suffix guard ------------------------------------------------------

def test_bare_simple_honorific_not_stripped():
    """Input that IS the honorific (e.g. 'ちゃん' alone) must not be stripped
    to an empty stem. Falls through to pykakasi which romanizes the kana."""
    assert transliterate("ちゃん", "en") == "Chan"
    assert transliterate("さん", "en") == "San"


# --- Known-limitation regressions (xfail documents ideal behavior) ----------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("兄ちゃん", "Niichan"),
        ("姉ちゃん", "Neechan"),
        ("兄さん", "Niisan"),
        ("姉さん", "Neesan"),
        ("にいさん", "Niisan"),
        ("ねえさん", "Neesan"),
        ("にいちゃん", "Niichan"),
        ("ねえちゃん", "Neechan"),
    ],
)
def test_compound_honorific_as_whole_input(name, expected):
    """When the whole input IS a compound kinship term, emit its dict form
    rather than falling through to a shorter suffix + pykakasi read."""
    assert transliterate(name, "en") == expected


# --- Geminated nickname forms (sokuon nicknames) ----------------------------

@pytest.mark.parametrize(
    "name, expected",
    [
        # Pure-kana: explicit small tsu in the input. Pykakasi already produces
        # the correct geminated romanization; engine just needs to NOT split
        # at the honorific boundary, which would destroy the geminate.
        ("いっちゃん", "Itchan"),
        ("はっちゃん", "Hatchan"),
        ("ろっちゃん", "Rotchan"),
        ("カッちゃん", "Katchan"),  # pykakasi passport: 'tch' rather than 'cch'
        # Single-kanji + ちゃん: applies the gemination heuristic when the
        # kanji's reading ends in chi/tsu/ku.
        ("一ちゃん", "Itchan"),    # ichi → it + chan
        ("八ちゃん", "Hatchan"),   # hachi → hat + chan
        ("六ちゃん", "Rotchan"),   # roku → rot + chan
        ("律ちゃん", "Ritchan"),   # ritsu → rit + chan
        ("七ちゃん", "Shitchan"),  # shichi → shit + chan
    ],
)
def test_geminated_nickname_chan(name, expected):
    """Colloquial Japanese geminates a stop-ending mora with the following
    ち of ちゃん (sokuon nickname pattern). Engine handles two cases:

    1. Explicit small-tsu in input (いっちゃん): triggered by the small-tsu
       check before the honorific in Pass 2.
    2. Single-kanji + ちゃん where the kanji's reading ends in chi/tsu/ku
       (一ちゃん, 八ちゃん): triggered by the gemination heuristic in Pass 4."""
    assert transliterate(name, "en") == expected


@pytest.mark.parametrize(
    "name, expected",
    [
        # Single-kanji nicknames that DON'T geminate (no chi/tsu/ku ending).
        ("大ちゃん", "Dai-chan"),    # dai → no gemination
        ("美ちゃん", "Bi-chan"),     # bi → no gemination
        ("愛ちゃん", "Ai-chan"),     # ai → no gemination
        ("和ちゃん", "Wa-chan"),     # wa → no gemination
    ],
)
def test_kanji_chan_no_gemination_when_reading_lacks_stop(name, expected):
    """The gemination heuristic only fires for stems whose reading ends in
    chi/tsu/ku. Other kanji+ちゃん nicknames keep the standard literal
    romanization."""
    assert transliterate(name, "en") == expected


def test_geminated_nickname_does_not_affect_simple_honorific():
    """たなかりん has no small-tsu before the honorific, so it should
    still split as 'Tanaka' + '-rin', not collapse to 'Tanakarin'."""
    assert transliterate("たなかりん", "en") == "Tanaka-rin"
    assert transliterate("たなかぼん", "en") == "Tanaka-bon"
