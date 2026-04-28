# translit

Deterministic, name-aware transliteration. A small Python library
(`translit_core`) plus an optional FastAPI service (`app/`). Eight
language pairs, each with thoughtful edge-case handling — Japanese
honorifics, Korean traditional surname spellings, Russian press-style,
Hindi schwa deletion, and more.

**Live demo:** [t-fizz.github.io/translit](https://t-fizz.github.io/translit/)
(real Python in your browser via Pyodide)

## Quick start (library)

```bash
pip install -e git+https://github.com/T-Fizz/translit.git#egg=translit-core
```

```python
from translit_core import transliterate

transliterate("カナちゃん", "en")                              # → "Kana-chan"
transliterate("山田太郎", "en", source_lang="ja")              # → "Yamada Taro"
transliterate("김정은", "en", source_lang="ko")                # → "Kim Jeong-eun"
transliterate("Иван Сергеевич Тургенев", "en")                # → "Ivan Sergeevich Turgenev"
transliterate("नरेंद्र मोदी", "en", source_lang="hi")           # → "Narendra Modi"
transliterate("عبد الرحمن", "en", source_lang="ar")            # → "Abdul-Rahman"
transliterate("ทักษิณ", "en", source_lang="th")               # → "Thaksin"
transliterate("John Smith", "ja")                              # → "ジョン・スミス"
```

Returns `None` (fail-soft) when the engine can't deterministically
romanize an input. Warm calls run in microseconds.

## Quick start (HTTP service)

The repo also ships a FastAPI service that wraps the library with
API-key auth, an in-memory + Supabase cache, and the contract in
[docs/DESIGN.md](docs/DESIGN.md). Useful when the consumer isn't
Python or when multiple apps want to share a cache.

```bash
curl -X POST http://localhost:8080/v1/transliterate \
  -H "x-api-key: dev-local-key" \
  -H "content-type: application/json" \
  -d '{"name": "カナちゃん", "source_lang": "ja", "target_lang": "en"}'
# → {"phonetic":"Kana-chan","method":"pykakasi","cached":true,...}
```

## Currently supported

| Source script | Target | Method |
|---|---|---|
| Japanese (kana + kanji) | Latin | `pykakasi` passport-style + 22-entry honorific dict + reverse-katakana round-trip (`ヴィクター → Victor`) |
| Chinese (Hanzi) | Latin | `pypinyin` (no tone marks), family-first |
| Korean (Hangul) | Latin | In-repo per-syllable RR + 36-entry traditional surname overlay (Kim/Lee/Park) + 3-entry honorific dict (씨/님/선생님) |
| Russian (Cyrillic) | Latin | In-repo BGN/PCGN press-style — Mikhail/Akhmatova/Fyodor, ъе/ье digraph fix, soft signs dropped |
| Hindi (Devanagari) | Latin | `indic-transliteration` IAST + diacritic strip + schwa deletion + aspirated-digraph cluster fix |
| Arabic | Latin | Curated overlay of ~50 common names (rules-based impossible without short vowels) |
| Thai (Thai script) | Latin | RTGS via `pythainlp` |
| English (Latin) | Japanese (katakana) | `alkana` dictionary + A–Z acronym fallback (`FBI → エフビーアイ`) + hyphen-name handling |

Plus a `name_order="given-first"` flag that flips ja and ko output to
older Western convention (`Yamada Taro → Taro Yamada`).

## Documents

- **[docs/INTERNALS.md](docs/INTERNALS.md)** — engine deep-dive: every edge case we found, what we fixed, what we accepted, and why
- **[docs/TENETS.md](docs/TENETS.md)** — the principles behind deterministic-and-fail-soft
- **[docs/DESIGN.md](docs/DESIGN.md)** — architecture, API contract, data model, roadmap (FastAPI service)
- **[docs/SLA.md](docs/SLA.md)** — uptime, latency, rate limits, versioning
- **[docs/COMPETITIVE_ANALYSIS.md](docs/COMPETITIVE_ANALYSIS.md)** — survey of existing services

## Local development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # resolves to -e .[service,test]
pytest                             # 547 passing
uvicorn app.main:app --reload      # runs the optional FastAPI service
```

## License

MIT — see [LICENSE](LICENSE).
