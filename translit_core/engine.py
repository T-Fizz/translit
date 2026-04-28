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


# --- ru → latin (BGN/PCGN-style, name-friendly) ----------------------------

# Press-friendly BGN/PCGN-style Cyrillic → Latin map. The standard library
# alternatives (`transliterate`, `cyrtranslit`) lean scientific/GOST and
# emit `j` for й, `h` for х, drop the y-glide on ё (Fedor instead of Fyodor),
# and keep apostrophes for soft/hard signs. None of those match how Russian
# names appear in English-language press, sports, or visa contexts. This
# table is what newspapers actually print: Mikhail not Mihail, Akhmatova
# not Ahmatova, Fyodor not Fedor, Olga not Ol'ga.
_RU_MAP = {
    "А": "A",  "Б": "B",  "В": "V",  "Г": "G",  "Д": "D",
    "Е": "E",  "Ё": "Yo", "Ж": "Zh", "З": "Z",  "И": "I",
    "Й": "Y",  "К": "K",  "Л": "L",  "М": "M",  "Н": "N",
    "О": "O",  "П": "P",  "Р": "R",  "С": "S",  "Т": "T",
    "У": "U",  "Ф": "F",  "Х": "Kh", "Ц": "Ts", "Ч": "Ch",
    "Ш": "Sh", "Щ": "Shch", "Ъ": "", "Ы": "Y",  "Ь": "",
    "Э": "E",  "Ю": "Yu", "Я": "Ya",
    "а": "a",  "б": "b",  "в": "v",  "г": "g",  "д": "d",
    "е": "e",  "ё": "yo", "ж": "zh", "з": "z",  "и": "i",
    "й": "y",  "к": "k",  "л": "l",  "м": "m",  "н": "n",
    "о": "o",  "п": "p",  "р": "r",  "с": "s",  "т": "t",
    "у": "u",  "ф": "f",  "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ъ": "", "ы": "y",  "ь": "",
    "э": "e",  "ю": "yu", "я": "ya",
}


# Digraph fixups for ъ/ь + е — press writes 'ye' here even though strict
# single-char drop-the-sign + е would give just 'e' (Yuryevich vs Yurevich,
# Obyekt vs Obekt). ъё/ьё/ъя/ьа/ъю/ьу already work via single-char rules
# because ё/я/ю already start with y.
_RU_DIGRAPHS = {
    "ъе": "ye", "Ъе": "Ye", "ъЕ": "yE", "ЪЕ": "YE",
    "ье": "ye", "Ье": "Ye", "ьЕ": "yE", "ЬЕ": "YE",
}


def _ru_to_latin(name: str) -> str | None:
    """Russian (Cyrillic) → Latin via press-friendly BGN/PCGN.

    Internal whitespace and hyphens preserved. Non-Cyrillic letters
    (e.g., Ukrainian Ї) cause a refusal — we don't transliterate
    near-Cyrillic alphabets we haven't tabled. Digits / punctuation
    are stripped (parallel to the JA path)."""
    out: list[str] = []
    i = 0
    while i < len(name):
        c = name[i]
        # 2-char digraph (ъе/ье → ye) takes precedence over single-char drop
        if i + 1 < len(name):
            digraph = c + name[i + 1]
            if digraph in _RU_DIGRAPHS:
                out.append(_RU_DIGRAPHS[digraph])
                i += 2
                continue
        roman = _RU_MAP.get(c)
        if roman is not None:
            out.append(roman)
        elif c.isspace():
            out.append(" ")
        elif c == "-":
            out.append("-")
        elif c.isalpha():
            return None  # non-Cyrillic letter — refuse rather than mix
        # else: drop digits / punctuation
        i += 1
    text = "".join(out)
    if not text.strip():
        return None
    # Title-case each whitespace-split token; .title() handles internal
    # hyphens (Иван-Петров → Ivan-Petrov, not Ivan-petrov).
    return " ".join(t.title() for t in text.split())


# --- hi → latin (IAST via indic-transliteration + press-style fixups) -----

