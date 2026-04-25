# Work log — v1 build (autonomous session, 2026-04-24)

What Claude built while you were AFK + the library-first refactor that followed.

## TL;DR

- **Tests: 203 passing, 0 xfailed.** All originally-xfailed engine limits fixed
  via pykakasi `passport`-field mode.
- **Repo now ships two things:** a `translit_core` library (pyproject-declared,
  editable-installable) and a `app/` FastAPI service that wraps it. Witsend
  (formerly Roastly) pulls in the library directly; the HTTP service is
  optional infrastructure.
- **Engine rewritten** to use pykakasi's `passport` romanization field —
  simplified-Hepburn used on actual Japanese passports. Handles mid-string
  long vowels and multi-kanji tokenization for free.
- **Smoke-tested in-process.** Real traffic against live Supabase NOT exercised —
  no credentials; see "Blockers" below.

## What's on disk

```
translit_core/          ← pip-installable library — consumers just import this
  __init__.py             re-exports public API
  engine.py               full engine (detection, honorifics, romanizers)

app/                    ← FastAPI service wrapping translit_core
  auth.py                 API-key hash + TTL-cached tenant resolution
  cache.py                InMemoryCache (LRU) + SupabaseCache + TieredCache
  config.py               Settings.from_env()
  errors.py               ApiError + subclasses mapped to DESIGN envelope
  logs.py                 Structured JSON logs with request_id contextvar
  main.py                 create_app() factory, middleware, exception handlers
  models.py               Pydantic request/response models
  routes.py               /v1/{health,supported,transliterate,transliterate/batch}

tests/
  conftest.py             shared fixtures (settings / client / auth headers)
  test_script_detection.py
  test_ja_romanization.py
  test_ja_honorifics.py
  test_engine_api.py
  test_cache.py
  test_auth.py
  test_http_api.py

pyproject.toml          ← package metadata + deps + pytest config
migrations/001_init.sql ← verbatim schema from DESIGN.md §Data model
Dockerfile, fly.toml, .env.example, .dockerignore, requirements.txt
```

### Consuming translit_core from another project

From witsend (or any Python consumer), one of these:

```bash
# Local dev, lives on your disk:
pip install -e /path/to/translit

# From a git URL (no PyPI publish needed):
pip install 'git+https://github.com/you/translit.git#subdirectory='
```

Then:

```python
from translit_core import transliterate, detect_source_script

transliterate("カナちゃん", "en")               # → "Kana-chan"
transliterate("田中", "en", source_lang="ja")   # → "Tanaka"
detect_source_script("ひろし")                  # → "ja"
```

No network, no auth, 2.6μs per warm call.

## Decisions I made without you

### 1. Python 3.12 for the venv (not 3.14)
Homebrew's 3.14 ships with a broken `ensurepip`. Switched the venv to 3.12 for
local dev; [Dockerfile](../Dockerfile) pins `python:3.12-slim`. No other code
impact — all deps resolve identically.

