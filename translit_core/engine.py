"""
Deterministic transliteration for common source scripts.

Currently supports:
    ja → latin (Hepburn romaji via pykakasi, with honorific-aware hyphens)
    zh → latin (pinyin without tone marks via pypinyin)

Non-covered pairs (ko, ar, hi, ru, th → latin, and latin → non-latin) return
None so the caller can decide whether to fall back to an LLM or surface the
original name.
"""
from __future__ import annotations

import unicodedata


def _normalize(s: str) -> str:
    """NFKC-normalize input — folds half-width katakana to full-width
    (ｶﾅ → カナ), full-width Latin to ASCII (Ｊｏｈｎ → John), and standardizes
    voiced kana (ｶ + ﾞ → ガ). Lets all downstream code assume canonical
    forms without touching half-width edge cases."""
    return unicodedata.normalize("NFKC", s)


# --- script detection -------------------------------------------------------

_HIRAGANA = (0x3040, 0x309F)
_KATAKANA = (0x30A0, 0x30FF)
_CJK = (0x4E00, 0x9FFF)
_HANGUL = (0xAC00, 0xD7AF)
_CYRILLIC = (0x0400, 0x04FF)
_THAI = (0x0E00, 0x0E7F)
_ARABIC = (0x0600, 0x06FF)
_DEVANAGARI = (0x0900, 0x097F)

_LATIN_TARGETS = {"en", "es", "fr", "de", "it", "pt", "nl", "sv", "pl", "tr", "vi", "id", "tl"}


def _in(ch: str, lo: int, hi: int) -> bool:
    return lo <= ord(ch) <= hi


def detect_source_script(name: str) -> str | None:
    counts = {"ja": 0, "zh": 0, "ko": 0, "ru": 0, "th": 0, "ar": 0, "hi": 0, "latin": 0}
    total = 0
    has_kana = False
    has_cjk = False
    for ch in _normalize(name):
        if not ch.isalpha():
            continue
        total += 1
        if _in(ch, *_HIRAGANA) or _in(ch, *_KATAKANA):
            has_kana = True
            counts["ja"] += 1
        elif _in(ch, *_CJK):
            has_cjk = True
            counts["zh"] += 1
        elif _in(ch, *_HANGUL):
            counts["ko"] += 1
        elif _in(ch, *_CYRILLIC):
            counts["ru"] += 1
        elif _in(ch, *_THAI):
            counts["th"] += 1
        elif _in(ch, *_ARABIC):
            counts["ar"] += 1
        elif _in(ch, *_DEVANAGARI):
            counts["hi"] += 1
        elif ord(ch) < 0x0250:
            counts["latin"] += 1
    if total == 0:
        return None
    if has_kana and has_cjk:
        return "ja"
    best = max(counts.items(), key=lambda kv: kv[1])
    if best[1] / total < 0.5:
        return None
    return best[0]


# --- Japanese honorifics ----------------------------------------------------

_JA_HONORIFICS_RAW = [
    # Formal / standard
    ("せんぱい", "-senpai"), ("先輩", "-senpai"),
    ("こうはい", "-kouhai"), ("後輩", "-kouhai"),
    ("せんせい", "-sensei"), ("先生", "-sensei"),
    ("はかせ", "-hakase"),   ("博士", "-hakase"),
    ("ちゃん", "-chan"),
    ("さん", "-san"),
    ("くん", "-kun"),
    ("さま", "-sama"),       ("様", "-sama"),
    ("どの", "-dono"),       ("殿", "-dono"),

    # Family compounds — must out-rank bare さん/さま (longest-first sort does this)
    ("にいさん", "-niisan"), ("兄さん", "-niisan"),
    ("にいちゃん", "-niichan"), ("兄ちゃん", "-niichan"),
    ("ねえさん", "-neesan"), ("姉さん", "-neesan"),
    ("ねえちゃん", "-neechan"), ("姉ちゃん", "-neechan"),

    # Slang / moe
    ("っち", "-cchi"), ("にゃん", "-nyan"), ("ぴょん", "-pyon"),
    ("きゅん", "-kyun"), ("たん", "-tan"), ("ちん", "-chin"),
    ("ぽん", "-pon"), ("りん", "-rin"), ("ぼん", "-bon"),
]
_JA_HONORIFICS = sorted(_JA_HONORIFICS_RAW, key=lambda x: -len(x[0]))


def _katakana_to_hiragana(s: str) -> str:
    """Fold katakana → hiragana for loose suffix matching (リん matches りん)."""
    return "".join(
        chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c
        for c in s
    )


# --- romanizers -------------------------------------------------------------