# IAST → press-style ASCII mapping. The `indic-transliteration` lib emits
# scholarly IAST with macrons (ā/ī/ū) and underdots (ṃ/ṛ/ṣ/ṇ); press writes
# names without these (Rama, Krishna, Anjali — not Rāma, Kṛṣṇa, Aṃjalī).
_IAST_TO_PRESS = {
    # long vowels — drop the macron
    "ā": "a", "ī": "i", "ū": "u", "ē": "e", "ō": "o",
    # nasals → n
    "ṃ": "n", "ṁ": "n", "ṅ": "n", "ñ": "n", "ṇ": "n",
    # vocalic r/l → ri/li (Krishna, not Kṛṣṇa)
    "ṛ": "ri", "ṝ": "ri", "ḷ": "li", "ḹ": "li",
    # retroflex stops collapse to plain stops
    "ṭ": "t", "ḍ": "d",
    # visarga at end usually dropped in press
    "ḥ": "",
    # sibilants → sh (both palatal ś and retroflex ṣ)
    "ś": "sh", "ṣ": "sh",
    # IAST 'c' is the palatal stop /tʃ/ — written 'ch' in English press
    # (Bachchan, Chandra, Charan). Applied last via the same .replace().
    "c": "ch",
}

# Aspirated stops in IAST: paired consonant + 'h' representing one phoneme.
# We don't want the schwa-delete cluster check to mistake them for two
# consonants (otherwise अमिताभ → Amitabha instead of Amitabh).
_IAST_ASPIRATE_FIRSTS = set("bdgjkptcḍṭ")


def _hi_to_latin(name: str) -> str | None:
    """Hindi (Devanagari) → Latin via IAST + press-style fixups.

    Pipeline:
      1. Run input through `indic_transliteration` to get IAST.
      2. Replace IAST diacritics with their press-style ASCII equivalents.
      3. Schwa-delete: drop word-final 'a' if preceded by exactly one
         consonant (`rama → ram`, `raja → raj`). Keep 'a' after a
         consonant cluster (`krishna` not `krishn`, `narendra` not
         `narendr`) — the cluster signals the inherent vowel is
         pronounced.
      4. Title-case per word.
    """
    try:
        from indic_transliteration import sanscript
    except ImportError:
        return None
    if not name.strip():
        return None
    # Strip non-Devanagari, non-whitespace before the library sees the input.
    # Otherwise punctuation (!, ., ।) and digits leak straight through to
    # the IAST output (`राम! → 'rāma!'`).
    cleaned = "".join(
        c for c in name
        if (0x0900 <= ord(c) <= 0x097F and not 0x0964 <= ord(c) <= 0x096F)
        or c.isspace()
    )
    if not cleaned.strip():
        return None
    iast = sanscript.transliterate(cleaned, sanscript.DEVANAGARI, sanscript.IAST)
    if not iast.strip():
        return None
    # Schwa-delete BEFORE diacritic stripping so we can distinguish the
    # inherent vowel 'a' from the explicit long vowel 'ā'. After macron
    # drop they'd look identical, but only the short 'a' (inherent schwa)
    # gets deleted in modern Hindi pronunciation — सुनीता ends in long ā
    # and stays as 'Sunita', not 'Sunit'.
    iast_vowels = set("aeiouāīūēōṛṝḷḹ")
    schwa_dropped: list[str] = []
    for word in iast.split():
        if len(word) >= 3 and word[-1] == "a":
            prev = word[-2]
            if prev not in iast_vowels:  # consonant before short final 'a'
                # If 'h' is part of an aspirated digraph (bh/dh/gh/jh/etc.),
                # treat the digraph as a single consonant unit when looking
                # for clusters (otherwise अमिताभ → Amitabha not Amitabh).
                aspirated = (
                    prev == "h"
                    and len(word) >= 3
                    and word[-3] in _IAST_ASPIRATE_FIRSTS
                )
                cluster_check_idx = -4 if aspirated else -3
                is_cluster = (
                    len(word) >= -cluster_check_idx + 1
                    and word[cluster_check_idx] not in iast_vowels
                )
                if not is_cluster:
                    word = word[:-1]
        if word:
            schwa_dropped.append(word)
    if not schwa_dropped:
        return None
    # Diacritic → press ASCII
    text = " ".join(schwa_dropped)
    for k, v in _IAST_TO_PRESS.items():
        text = text.replace(k, v)
    return " ".join(t.title() for t in text.split() if t)


