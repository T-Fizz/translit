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

The actual phonetic conversion is done by Python libraries (where they
exist with the right semantics) and a few small in-repo tables (where a
library would have been a bad fit):

| Source | Provider | What it does |
|---|---|---|
| Japanese | [`pykakasi`](https://codeberg.org/miurahr/pykakasi) | kana/kanji → romaji |
| Chinese | [`pypinyin`](https://github.com/mozillazg/python-pinyin) | hanzi → pinyin |
| English | [`alkana`](https://github.com/cod-sushi/alkana.py) | English → katakana |
| Korean | in-repo: Hangul codepoint decomposition + RR table | Hangul → roman |

If the libraries already exist, **what does this project add?** Five things:

1. **Honorific detection.** `pykakasi` gives `カナちゃん → "kanachan"`. We
   want `Kana-chan`. The 22-entry honorific table lives in
   [translit_core/engine.py](../translit_core/engine.py); we strip a known
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
[`test_mid_string_long_vowel_folded_in_single_token`](../tests/test_ja_romanization.py).

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

## 6. Korean: traditional overlay layered on Revised Romanization

Korean is the one language pair where we don't depend on an external
library — `hangul-romanize` exists but its `REVISED_*` tables don't match
what RR actually says (initial ㄹ as `'l'` instead of `'r'`, finals as the
underlying lenis form `'g'` instead of pause-form `'k'`). Easier and more
correct to implement RR ourselves: ~30 lines via Hangul codepoint
decomposition.

Each Hangul syllable block (U+AC00–U+D7A3) decomposes deterministically:

```
syllable_index = (initial_index * 21 + medial_index) * 28 + final_index
```

So we look up each component in three small tables (19 initials, 21 vowels,
28 finals) and concatenate. Per-syllable feeding keeps each block atomic —
no sandhi rules to worry about, suitable for hyphen-joined names like
`Jeong-eun` where each piece stands alone.

**The traditional overlay.** Pure RR would render `김 → "Gim"`, `이 → "I"`,
`박 → "Bak"`, `최 → "Choe"`. You'd never see those spellings in real life.
Korean newspapers, passports, and business cards universally use the
*traditional* spellings: Kim / Lee / Park / Choi / Jung / Yoon / Cho.
We ship a 36-entry surname overlay covering ~85% of the population's
family names. Unknown surnames fall back to RR.

```python
_KO_SURNAME_OVERLAY = {
    "김": "Kim", "이": "Lee", "박": "Park", "최": "Choi",
    "정": "Jung", "강": "Kang", "조": "Cho", "윤": "Yoon",
    # ... 30+ more, including 2-syllable family names like 남궁/황보
}
```

**Family-name boundary.** Korean family names are almost always 1 syllable
(99% of the population). A handful of 2-syllable family names exist
(남궁/Namgoong, 황보/Hwangbo, 사공/Sagong, 제갈/Jegal, 선우/Sunwoo, 독고/Dokgo);
those are tracked as keys in the overlay, and the engine prefers a
2-syllable family match over a 1-syllable one when the head matches.

**Press-style capitalization.** Korean given names appear with the second
syllable lowercase in news writing (`Lee Min-ho`, `Kim Jong-un`,
`Park Geun-hye`). We capitalize only the first syllable of the given name
and join with hyphens; the family name's casing comes straight from the
overlay (or a `Title()`'d RR fallback).

**Same `name_order` flag.** Family-first is the default; `given-first`
swaps to `Geun-hye Park` etc. The flag works the same way as for Japanese.

**Korean honorifics.** Same longest-match-wins suffix-strip mechanic as
the JA dict, with three entries:

```python
("선생님", "-seonsaengnim"),  # teacher / formal address
("씨", "-ssi"),               # general
("님", "-nim"),               # respectful
```

`박지성씨 → "Park Ji-seong-ssi"`, `이선생님 → "Lee-seonsaengnim"`. Bare
honorifics with no name attached fall through to plain RR.

**Out of scope (deferred):**
- **Hanja form of Korean names.** `金正恩` (the Hanja spelling of 김정은)
  routes through `pypinyin` and emits Mandarin pinyin (`Jin Zheng En`),
  not the Korean reading. Recovering the Korean reading would need a
  Hanja → Hangul-reading dictionary (~1000+ entries, not all reversible —
  one Hanja can have multiple Korean readings). Callers can pre-convert
  to Hangul before calling.
- **North Korean transliteration conventions** (differ slightly from RR).
- **Per-person spelling overrides.** `이수만 → "Lee Soo-man"` vs RR
  `"Lee Su-man"`; `김정은 → "Kim Jong-un"` (press) vs `"Kim Jeong-eun"`
  (RR). The choice depends on individual preference and isn't
  recoverable from the Hangul alone. RR is the deterministic baseline.

## 7. Russian (Cyrillic → Latin)

The standard Python libraries (`transliterate`, `cyrtranslit`) lean
GOST/scientific style — `Sergej` instead of `Sergey`, `Mihail` instead
of `Mikhail`, `Ahmatova` instead of `Akhmatova`, `Ol'ga` instead of
`Olga`, and they sometimes strip the y-glide on ё (`Fedor` instead of
`Fyodor`). None of those match how Russian names appear in
English-language press, sports, or visa contexts. So Russian is, like
Korean, an in-repo implementation: a 33-letter case-preserving map plus
8 digraph rules, ~70 lines total.

The map follows BGN/PCGN with the press-friendly tweaks that real
newspapers print: `х → kh` (not `h`), ё-glide preserved (`Fyodor`,
`Semyon`), soft/hard signs dropped (`Olga`, `Igor`).

**Digraph rule for ъе/ье.** Strict per-char drop of ъ/ь followed by е
gives plain `e` — but press writes `ye` here (`Obyekt`, `Yuryevich`).
A small lookup of 8 cased pairs catches it before single-char dispatch:

```python
_RU_DIGRAPHS = {
    "ъе": "ye", "Ъе": "Ye", "ъЕ": "yE", "ЪЕ": "YE",
    "ье": "ye", "Ье": "Ye", "ьЕ": "yE", "ЬЕ": "YE",
}
```

ъё/ьё/ъя/ьа/ъю/ью don't need digraph rules because ё/я/ю already start
with a y in the base map.

**Case handling.** Whatever case the input is (`ИВАН`, `иван`, `Иван`),
the output is title-cased per word and per hyphen-delimited piece via
Python's `str.title()` — `иван-петров → Ivan-Petrov`.

**Refused inputs.** Letters from related Cyrillic alphabets we haven't
tabled (Ukrainian Ї, Macedonian Ѓ, etc.) trigger a refusal rather than
an emit-the-Cyrillic-as-itself fallback. Mixed Russian+Latin similarly
returns None.

**Out of scope (for now):**
- **Word-initial Е → Ye.** BGN says word-initial е maps to "Ye" rather
  than "E" (Yelena, Yevgeny, Yeltsin). The rule is contextual; press
  applies it inconsistently. Strict-map gives `Elena`/`Evgeniy`/`Eltsin`
  — defensible defaults, but not always what press would print.
- **Ukrainian/Belarusian/Bulgarian/Macedonian Cyrillic.** Detection
  groups all Cyrillic as `ru`; we'd need separate maps to handle
  language-specific letters and conventions.
- **Patronymic recognition.** We don't detect Russian patronymics as
  honorific-like suffixes — they get romanized as part of the name
  (e.g., `Иван Сергеевич → Ivan Sergeevich`), which is the correct
  behavior anyway.

## 8. Hindi (Devanagari → Latin)

Hindi is the first pair where we both use a library and post-process its
output. `indic-transliteration` emits academic IAST (with macrons,
underdots, vocalic-r). Press style demands ASCII without diacritics +
**schwa deletion**. The pipeline:

1. Strip non-Devanagari letters from input (filter danda U+0964, double
   danda U+0965, Devanagari digits U+0966-U+096F).
2. Run through `sanscript.transliterate(..., DEVANAGARI, IAST)` to get
   IAST.
3. Schwa-delete on IAST (before stripping diacritics, so `ā` and `a`
   stay distinguishable): drop word-final inherent `a` if preceded by
   exactly one consonant unit. Cluster preceding the `a` keeps it.
4. Strip diacritics: `ā→a`, `ī→i`, `ū→u`, `ṃ/ṅ/ñ/ṇ→n`, `ṛ→ri`, `ṭ→t`,
   `ḍ→d`, `ḥ→` (drop), `ś/ṣ→sh`, `c→ch`.
5. Title-case per word.

### Schwa deletion: where it bites

Schwa deletion is the single biggest difference between IAST and
press-style Hindi. Modern Hindi pronunciation deletes the inherent
vowel `अ` (a) at the end of most words, but only when it follows a
single consonant. Examples:

| Input | IAST | After schwa-delete | After diacritic strip |
|---|---|---|---|
| राम (Rāma) | `rāma` | `rām` | `Ram` |
| अमित | `amita` | `amit` | `Amit` |
| सुनीता | `sunītā` | `sunītā` (last vowel is long ā, not schwa) | `Sunita` |
| कृष्ण | `kṛṣṇa` | `kṛṣṇa` (cluster ṣṇ before the a) | `Krishna` |

The cluster check is what keeps `Krishna` from becoming `Krishn` — the
two-consonant cluster `ṣṇ` before the final `a` signals that the inherent
vowel is pronounced.

### Aspirated digraphs need special-casing

IAST writes aspirated stops as digraphs: `bh`, `dh`, `gh`, `jh`, `kh`,
`ph`, `th`, `ch`, `ḍh`, `ṭh`. They're two ASCII characters but a single
phoneme. A naive "is the previous character a consonant?" cluster check
mistakes them for clusters and over-preserves the schwa:

```
अमिताभ (Amitābh) → IAST 'amitābha'
                 → naive: word[-3]='b' is a consonant → cluster → keep 'a' → 'Amitabha' ✗
                 → correct: 'bh' is one consonant → check word[-4]='ā' (vowel) → no cluster → drop 'a' → 'Amitabh' ✓
```

The fix: when the consonant before final `a` is `h` and the character
before THAT is in `{b,d,g,j,k,p,t,c,ḍ,ṭ}`, treat the digraph as one
consonant and look one position further back for the cluster check.

### Out of scope (deferred)

- **Anusvara + h (ṃh) → "ngh"**. `सिंह` is universally written `Singh`
  (Sikh surname), but our rules emit `Sinha` (which is also a real Hindi
  surname). Recovering `Singh` needs a name-specific override.
- **`ī → ee` press substitution**. Some names appear with double-`e`
  in press (Deepika, Veer) instead of single-`i` (Dipika, Vir). Both
  are common; we ship the single-letter form as the deterministic baseline.
- **Schwa deletion is heuristic.** A pronunciation dictionary would
  catch the ~10% of names where rules-based schwa-delete is wrong.
- **Other Brahmic scripts** (Bengali, Tamil, Telugu, Gurmukhi). The
  `indic-transliteration` lib supports them, but their conventions
  differ enough that each needs its own pipeline.

## 9. Arabic: the dictionary path

Arabic is the first pair where I gave up on rules-based romanization
and shipped a curated dictionary instead. The reason is structural:
**Arabic written without short vowels is fundamentally
under-determined for romanization.** The string م-ح-م-د could be
"Muhammad", "Mohammed", "Mahmoud", or several other readings depending
on the consensus pronunciation. Without vowel context (which native
Arabic text rarely includes), there's no rule we can write.

The path the academic community took was Buckwalter encoding — a
1-to-1 ASCII mapping (m-h-m-d for محمد). It's lossless but unreadable
for English readers. Press uses **established personal-name spellings**
that are essentially memorized rather than derived.

So this is what we ship: a ~50-entry overlay of common Arabic names
with their established press spellings. Names not in the overlay
return None — fail-soft is honest. The alternative (consonant-only
output) would be useless for English readers.

**Input normalization before lookup** handles the noisy parts:
- Tashkeel (vowel diacritics, U+064B-U+0652) stripped — vowelized and
  unvowelized inputs hit the same key.
- Hamza-bearing alifs (أ, إ, آ) → plain alif (ا).
- Alef maksura (ى) → ya (ي).
- Tatweel (ـ, U+0640) — visual stretching, removed.
- NFKC normalization first — handles the Allah ligature ﷲ → الله, etc.

**Multi-token compound names** (عبد الله, عبد الرحمن, أبو بكر) are stored
as full-input keys. Whole-input lookup beats per-word fallback so
"Abdullah" wins over trying to match "عبد" + "الله" separately.

**Coverage trade-off.** Curated overlay covers ~70-80% of names English
press writes about — political figures, athletes, entertainment figures,
common given names. Unusual names, regional variations, and modern
nicknames return None. A real solution would need either a much larger
name dataset (~5000+ entries) or LLM Tier-2 fallback. Documented as
a Tier-2 candidate.

## 10. The edge-case bestiary

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

### Round-trip katakana names (`ヴィクター → "Victor"`)

`ヴィクター` is the Japanese transliteration of "Victor". The naive path —
running it through pykakasi — gives `Buikutaa` because pykakasi treats `ヴィ`
as `bui` and `クター` as `kutaa`. To recover `Victor`, we invert `alkana`'s
~49k-entry dictionary on first use to build a *reverse-alkana* map (katakana →
English). When the engine sees all-katakana input, it tries the reverse map
*before* pykakasi:

```python
if _is_all_katakana(stem):
    western = _katakana_to_western(stem)
    if western is not None:
        return western + honorific_roman
```

Multi-word katakana names split on `・` and look up each piece independently
(`ジョン・スミス → "John Smith"`). Honorifics are stripped first, so
`ヴィクターさん → "Victor-san"`. Japanese-origin names like `タナカ`, `サクラ`,
`ナルト` aren't in alkana's dictionary, so they fall through to pykakasi
cleanly — no false positives.

### Acronyms (`FBI → "エフビーアイ"`)

`alkana` knows some acronyms (`NASA → ナサ`, `IBM → アイビーエム`) but misses
many (`FBI`, `USA`, `CEO`, `AI`, `UK`, `EU`, `DNA`, `ATM`). Real Japanese
reads English acronyms letter-by-letter: `FBI → エフビーアイ` (eff-bii-ai). A
26-entry A–Z mapping table closes the gap. Activation rule: only when alkana
has missed *and* the input is 2+ uppercase ASCII letters.

```python
"a": "エー", "b": "ビー", "c": "シー", ...
"f": "エフ", "g": "ジー", "h": "エイチ", "i": "アイ", ...
```

Single uppercase letters (`A`, `I`) deliberately *don't* trigger the fallback
— they're too ambiguous (pronoun? abbreviation?). The engine refuses rather
than guessing.

### Names with punctuation (`Mr. Smith`, `Mary-Jane`)

The en → ja path now does progressive cleanup per word:

1. Try alkana with the word as-is.
2. Strip trailing `.,;:!?` and try again (`"Mr." → "Mr" → ミスター`).
3. Try the acronym fallback if the cleaned word is 2+ uppercase letters.

Hyphenated names get split on the hyphen first (`Mary-Jane → ["Mary", "Jane"]`)
so each piece can look up independently. The result still joins with `・`:
`Mary-Jane → メアリー・ジェイン`.

Still misses: names with leading apostrophes (`O'Brien`, `D'Angelo`) — alkana
doesn't carry those forms, and we don't strip the apostrophe because that
would break `O'Brien` ≠ `Brien`. A name-prefix dictionary (`O'`, `Mc`, `de`)
would help; deferred.

### Family-name-first vs given-name-first (`name_order`)

Modern Japanese government convention (formally adopted 2019) renders names
family-first: `山田太郎 → "Yamada Taro"`. That's the default. Older
Western-facing conventions often flip to given-first (`Taro Yamada`). The
`name_order` parameter on `transliterate()` exposes this:

```python
transliterate("山田太郎", "en", source_lang="ja")                            # "Yamada Taro"
transliterate("山田太郎", "en", source_lang="ja", name_order="given-first")  # "Taro Yamada"
```

The swap only fires when pykakasi tokenizes the input into exactly two parts.
Single-token output — single kanji blocks like `田中`, kana names like `たなか`,
or `タナカ` (where pykakasi can't find a morpheme boundary) — emits unchanged
regardless of `name_order`. Honorifics still attach to the end after the
swap (`山田太郎さん → "Taro Yamada-san"`). Round-trip katakana names
(`ヴィクター → "Victor"`) ignore `name_order` because Western names rendered
in Japanese are already given-first by convention.

Chinese pinyin output (`王明 → "Wang Ming"`) also follows family-first; a
similar swap for `_zh_to_pinyin` could land in v1.1 if needed.

## 11. What you can rely on, what you can't

**Reliable:**
- Common Japanese names (`pykakasi` covers the top several thousand).
- Japanese honorifics from the dictionary (22 entries, longest-match-wins).
- Hiragana, katakana (full-width and half-width), and CJK kanji within the
  Basic Multilingual Plane.
- Common Korean names with traditional surname spellings (Kim/Lee/Park/etc.,
  ~36 surnames covering ~85% of the population).
- Korean given names via Revised Romanization, press-style (`Kim Jong-un`).
- Russian (Cyrillic) names via press-friendly BGN/PCGN — `Mikhail`,
  `Akhmatova`, `Fyodor`, `Yuryevich`.
- Hindi (Devanagari) names via IAST + schwa-delete + diacritic strip —
  `Amit`, `Krishna`, `Narendra Modi`, `Bachchan`.
- Arabic names via curated overlay (~50 entries) — common male/female
  names + compounds (`Abdullah`, `Abdul-Rahman`). Unknown Arabic names
  return None.
- Common English first/last names and loanwords from `alkana`.
- Multi-word English names: whitespace + hyphen splitting, joined with `・`.
- Round-trip katakana → Western name (`ヴィクター → "Victor"`).
- English acronyms 2+ letters (`FBI → エフビーアイ` via A–Z fallback).
- Title prefixes with trailing periods (`Mr. Smith → ミスター・スミス`).

**Unreliable / refused:**
- Pure-kana compound names won't be word-split (`さとうひろし` stays one word).
- Rare 4-byte kanji return `None` (the coverage check catches silent
  dropouts).
- Rare kanji variants (`髙`, `齋`) usually return `None`; pykakasi can't
  read them.
- Korean surnames outside the overlay fall back to RR (`나 → "Na"` rather
  than the personal-choice spelling that surname-holder might use).
- Per-person Korean spelling choices (`이수만 → "Lee Soo-man"` vs RR
  `"Lee Su-man"`) — not recoverable from Hangul alone.
- English names with leading apostrophes (`O'Brien`, `D'Angelo`) miss.
- Single uppercase letters (`A`, `I`) — too ambiguous, refused.
- Single-token Japanese names can't be re-ordered to given-first — no
  family/given boundary exists in the output to swap.

**Out of scope by design:**
- Non-name text (sentences, paragraphs).
- Translation (use Azure or DeepL).
- Languages other than ja/zh/ko/en for now.

## 12. Why a service at all (over just `pip install pykakasi`)

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

## 13. Where to look in the code

| Concern | File / function |
|---|---|
| Script detection | [`translit_core/engine.py:detect_source_script`](../translit_core/engine.py) |
| Honorific dictionary | [`translit_core/engine.py:_JA_HONORIFICS_RAW`](../translit_core/engine.py) |
| Honorific stripping | [`translit_core/engine.py:_ja_to_romaji`](../translit_core/engine.py) (top half) |
| pykakasi → romaji | [`translit_core/engine.py:_ja_to_romaji`](../translit_core/engine.py) (bottom half) |
| zh → pinyin | [`translit_core/engine.py:_zh_to_pinyin`](../translit_core/engine.py) |
| en → katakana | [`translit_core/engine.py:_en_to_katakana`](../translit_core/engine.py) |
| ko → roman + surname overlay | [`translit_core/engine.py:_ko_to_roman`](../translit_core/engine.py) |
| Korean honorific dictionary | [`translit_core/engine.py:_KO_HONORIFICS_RAW`](../translit_core/engine.py) |
| Korean RR per-syllable table | [`translit_core/engine.py:_RR_INITIALS`](../translit_core/engine.py) |
| ru → latin (BGN/PCGN press-style) | [`translit_core/engine.py:_ru_to_latin`](../translit_core/engine.py) |
| Russian Cyrillic table + digraphs | [`translit_core/engine.py:_RU_MAP`](../translit_core/engine.py) |
| hi → latin (IAST + schwa-delete) | [`translit_core/engine.py:_hi_to_latin`](../translit_core/engine.py) |
| IAST → press-style fixup table | [`translit_core/engine.py:_IAST_TO_PRESS`](../translit_core/engine.py) |
| ar → latin (curated name overlay) | [`translit_core/engine.py:_ar_to_latin`](../translit_core/engine.py) |
| Arabic name dictionary | [`translit_core/engine.py:_AR_NAME_OVERLAY_RAW`](../translit_core/engine.py) |
| Coverage / silent-dropout check | [`translit_core/engine.py`](../translit_core/engine.py) (search for `input_alpha`) |
| Edge-case regression tests | [`tests/test_edge_cases.py`](../tests/test_edge_cases.py) |
| Honorific tests | [`tests/test_ja_honorifics.py`](../tests/test_ja_honorifics.py) |
| Romanization tests | [`tests/test_ja_romanization.py`](../tests/test_ja_romanization.py) |

Total core engine: ~200 lines. The rest of the repo is the optional FastAPI
service, deployment scaffolding, and the test suite.