def _ja_to_romaji(name: str) -> str | None:
    try:
        import pykakasi
    except ImportError:
        return None

    # Strip non-alphabetic chars (punctuation, digits, emoji, whitespace)
    # before honorific detection or pykakasi sees the input. pykakasi has a
    # quirk where whitespace/emoji tokens cause it to duplicate adjacent
    # alpha tokens; removing those characters sidesteps the issue and also
    # means we don't have to filter punctuation from output. Spaces in the
    # output come from pykakasi's own morpheme boundaries.
    name = "".join(c for c in _normalize(name) if c.isalpha())
    if not name:
        return None
    honorific_roman = ""
    stem = name
    tail_hira = _katakana_to_hiragana(name)
    for suffix, roman in _JA_HONORIFICS:
        sfx_hira = _katakana_to_hiragana(suffix)
        if not tail_hira.endswith(sfx_hira):
            continue
        if len(stem) == len(suffix):
            # Whole input is the honorific/compound term — use its roman form
            # directly (no stem, no leading hyphen).
            return roman.lstrip("-").capitalize()
        if len(stem) > len(suffix):
            stem = stem[:-len(suffix)]
            honorific_roman = roman
            break

    # 'passport' is pykakasi's simplified-Hepburn field, modeled on the
    # romanization Japanese passports use. It handles most mid-word long
    # vowels (satou→sato, oumei→omei) but inconsistently on yōon and
    # geminated forms (shou/ryou/shuu/yuu/gakkou stay un-folded). We layer
    # an end-of-token fold on top so those cases round out to simplified.
    # Tokens are joined with spaces so multi-kanji names split at
    # pykakasi's morpheme boundaries (山田太郎 → "Yamada Taro").
    k = pykakasi.kakasi()
    parts = k.convert(stem)
    # Coverage check: every alphabetic character in the input must show up
    # in pykakasi's `orig` output. Catches silent dropout of unknown kanji
    # (e.g. 𠮷 in 𠮷田 — the 𠮷 disappears entirely from the parts list).
    # Set-based comparison so we tolerate pykakasi's habit of duplicating
    # tokens around whitespace/emoji.
    input_alpha = {c for c in stem if c.isalpha()}
    covered_alpha = {c for p in parts for c in p["orig"] if c.isalpha()}
    if not input_alpha.issubset(covered_alpha):
        return None
    tokens: list[str] = []
    for p in parts:
        t = p["passport"]
        if not t.strip():
            continue
        # Drop pykakasi-emitted punctuation/digits — they aren't part of
        # the name (e.g. 「田中」 would otherwise come back as "( Tanaka )").
        if not any(c.isalpha() for c in p["orig"]):
            continue
        if t.endswith("ou"):
            t = t[:-2] + "o"
        elif t.endswith("uu"):
            t = t[:-2] + "u"
        tokens.append(t)
    if not tokens:
        return None
    return " ".join(t.capitalize() for t in tokens) + honorific_roman


def _zh_to_pinyin(name: str) -> str | None:
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return None
    words = lazy_pinyin(name)
    if not words:
        return None
    return " ".join(w.capitalize() for w in words if w)


def _en_to_katakana(name: str) -> str | None:
    """English (Latin script) → katakana via the alkana dictionary.

    All-or-nothing: if any whitespace-split word misses the dict, return
    None rather than a partially-romanized garble. Words are joined with
    '・' (Japanese full-width middle dot), the conventional separator for
    foreign personal names (ジョン・スミス).
    """
    try:
        import alkana
    except ImportError:
        return None
    parts = name.strip().split()
    if not parts:
        return None
    katas = [alkana.get_kana(p) for p in parts]
    if any(k is None for k in katas):
        return None
    return "・".join(katas)


# --- public API -------------------------------------------------------------

def transliterate(name: str, target_lang: str, source_lang: str | None = None) -> str | None:
    """Return a transliteration of `name` in the native script of `target_lang`.

    `source_lang` disambiguates pure-kanji names (田中 → Tanaka if ja, Tian Zhong if zh).
    Returns None when the pair isn't supported deterministically.
    """
    if not name:
        return None
    name = _normalize(name)
    src = detect_source_script(name)
    if src is None:
        return None

    # Caller hint wins for CJK ambiguity.
    if source_lang == "ja" and src == "zh":
        src = "ja"
    elif source_lang == "zh" and src == "ja":
        src = "zh"

    # en (Latin script) → ja (katakana) — alkana lookup
    if src == "latin" and target_lang == "ja":
        return _en_to_katakana(name)
    if src == "latin":
        return None  # Latin → Latin isn't transliteration

    if target_lang not in _LATIN_TARGETS:
        return None
    if src == "ja":
        return _ja_to_romaji(name)
    if src == "zh":
        return _zh_to_pinyin(name)
    return None


def supported_pairs() -> list[dict]:
    """What (source_script, target_lang) combinations this service handles deterministically."""
    return [
        {"source": "ja", "target": "latin", "method": "pykakasi+passport+honorifics"},
        {"source": "zh", "target": "latin", "method": "pypinyin (no tones)"},
        {"source": "en", "target": "ja", "method": "alkana"},
    ]