# --- ar → latin (curated name overlay) -------------------------------------

# Arabic diacritics (tashkeel) we strip before dictionary lookup.
# Modern Arabic text rarely includes these except in religious/formal
# contexts; our dict keys are stored without them.
_AR_TASHKEEL = "".join(chr(c) for c in range(0x064B, 0x0653)) + "ٰ"

# Alif/ya/ta variants normalized to canonical forms before lookup.
_AR_NORMALIZE = {
    "أ": "ا", "إ": "ا", "آ": "ا",  # hamza-bearing alifs → plain alif
    "ى": "ي",                        # alef maksura → ya
    "ـ": "",                         # tatweel (kashida) — visual stretch
}


def _ar_normalize_for_lookup(s: str) -> str:
    """NFKC-normalize, strip tashkeel, fold alif/ya variants. Output is
    the canonical form used as keys in `_AR_NAME_OVERLAY`."""
    s = _normalize(s)  # NFKC handles the Allah ligature ﷲ → الله, etc.
    s = "".join(c for c in s if c not in _AR_TASHKEEL)
    for src, dst in _AR_NORMALIZE.items():
        s = s.replace(src, dst)
    return s


# Common Arabic names with their established press / English-language
# spellings. This is intentionally a curated overlay, not a derivation —
# Arabic without short vowels (the normal written form) is fundamentally
# under-determined for romanization. ~50 entries cover the most-encountered
# Arabic names in English-language press.
#
# Keys are stored in normalized form (no tashkeel, plain alif). The
# normalizer applied at lookup time matches input to keys.
_AR_NAME_OVERLAY_RAW = {
    # Male given names
    "محمد": "Muhammad",
    "احمد": "Ahmad",
    "علي": "Ali",
    "عمر": "Omar",
    "حسن": "Hassan",
    "حسين": "Hussein",
    "خالد": "Khalid",
    "صالح": "Saleh",
    "ابراهيم": "Ibrahim",
    "يوسف": "Yusuf",
    "سلمان": "Salman",
    "محمود": "Mahmoud",
    "كريم": "Karim",
    "سامي": "Sami",
    "رشيد": "Rashid",
    "جمال": "Jamal",
    "بلال": "Bilal",
    "حمزة": "Hamza",
    "زياد": "Ziyad",
    "طارق": "Tariq",
    "فيصل": "Faisal",
    "هاني": "Hani",
    "وليد": "Walid",
    "ياسر": "Yasser",
    "زين": "Zain",
    "سعيد": "Saeed",
    # Female given names
    "فاطمة": "Fatima",
    "عائشة": "Aisha",
    "خديجة": "Khadija",
    "مريم": "Mariam",
    "ليلى": "Layla",
    "سارة": "Sara",
    "نور": "Nour",
    "زينب": "Zaynab",
    "ياسمين": "Yasmin",
    "امينة": "Amina",
    "سلمى": "Salma",
    "نادية": "Nadia",
    "هدى": "Huda",
    "رنا": "Rana",
    "هبة": "Heba",
    "اسماء": "Asma",
    # Compound (multi-token) — must out-rank per-word lookup
    "عبد الله": "Abdullah",
    "عبد الرحمن": "Abdul-Rahman",
    "عبد العزيز": "Abdul-Aziz",
    "عبد الكريم": "Abdul-Karim",
    "عبد الرحيم": "Abdul-Rahim",
    "ابو بكر": "Abu Bakr",
    "ام كلثوم": "Umm Kulthum",
}

# Pre-normalize the dict keys so input normalization (which folds maksura
# ى → ya ي, hamza-bearing alifs → plain alif, etc.) lands on the same
# canonical key regardless of which spelling was authored above.
_AR_NAME_OVERLAY = {
    _ar_normalize_for_lookup(k): v for k, v in _AR_NAME_OVERLAY_RAW.items()
}


