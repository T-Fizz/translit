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


# --- reverse-alkana (katakana → English name round-trip) -------------------

_REVERSE_ALKANA: dict[str, str] | None = None


def _build_reverse_alkana() -> dict[str, str]:
    """Build a katakana → English reverse map from alkana's dictionary on
    first use. Multiple English words may map to the same katakana
    (homophones); we pick the alphabetically-first deterministically."""
    global _REVERSE_ALKANA
    if _REVERSE_ALKANA is not None:
        return _REVERSE_ALKANA
    try:
        import alkana
    except ImportError:
        _REVERSE_ALKANA = {}
        return _REVERSE_ALKANA
    rev: dict[str, str] = {}
    for eng, kata in alkana.data.data.items():
        if kata not in rev or eng < rev[kata]:
            rev[kata] = eng
    _REVERSE_ALKANA = rev
    return rev


def _katakana_to_western(name: str) -> str | None:
    """Look up an all-katakana name in reverse-alkana to recover the
    original Western spelling (ヴィクター → 'Victor'). All-or-nothing
    across ・-separated tokens."""
    rev = _build_reverse_alkana()
    parts = [p for p in name.split("・") if p]
    if not parts:
        return None
    out: list[str] = []
    for p in parts:
        # Strip any non-katakana noise within a piece before lookup
        clean = "".join(c for c in p if 0x30A0 <= ord(c) <= 0x30FF)
        if not clean:
            return None
        eng = rev.get(clean)
        if eng is None:
            return None
        out.append(eng.title())
    return " ".join(out)


def _is_all_katakana(s: str) -> bool:
    """True if every alphabetic character in `s` is katakana (incl. ー
    prolong mark and ・ middle dot). Non-alpha noise is skipped."""
    seen = False
    for c in s:
        if 0x30A0 <= ord(c) <= 0x30FF:
            seen = True
            continue
        if c.isalpha():
            return False  # a non-katakana letter (kanji, hiragana, latin)
    return seen


# --- en → katakana fallbacks (acronyms, punctuation handling) --------------

_LETTER_TO_KATAKANA = {
    "a": "エー", "b": "ビー", "c": "シー", "d": "ディー", "e": "イー",
    "f": "エフ", "g": "ジー", "h": "エイチ", "i": "アイ", "j": "ジェイ",
    "k": "ケー", "l": "エル", "m": "エム", "n": "エヌ", "o": "オー",
    "p": "ピー", "q": "キュー", "r": "アール", "s": "エス", "t": "ティー",
    "u": "ユー", "v": "ブイ", "w": "ダブリュー", "x": "エックス", "y": "ワイ",
    "z": "ゼット",
}


def _en_acronym_to_katakana(word: str) -> str | None:
    """Letter-by-letter katakana for ASCII uppercase acronyms (FBI →
    エフビーアイ). Real Japanese reads English acronyms by letter name.
    Activated only when alkana misses AND input is 2+ uppercase letters."""
    if len(word) < 2 or not word.isupper():
        return None
    if not all(c.isascii() and c.isalpha() for c in word):
        return None
    return "".join(_LETTER_TO_KATAKANA[c.lower()] for c in word)


def _alkana_lookup(word: str) -> str | None:
    """Look up an English word in alkana with progressive cleanup.

    Tries: exact match → trailing-punctuation-stripped → acronym fallback.
    """
    try:
        import alkana
    except ImportError:
        return None
    result = alkana.get_kana(word)
    if result is not None:
        return result
    cleaned = word.rstrip(".,;:!?")
    if cleaned and cleaned != word:
        result = alkana.get_kana(cleaned)
        if result is not None:
            return result
        word = cleaned
    return _en_acronym_to_katakana(word)


# --- romanizers -------------------------------------------------------------

def _ja_to_romaji(
    name: str,
    caller_hinted_ja: bool = False,
    name_order: str = "family-first",
) -> str | None:
    try:
        import pykakasi
    except ImportError:
        return None

    # Strip non-alphabetic chars before honorific detection / pykakasi.
    # We keep ・ (foreign-name separator) so multi-word katakana names like
    # ジョン・スミス can round-trip through reverse-alkana below.
    name = "".join(c for c in _normalize(name) if c.isalpha() or c == "・")
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

    # Round-trip path: if the stem is pure katakana (with optional ・ or ー),
    # try recovering the original Western spelling from reverse-alkana
    # before falling back to pykakasi's literal kana romanization.
    # ヴィクター → 'Victor' (good) vs pykakasi's 'Buikutaa' (bad).
    #
    # Skipped when the caller hinted source_lang='ja' — they're asserting this
    # is a Japanese name, so we should NOT second-guess as a Western loanword.
    # Many common JA names happen to phonetically match English words via the
    # reverse map (タロウ→Tallow, レン→Len, ゼン→Then, ノブ→Knob, ハル→Hal, ケイ→Kay).
    if not caller_hinted_ja and _is_all_katakana(stem):
        western = _katakana_to_western(stem)
        if western is not None:
            return western + honorific_roman

    # ・ was only relevant for the reverse-alkana split — pykakasi doesn't
    # know what to do with it.
    stem = stem.replace("・", "")
    if not stem:
        return None

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
    # Family-first is the modern Japanese government convention (formally
    # adopted 2019) and our default. Older Western-facing contexts often
    # expect given-first; swap when there's a clean 2-token boundary
    # (山田太郎 → [yamada, taro] → "Taro Yamada"). Names pykakasi can't
    # tokenize (single-token kana, single kanji block) can't be swapped.
    if name_order == "given-first" and len(tokens) == 2:
        tokens = [tokens[1], tokens[0]]
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
    """English (Latin script) → katakana.

    Pipeline per word: alkana → trailing-punctuation strip and retry →
    A–Z acronym fallback. Hyphenated names split into pieces and look up
    each. All-or-nothing: any miss returns None for the whole input.
    Output joins pieces with '・' (foreign-name separator).
    """
    parts = name.strip().split()
    if not parts:
        return None
    expanded: list[str] = []
    for p in parts:
        # Hyphenated names split at hyphens (Mary-Jane → ['Mary', 'Jane']).
        for sub in p.split("-"):
            if sub:
                expanded.append(sub)
    katas = [_alkana_lookup(p) for p in expanded]
    if any(k is None for k in katas):
        return None
    return "・".join(katas)


# --- public API -------------------------------------------------------------

def transliterate(
    name: str,
    target_lang: str,
    source_lang: str | None = None,
    name_order: str = "family-first",
) -> str | None:
    """Return a transliteration of `name` in the native script of `target_lang`.

    `source_lang` disambiguates pure-kanji names (田中 → Tanaka if ja, Tian Zhong if zh).

    `name_order` controls family/given output for Japanese names:
      - "family-first" (default): 山田太郎 → "Yamada Taro" (modern JA convention)
      - "given-first":             山田太郎 → "Taro Yamada" (older Western-facing)
    Only takes effect when pykakasi tokenizes the name into exactly two parts;
    single-token output (single kanji block, pure kana names) emits unchanged.

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
        return _ja_to_romaji(
            name,
            caller_hinted_ja=(source_lang == "ja"),
            name_order=name_order,
        )
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