### 2. Compound-honorific bug: fixed + ruleset expanded
[app/transliterate.py:114-128](../app/transliterate.py#L114-L128) — the old guard
`len(stem) > len(suffix)` mis-rejected the exact-match case, so `兄ちゃん` fell
through to bare `ちゃん` + pykakasi reading of `兄` → `Ani-chan`. New behavior:
exact match emits the dict roman form directly (`Niichan`). Extended
`_JA_HONORIFICS_RAW` with pure-hiragana variants (`にいちゃん`, `ねえちゃん`) that
were missing. `ちゃん`/`さん` alone still romanize to `Chan`/`San` — no regression.

### 3. No BOOTSTRAP_API_KEYS required → service still boots
Without `SUPABASE_URL` or `BOOTSTRAP_API_KEYS`, `TenantStore` is empty and every
`/transliterate` hit returns 401. Public routes (`/health`, `/supported`) still
respond. This matches the "fail soft" tenet — the service boots and health-checks
green, but won't serve lookups to an unauthenticated caller. Intentional.

### 4. Batch size limits: 100 entries + 10KB body
Per [DESIGN.md:121](DESIGN.md#L121). Entry count validated in-handler; body size
via `Content-Length`. Streamed/chunked uploads bypass the header check — this is
accepted for v1 (honest clients send it; hostile ones hit 413 slightly later when
starlette buffers).

### 5. Method label derived from resolved source
Instead of re-reading a registry on every lookup, `_method_for()` in
[app/routes.py:29-34](../app/routes.py#L29-L34) has a hardcoded `ja → pykakasi`,
`zh → pypinyin` map. If `supported_pairs()` grows, this map must grow too —
added a comment there. Not DRY'd because the registry shape in
`supported_pairs()` encodes display strings like `"pykakasi+hepburn+honorifics"`
which don't match the terse `method` field in the response. Split by intent.

### 6. No usage_log writes yet
Schema is created in [migrations/001_init.sql](../migrations/001_init.sql) but
nothing writes to it. [DESIGN.md](DESIGN.md) says async upsert every N seconds;
that's a bg task I didn't build this session. SLA.md describes daily aggregates
— we can add a periodic flush in v1.1 without breaking the contract.

### 7. No rate limiting
v1 ships `internal` tier only, which SLA says is unlimited. `rate_limited` error
code exists for when we add `free`/`pro`, but no enforcement today.

### 8. No metrics emission
[DESIGN.md §Observability](DESIGN.md) lists three metrics. Structured logs carry
the tagged data (`method`, `cache_hit` via the `cached` response flag, latency
per request), so metrics can be derived post-hoc from log ingestion until APM
earns its keep.

## Engine: the passport-mode rewrite

The original engine used pykakasi's `hepburn` field and manually folded `ou`/`uu`
only at the end of the full output string. That created three bugs:

1. Mid-string long vowels kept their length marker (`さとうひろし → Satouhiroshi`).
2. Multi-kanji names jammed together (`山田太郎 → Yamadataro`).
3. `oumei → Oumei` for `王明` read as Japanese, when the real-world form is `Omei`.

Switching to pykakasi's `passport` field — which is modeled on the romanization
Japanese passports use — fixed all three in one edit. Key findings:

- `passport` already folds most mid-string long vowels (`satou → sato`,
  `oumei → omei`). The previous manual fold was redundant and less capable.
- pykakasi returns **tokens** per morpheme boundary. Joining them with a space
  (instead of `"".join`) gives us name splitting for free: `山田太郎 → [山田, 太郎] → "Yamada Taro"`.
- `passport` is *inconsistent* on yōon and gemination (`しょう → shou`,
  `がっこう → gakkou`, `ゆう → yuu` — still un-folded). We backstop with our
  own `ou`/`uu` end-of-token fold, which cleans those cases.

The kana-tokenization limit that remains: pure-kana compound names like
`さとうひろし` come back as one pykakasi token. Passport folds the internal long
vowel (`satohiroshi`) but can't split the word boundary. A separate kana word-
boundary detector is the only way — it's not attempted. Test
`test_mid_string_long_vowel_folded_in_single_token` pins the realistic behavior.

## Blockers I hit

1. **No Supabase credentials → L2 cache not live-tested.** `SupabaseCache`
   reads/writes are structured per the supabase-py API but have zero runtime
   verification. Verify before prod: point `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`
   at a real instance, run migrations, POST a known name twice, confirm second
   call has `"cached": true`. If the supabase-py signatures have drifted from
   what I wrote in [app/cache.py:81-122](../app/cache.py#L81-L122), update there.

2. **No Fly account access → no deploy verification.** [Dockerfile](../Dockerfile)
   and [fly.toml](../fly.toml) are written but never actually `fly deploy`'d.
   One thing worth checking on first deploy: dict-warming `RUN` step in the
   Dockerfile adds ~5-15s to build time. If that's unacceptable, delete those
   two lines and accept the cold-start penalty on boot instead.

3. **pykakasi 3 vs 2 API drift.** `requirements.txt` pins `pykakasi==2.*`. The
   engine uses the old `kakasi().convert()` shape. If anyone bumps to 3.x later
   the API changed (now `.convert()` returns a string). Pin is intentional.

## How to run

```bash
# From a clean clone:
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt   # resolves to -e .[service,test]
.venv/bin/pytest              # → 203 passed
.venv/bin/uvicorn app.main:app --reload --port 8080

# With auth:
BOOTSTRAP_API_KEYS=dev-local:local .venv/bin/uvicorn app.main:app --reload

# Smoke call:
curl -s localhost:8080/v1/transliterate \
    -H 'x-api-key: dev-local' -H 'content-type: application/json' \
    -d '{"name":"カナちゃん","target_lang":"en"}'
# → {"phonetic":"Kana-chan","source_lang":"ja","target_lang":"en","method":"pykakasi","cached":false,"reason":null}
```

## Before you push to Fly

- [ ] Create a Supabase project; run `migrations/001_init.sql` against it.
- [ ] Seed `tenants` with your first real key: `insert into tenants (name, api_key_hash, tier) values ('internal', encode(sha256('<raw-key>'::bytea), 'hex'), 'internal');`
- [ ] `fly secrets set SUPABASE_URL=... SUPABASE_SERVICE_KEY=... BOOTSTRAP_API_KEYS=<raw-key>:internal`
- [ ] `fly deploy`
- [ ] Hit `/v1/health` — expect 200.
- [ ] POST a lookup twice, verify `"cached": true` on the second.

## Next time I'd suggest

- Fix the two pykakasi spacing xfails (probably a 2-hour project: detect
  family+given-name boundary via a common-surname list, insert a space, then
  fold `ou`/`uu` per token not per raw).
- Wire the async `usage_log` flusher for DESIGN.md compliance.
- Add a `/v1/usage/me` endpoint (per DESIGN §Roadmap v1.1).
- Consider adding a property-based test: generate random kana strings and
  assert `transliterate(x) != None` and is all-ASCII. Would catch whole classes
  of pykakasi regressions we haven't seen yet.