def _ar_to_latin(name: str) -> str | None:
    """Arabic → Latin via curated name overlay.

    Arabic written without short vowels (the normal form) can't be
    romanized deterministically from rules — there's no way to know
    whether m-h-m-d should be "Muhammad", "Mohammed", or something else.
    So this is a dictionary lookup against ~50 curated common names.
    Inputs not in the dictionary return None (fail-soft).

    The full-input is tried first so multi-token compounds like
    'عبد الله' → 'Abdullah' beat the per-word fallback.
    """
    cleaned = _ar_normalize_for_lookup(name).strip()
    if not cleaned:
        return None
    # Whole-input lookup catches compounds.
    full = _AR_NAME_OVERLAY.get(cleaned)
    if full is not None:
        return full
    # Per-word lookup, all-or-nothing.
    words = cleaned.split()
    out: list[str] = []
    for w in words:
        roman = _AR_NAME_OVERLAY.get(w)
        if roman is None:
            return None
        out.append(roman)
    return " ".join(out) if out else None


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


# --- ko → roman (Revised Romanization + traditional surname overlay) -------

_HANGUL_BASE = 0xAC00
_HANGUL_END = 0xD7A3

# 19 initials (consonants in onset position). RR initial-position values.
# ㄹ → 'r' here even though final ㄹ → 'l'.
_RR_INITIALS = (
    "g", "kk", "n", "d", "tt", "r", "m", "b", "pp",
    "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h",
)

# 21 vowels (medials).
_RR_VOWELS = (
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae",
    "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i",
)

# 28 finals (codas) at pause / end-of-syllable. RR official forms — stops
# realize as their unreleased equivalents (ㄱ→k, ㅂ→p, ㄷ/ㅅ/ㅈ/ㅊ/ㅌ→t).
# Cluster finals collapse to a single representative consonant (per RR).
_RR_FINALS = (
    "",   "k",  "kk", "k",  "n",  "n",  "n",  "t",  "l",  "k",
    "m",  "p",  "l",  "l",  "p",  "l",  "m",  "p",  "p",  "t",
    "t",  "ng", "t",  "t",  "k",  "t",  "p",  "t",
)

# Korean honorifics. Same longest-match-first pattern as the JA dict —
# 선생님 (3 syllables) must out-rank 님 (1 syllable).
_KO_HONORIFICS_RAW = [
    ("선생님", "-seonsaengnim"),
    ("씨", "-ssi"),
    ("님", "-nim"),
]
_KO_HONORIFICS = sorted(_KO_HONORIFICS_RAW, key=lambda x: -len(x[0]))


# Traditional Western-friendly surname spellings — what people actually
# put on their passports and business cards. RR would say "Gim/I/Bak/Choe"
# but every newspaper, sports broadcast, and visa form uses these forms.
# Sources: top-30 Korean surnames by population, with their established
# Latin spellings as documented across English-language media.
_KO_SURNAME_OVERLAY = {
    "김": "Kim",
    "이": "Lee",
    "박": "Park",
    "최": "Choi",
    "정": "Jung",
    "강": "Kang",
    "조": "Cho",
    "윤": "Yoon",
    "장": "Jang",
    "임": "Lim",
    "한": "Han",
    "오": "Oh",
    "서": "Seo",
    "신": "Shin",
    "권": "Kwon",
    "황": "Hwang",
    "안": "Ahn",
    "송": "Song",
    "전": "Jeon",
    "홍": "Hong",
    "유": "Yoo",
    "고": "Ko",
    "문": "Moon",
    "양": "Yang",
    "손": "Son",
    "배": "Bae",
    "백": "Baek",
    "허": "Heo",
    "남": "Nam",
    "심": "Shim",
    "노": "Noh",
    "하": "Ha",
    "주": "Joo",
    "류": "Ryu",
    # Common 2-syllable family names — kept as keys so we detect a
    # 2-syllable family at the head of an input.
    "남궁": "Namgoong",
    "황보": "Hwangbo",
    "사공": "Sagong",
    "제갈": "Jegal",
    "선우": "Sunwoo",
    "독고": "Dokgo",
}


