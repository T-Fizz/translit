# translit

Deterministic name-aware transliteration as a service. Send a name and a
target language, get back a readable romanization — with Japanese
honorifics, Chinese name spacing, and kanji source-language
disambiguation handled correctly.

## Quick start

```bash
curl -X POST https://translit.example.com/v1/transliterate \
  -H "x-api-key: $TRANSLIT_KEY" \
  -H "content-type: application/json" \
  -d '{"name": "カナちゃん", "source_lang": "ja", "target_lang": "en"}'
# → {"phonetic":"Kana-chan","method":"pykakasi","cached":true}
```

## Documents

- **[INTERNALS.md](INTERNALS.md)** — engine deep-dive: how the wrapper works, every edge case we hit, and the hard problems we couldn't solve
- **[TENETS.md](TENETS.md)** — non-negotiable principles
- **[DESIGN.md](DESIGN.md)** — architecture, API contract, data model, roadmap
- **[SLA.md](SLA.md)** — uptime, latency, rate limits, versioning
- **[COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md)** — honest survey of existing services

## Currently supported

| Source script | Target | Method |
|---|---|---|
| Japanese (kana + kanji) | Latin | `pykakasi` (passport-style Hepburn) + honorific dictionary |
| Chinese (Hanzi) | Latin | `pypinyin` (no tone marks) |
| English (Latin)         | Japanese (katakana) | `alkana` dictionary; multi-word names join with `・` |

See [DESIGN.md → Roadmap](DESIGN.md) for what's coming.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, API_KEYS
uvicorn app.main:app --reload
```

Test:
```bash
pytest
```

## Deploy

```bash
fly deploy
```

## License

MIT — see [LICENSE](LICENSE).
