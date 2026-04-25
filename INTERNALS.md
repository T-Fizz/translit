# Engine Internals

A deep dive into how `translit_core` actually works — the wrapper logic, the
edge cases, and the things we deliberately *don't* try to handle. Useful if
you're building something similar, debugging an unexpected output, or just
curious about why CJK transliteration is harder than it looks.

## 1. What "transliteration" is — and isn't

**Transliteration** converts text from one script to another while preserving
*sound*. **Translation** preserves *meaning*.

- `田中 → "Tanaka"` is transliteration. The English reader can pronounce
  Latin letters to approximate the Japanese sound.
- `田中 → "rice paddy middle"` would be a literal *translation* of the kanji
  characters' semantic content. (`田中` is a common Japanese family name, so
  even that translation is wrong in context.)

This distinction matters because en → ja "transliteration" almost always
means **proper nouns and loanwords**: `John → ジョン`, `computer → コンピュータ`.
You don't transliterate full English sentences into Japanese script — that
would be translation, and you'd use a different tool.

## 2. The 100-line wrapper

The actual phonetic conversion is done by two well-maintained Python libs:

| Source | Library | What it does |
|---|---|---|
| Japanese | [`pykakasi`](https://codeberg.org/miurahr/pykakasi) | kana/kanji → romaji |
| Chinese | [`pypinyin`](https://github.com/mozillazg/python-pinyin) | hanzi → pinyin |
| English | [`alkana`](https://github.com/cod-sushi/alkana.py) | English → katakana |

If the libraries already exist, **what does this project add?** Five things:

1. **Honorific detection.** `pykakasi` gives `カナちゃん → "kanachan"`. We
   want `Kana-chan`. The 22-entry honorific table lives in
   [translit_core/engine.py](translit_core/engine.py); we strip a known
   trailing honorific before romanization, then re-attach the roman form
   with a hyphen.
2. **CJK source disambiguation.** `田中` is valid Chinese ("Tian Zhong") and
   valid Japanese ("Tanaka"). The libraries don't know which you meant. Our
   `source_lang` hint routes to `pykakasi` for `ja`, `pypinyin` for `zh`.
3. **Multi-kanji tokenization.** `pykakasi`'s name dictionary recognizes that
   `山田太郎` is `[山田, 太郎]` — family + given. We join with a space:
   `Yamada Taro`. Without that, the default would be `yamadatarou`.
4. **Simplified-Hepburn ("passport") romanization.** More on this below —
   it's the format Japanese passports actually use, and pykakasi exposes it
   as a non-default field.
5. **Routing + fail-soft.** Detect the source script, route to the right
   library, return `None` when we can't do it deterministically. Callers
   build LLM fallbacks on top if they want.

That's the product. The romanization itself is borrowed.

## 3. Discovering passport mode

`pykakasi` exposes multiple romanization styles per token:

```python
{'orig': 'さとう', 'hepburn': 'satou', 'passport': 'sato'}
```

**Hepburn** keeps long-vowel markers (`さとう → satou`). It's the academic
default. **Passport** drops them (`さとう → sato`) — it's modeled on the
romanization Japan's Ministry of Foreign Affairs prescribes for citizens'
names on passport documents. Real-world Japanese names appear in `Passport`
form on business cards, news mastheads, credit cards.

We chose passport for the obvious reason: **a name service should match how
Japanese people actually write their own names in Latin contexts.** Sato
Ichirō puts `Sato Ichiro` on his business card, not `Satō Ichirō`, not
`Satou Ichirou`.

Passport mode also fixes mid-word long vowels for free:

| Input | Hepburn | Passport |
|---|---|---|
| `さとう` (`satō`) | `satou` | `sato` |
| `王明` (read as ja, `Ōmei`) | `oumei` | `omei` |

**But it's not perfectly consistent.** Passport leaves *yōon* (palatalized)
and geminated long vowels un-folded:

| Input | Hepburn | Passport | What we want |
|---|---|---|---|
| `しょう` | `shou` | `shou` | `Sho` |
| `りょう` | `ryou` | `ryou` | `Ryo` |
| `しゅう` | `shuu` | `shuu` | `Shu` |
| `がっこう` | `gakkou` | `gakkou` | `Gakko` |

So we backstop with our own end-of-token `ou → o` / `uu → u` fold. Passport
handles the mid-string cases; our backstop handles the yōon cases.

## 4. Honorifics: the dictionary that compounds

The honorific table is the asset that grows. Real-world names from a
hypothetical bug tracker would each add a row:

```python
("ちゃん", "-chan"), ("さん", "-san"), ("くん", "-kun"), ("さま", "-sama"),
("先生", "-sensei"), ("先輩", "-senpai"),
("にいさん", "-niisan"), ("兄ちゃん", "-niichan"),  # compounds rank above bare さん/ちゃん
("にゃん", "-nyan"), ("ぴょん", "-pyon"), ("きゅん", "-kyun"),  # slang/moe
# ... 22 entries total
```

Three mechanics make it work:

**Longest-suffix-first matching.** Sorted by descending suffix length so
`兄ちゃん` (length 4) matches before `ちゃん` (length 3) on input `田中兄ちゃん`.

**Katakana-to-hiragana folding for matching.** Half/full-width katakana in
the input gets folded to hiragana before suffix comparison, so `カナチャン`
(all katakana) detects the `ちゃん` suffix.

**Exact-match emits the bare honorific.** When the entire input *is* the
honorific compound (`兄ちゃん` alone, with no name), we used to fall through
to the shorter `ちゃん` and emit `Ani-chan` — pykakasi reading `兄` as `Ani`.
That's wrong: the dictionary has the canonical form (`-niichan`). We now
detect `len(stem) == len(suffix)` and return the dict roman form directly:
`Niichan`.

## 5. Multi-kanji tokenization (and where it stops working)

`pykakasi` ships a name dictionary. For common Japanese names, it tokenizes
at the family/given boundary:

```python
>>> k.convert("中村花子")
[{'orig': '中村', 'passport': 'nakamura'},
 {'orig': '花子', 'passport': 'hanako'}]
```

Joining tokens with a space gives `Nakamura Hanako`. Free.

**Where this breaks: pure-kana compound names.** `さとうひろし` (Satō Hiroshi
in hiragana) is one token to pykakasi, because there's no kanji boundary to
split on:

```python
>>> k.convert("さとうひろし")
[{'orig': 'さとうひろし', 'passport': 'satohiroshi'}]
```

We get `Satohiroshi` — long vowel folded correctly, but no space because
there's nothing to split on. Native Japanese readers would also struggle
without context: is it Satō Hiroshi (a person) or some compound word?
Splitting unsegmented kana would need a separate word-boundary detector
(MeCab, Janome, or a name dictionary), and we didn't ship one.

Tracked as a known limit in
[`test_mid_string_long_vowel_folded_in_single_token`](tests/test_ja_romanization.py).

**Where it breaks more silently: rare kanji variants.** Some names use
visually similar but encoded-distinct characters that pykakasi's dictionary
doesn't carry:

| Common form | Variant | What pykakasi does |
|---|---|---|
| `高橋` (Takahashi) | `髙橋` | Returns `髙` with empty reading → we return `None` |
| `吉田` (Yoshida) | `𠮷田` (4-byte 𠮷, U+20BB7) | Silently *drops* `𠮷`, returns just `田` → "Ta" |

The first case is honest: pykakasi knows the codepoint exists but can't
read it; our token filter drops the empty-reading entry, and if no tokens
remain we return `None`. The second case was scarier — pykakasi just
omits the unknown 4-byte kanji from its parts list entirely, so a partial
romanization leaks out as if nothing went wrong.

**Mitigation: a coverage check.** After conversion, we collect every
alphabetic character pykakasi reported in its `orig` fields and verify the
input's alphabetic characters are a subset:

```python
input_alpha = {c for c in stem if c.isalpha()}
covered_alpha = {c for p in parts for c in p["orig"] if c.isalpha()}
if not input_alpha.issubset(covered_alpha):
    return None
```

If `𠮷` was in the input but not in any `orig`, we refuse rather than emit
a misleading partial reading.

## 6. The edge-case bestiary

Things we ran into during testing, and how each is handled.

### Half-width katakana (`ｶﾅちゃん`)

Half-width katakana lives at U+FF65–U+FF9F. Our script-detection ranges
only covered full-width katakana (U+30A0–U+30FF), so half-width input fell
through to "no script detected" and got rejected. The voicing marks are
also separate codepoints (`ｶﾞ` is `ｶ` + `ﾞ`, not the single character `ガ`),
which would have broken honorific suffix matching too.

**Fix: NFKC normalize the input.** One line:

```python
import unicodedata
name = unicodedata.normalize("NFKC", name)
```

`NFKC` is the Unicode "compatibility decomposition + canonical composition"
form. It folds half-width katakana to full-width, full-width Latin
(`Ｊｏｈｎ`) to ASCII (`John`), and combines voiced kana (`ｶﾞ` → `ガ`).
After this normalization, all downstream code can assume canonical forms.

### Full-width Latin (`Ｊｏｈｎ → ジョン`)

Same NFKC fix. Without normalization, full-width Latin codepoints (U+FF21
and up) didn't match our `ord(ch) < 0x0250` ASCII range and were classified
as "no script". After NFKC: clean ASCII, routed to `alkana`, returns `ジョン`.

### Punctuation in input (`田中。`, `「田中」`)

`pykakasi` happily romanizes Japanese punctuation: `。 → "."`, `「 → "("`,
`」 → ")"`. Without intervention you'd get `「田中」 → "( Tanaka )"`. Ugly.

**Fix: strip non-alphabetic input before pykakasi.**

```python
name = "".join(c for c in _normalize(name) if c.isalpha())
```

`isalpha()` is True for all letters (including kanji, kana, Latin) and
False for punctuation, digits, whitespace, emoji. Punctuation and digits
in input are simply dropped before any phonetic work happens.

### The pykakasi whitespace/emoji duplication quirk

`pykakasi` has an unexpected behavior: when the input contains a newline,
tab, or emoji *between* alpha tokens, it duplicates the preceding token in
its parts list:

```python
>>> k.convert("田中\nひろし")
[{'orig': '田中', 'passport': 'tanaka'},
 {'orig': '\n', 'passport': ''},
 {'orig': '田中', 'passport': 'tanaka'},   # ← duplicated
 {'orig': 'ひろし', 'passport': 'hiroshi'}]
```

Without a fix, this leaks as `Tanaka Tanaka Hiroshi`. The same input-strip
that handles punctuation handles this too: stripping `\n`, `\t`, and emoji
before pykakasi sees the input means pykakasi never gets confused.

### Round-trip katakana names (`ヴィクター → ?`)

`ヴィクター` is the Japanese transliteration of "Victor". Going back the
other way, you'd want `Victor`. What we produce is `Buikutaa` — the literal
romanization of the kana symbols, treating `ヴィ` as `bui` and `クター` as
`kutaa`.

This is fundamentally a **lost-information** problem. The kana representation
of "Victor" smudges English phonemes through Japanese phonotactics; the path
back requires knowing it was originally a Western name and reaching into a
Western-name dictionary. We can't reconstruct that from the kana alone.

`xfail`'d as `test_katakana_western_name_round_trip`. Solving it would mean
shipping a reverse loanword dictionary — substantial work for a niche case.

### Acronyms (`FBI → ?`)

`alkana` knows some acronyms (`NASA → ナサ`, `IBM → アイビーエム`) but misses
others (`FBI`, `USA`, `CEO`, `AI`). Real Japanese reads English acronyms
letter-by-letter: `FBI → エフビーアイ` (eff-bii-ai). A 26-entry A–Z mapping
table plus an "is this all-caps?" check would close the gap.

Tracked in `test_acronym_letter_by_letter_fallback`. v1.1 candidate.

### Names with punctuation (`O'Brien`, `Mary-Jane`, `Mr. Smith`)

`alkana` rejects anything with apostrophes, hyphens, or trailing periods —
its dictionary is ASCII-letter-only. We don't preprocess these out, so
`Mr. Smith` returns `None`. A split-and-strip pass before lookup would help
(`"Mr." → "Mr"`, then `Mr → ミスター`, then join).

Tracked in `test_en_with_title_prefix`.

## 7. What you can rely on, what you can't

**Reliable:**
- Common Japanese names (`pykakasi` covers the top several thousand).
- Japanese honorifics from the dictionary (22 entries, longest-match-wins).
- Hiragana, katakana (full-width and half-width), and CJK kanji within the
  Basic Multilingual Plane.
- Common English first/last names and loanwords from `alkana`.
- Multi-word English names with `・` separation.

**Unreliable / refused:**
- Pure-kana compound names won't be word-split (`さとうひろし` stays one word).
- Rare 4-byte kanji return `None` (the coverage check catches silent
  dropouts).
- Rare kanji variants (`髙`, `齋`) usually return `None`; pykakasi can't
  read them.
- Round-trip romanization of katakana loanword names doesn't recover the
  original spelling.
- English acronyms hit/miss based on `alkana`'s dictionary.
- English names with punctuation (`O'Brien`, `Mary-Jane`) miss.

**Out of scope by design:**
- Non-name text (sentences, paragraphs).
- Languages other than ja/zh/en (yet).
- Translation (use Azure or DeepL).

## 8. Why a service at all (over just `pip install pykakasi`)

If your consumer is Python and you only need ja → en, **just install
`pykakasi` directly.** A warm `pykakasi.kakasi().convert()` call is ~3μs;
any HTTP roundtrip to a transliteration service is at least 4 orders of
magnitude slower.

The wrapper in this repo (`translit_core`) adds value over raw `pykakasi` in
exactly the ways listed in §2: honorific handling, source disambiguation,
clean tokenization, fail-soft routing, the simplified-Hepburn (passport)
default. Those are worth importing as a library.

The HTTP service in `app/` adds value over `translit_core` only when:

- Your consumer isn't Python (Node, Go, Swift, Rust).
- Multiple consumers need the same dictionary (one PR updates everyone).
- You eventually want to layer on cross-tenant cache, billing, rate limits.

Otherwise: `pip install -e /path/to/translit` and call the library directly.

## 9. Where to look in the code

| Concern | File / function |
|---|---|
| Script detection | [`translit_core/engine.py:detect_source_script`](translit_core/engine.py) |
| Honorific dictionary | [`translit_core/engine.py:_JA_HONORIFICS_RAW`](translit_core/engine.py) |
| Honorific stripping | [`translit_core/engine.py:_ja_to_romaji`](translit_core/engine.py) (top half) |
| pykakasi → romaji | [`translit_core/engine.py:_ja_to_romaji`](translit_core/engine.py) (bottom half) |
| zh → pinyin | [`translit_core/engine.py:_zh_to_pinyin`](translit_core/engine.py) |
| en → katakana | [`translit_core/engine.py:_en_to_katakana`](translit_core/engine.py) |
| Coverage / silent-dropout check | [`translit_core/engine.py`](translit_core/engine.py) (search for `input_alpha`) |
| Edge-case regression tests | [`tests/test_edge_cases.py`](tests/test_edge_cases.py) |
| Honorific tests | [`tests/test_ja_honorifics.py`](tests/test_ja_honorifics.py) |
| Romanization tests | [`tests/test_ja_romanization.py`](tests/test_ja_romanization.py) |

Total core engine: ~200 lines. The rest of the repo is the optional FastAPI
service, deployment scaffolding, and the test suite.