def _ko_syllable_to_roman(c: str) -> str:
    """Romanize one Hangul syllable per Revised Romanization.

    No sandhi: each syllable is treated atomically, suitable for hyphen-
    joined names like 'Jeong-eun' where each piece stands alone.
    """
    code = ord(c)
    if not (_HANGUL_BASE <= code <= _HANGUL_END):
        return ""
    idx = code - _HANGUL_BASE
    initial = idx // 588
    vowel = (idx % 588) // 28
    final = idx % 28
    return _RR_INITIALS[initial] + _RR_VOWELS[vowel] + _RR_FINALS[final]


def _ko_to_roman(name: str, name_order: str = "family-first") -> str | None:
    """Korean (Hangul) → Latin via Revised Romanization + traditional
    surname overlay.

    Pipeline:
      1. Strip non-Hangul.
      2. Detect family name boundary: if the first 2 syllables are a known
         2-syllable surname (남궁, 황보, …), treat them as the family.
         Otherwise the first 1 syllable is the family.
      3. Family name: look up in the traditional-spelling overlay (Kim/
         Lee/Park/…). If unknown, fall back to RR per syllable.
      4. Given name: RR per syllable, hyphen-joined and capitalized
         (정은 → 'Jeong-Un').
      5. Output: 'Family Given-Name', or 'Given-Name Family' if
         name_order='given-first'.
    """
    syllables = [c for c in name if _HANGUL_BASE <= ord(c) <= _HANGUL_END]
    if not syllables:
        return None

    # Honorific stripping (parallel to the JA path). Longest suffix wins so
    # 선생님 outranks 님; the bare-honorific guard prevents stripping 씨
    # alone (which falls through to a normal RR romanization).
    honorific_roman = ""
    hangul_str = "".join(syllables)
    for suffix, roman in _KO_HONORIFICS:
        if hangul_str.endswith(suffix) and len(hangul_str) > len(suffix):
            hangul_str = hangul_str[: -len(suffix)]
            honorific_roman = roman
            break
    syllables = list(hangul_str)
    if not syllables:
        return None

    # Two-syllable family detection: longest-match-wins. If the first 2
    # syllables are a known 2-syllable family name (남궁, 황보, …), treat
    # them as the family — even if there's no given-name remainder.
    family_len = 1
    if len(syllables) >= 2:
        head2 = "".join(syllables[:2])
        if head2 in _KO_SURNAME_OVERLAY:
            family_len = 2

    family_chars = "".join(syllables[:family_len])
    given_chars = syllables[family_len:]

    # Family name: overlay first, RR fallback
    family = _KO_SURNAME_OVERLAY.get(family_chars)
    if family is None:
        family_roman = "".join(_ko_syllable_to_roman(c) for c in family_chars)
        if not family_roman:
            return None
        family = family_roman.capitalize()

    if not given_chars:
        return family + honorific_roman  # single-syllable input is just the family

    given_pieces = [_ko_syllable_to_roman(c) for c in given_chars]
    if any(not p for p in given_pieces):
        return None
    # Press convention for Korean given names: capitalize only the first
    # syllable, lowercase the rest (Lee Min-ho, Kim Jong-un, Park Geun-hye).
    given = given_pieces[0].capitalize() + (
        "-" + "-".join(given_pieces[1:]) if len(given_pieces) > 1 else ""
    )

    if name_order == "given-first":
        return f"{given} {family}" + honorific_roman
    return f"{family} {given}" + honorific_roman


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
    if src == "ko":
        return _ko_to_roman(name, name_order=name_order)
    if src == "ru":
        return _ru_to_latin(name)
    if src == "hi":
        return _hi_to_latin(name)
    if src == "ar":
        return _ar_to_latin(name)
    return None


def supported_pairs() -> list[dict]:
    """What (source_script, target_lang) combinations this service handles deterministically."""
    return [
        {"source": "ja", "target": "latin", "method": "pykakasi+passport+honorifics"},
        {"source": "zh", "target": "latin", "method": "pypinyin (no tones)"},
        {"source": "ko", "target": "latin", "method": "RR+traditional-surname-overlay"},
        {"source": "ru", "target": "latin", "method": "BGN/PCGN press-style"},
        {"source": "hi", "target": "latin", "method": "IAST + press-style schwa-deletion"},
        {"source": "ar", "target": "latin", "method": "curated-name-overlay (~50 entries)"},
        {"source": "en", "target": "ja", "method": "alkana"},
    ]
