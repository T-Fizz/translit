# translit — Design Document

Deterministic name-aware transliteration as a service. Internal version 1.

## Problem

Every app that renders user-generated names across language boundaries
hits the same wall: showing a Japanese name to an English reader, or
vice versa, in a way that's legible. Existing solutions are either
free libraries (infra burden) or enterprise APIs (auth/pricing
friction). None are name-aware; all treat "カナちゃん" as a generic
string and emit "Kanachan" without the hyphen.

## Goals

- **Name-aware transliteration** across common script pairs, starting
  with ja↔en and zh→en.
- **Deterministic output** — same input always produces the same
  phonetic.
- **Single-digit-millisecond p99** on cache hits.
- **Developer-friendly onboarding** — from sign-up to first `curl` in
  under 60 seconds, single `x-api-key` header.
- **Multi-tenant safe** — many apps share the cache, no cross-tenant
  data leakage.

## Non-goals

- Generic content translation (sentences, paragraphs). Use Azure/DeepL.
- UI or dashboard beyond a simple admin page. Developer-only product.
- Sub-millisecond edge latency. We're a normal regional HTTP service,
  not a CDN.
- Support for every script Azure covers. Breadth grows dictionary-by-
  dictionary, not overnight.

## Architecture

```
┌──────────────────────┐
│ Customer app (any)   │
│  HTTP + x-api-key    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐     ┌────────────────────────┐
│ FastAPI on Fly.io    │◄───►│ Postgres (Supabase)    │
│                      │     │ - tenants              │
│  /v1/transliterate   │     │ - transliteration_cache│
│  /v1/batch           │     │ - usage_log (daily agg)│
│                      │     └────────────────────────┘
│  engine:             │
│   1. in-mem memo     │
│   2. postgres cache  │
│   3. deterministic   │
│      libs (pykakasi, │
│      pypinyin, ...)  │
│                      │
└──────────────────────┘
```

Single Fly app, single Postgres. No Redis, no queue, no message bus.
Complexity scales with features, not with traffic.

## API contract

All paths prefixed `/v1`. Authentication via `x-api-key` header.
Request/response is `application/json; charset=utf-8`.

### `POST /v1/transliterate`

Single lookup.

```json
// Request
{
  "name": "カナちゃん",
  "source_lang": "ja",    // ISO 639-1, optional (autodetect if omitted)
  "target_lang": "en"     // ISO 639-1, required
}

// 200 OK
{
  "phonetic": "Kana-chan",
  "source_lang": "ja",           // what we resolved (echo or detected)
  "target_lang": "en",
  "method": "pykakasi",          // pykakasi | pypinyin | cache | null
  "cached": true
}

// 200 OK (unsupported pair — not an error)
{
  "phonetic": null,
  "source_lang": "ko",
  "target_lang": "en",
  "method": null,
  "reason": "unsupported_pair"
}
```

### `POST /v1/transliterate/batch`

Multiple lookups in one call. Must be preferred over many singles for
any caller doing more than 2–3 lookups at once.

```json
// Request
{
  "entries": [
    { "name": "カナちゃん", "source_lang": "ja", "target_lang": "en" },
    { "name": "王明",        "source_lang": "zh", "target_lang": "en" }
  ]
}

// 200 OK
{
  "results": [
    { "phonetic": "Kana-chan", "method": "pykakasi", "cached": true },
    { "phonetic": "Wang Ming", "method": "pypinyin", "cached": false }
  ]
}
```

Limit: 100 entries per batch, 10KB request body. Returns 413 if exceeded.

### `GET /v1/health`

Public (no auth). Returns `{"status": "ok"}` when the service is
accepting requests. Used by Fly healthchecks and status page.

### `GET /v1/supported`

Public (no auth). Returns the list of supported source→target pairs
and the method used for each. Lets callers probe capability without
parsing release notes.

### Error shape

Every non-2xx response:

```json
{
  "error": {
    "code": "invalid_request" | "unauthorized" | "rate_limited" | "payload_too_large" | "internal",
    "message": "human-readable",
    "request_id": "req_01H..."
  }
}
```

## Data model

### `tenants`

```sql
CREATE TABLE tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  api_key_hash text UNIQUE NOT NULL,   -- sha256 of the raw key, key only shown at creation
  created_at timestamptz DEFAULT now(),
  revoked_at timestamptz,
  tier text NOT NULL DEFAULT 'free'   -- free | pro | internal
);
```

### `transliteration_cache`

```sql
CREATE TABLE transliteration_cache (
  hash text PRIMARY KEY,              -- sha256(name|source_lang|target_lang)[:32]
  name text NOT NULL,
  source_lang text NOT NULL,
  target_lang text NOT NULL,
  phonetic text NOT NULL,
  method text NOT NULL,                -- pykakasi | pypinyin | llm (for future tier 2)
  created_at timestamptz DEFAULT now()
);
CREATE INDEX transliteration_cache_lang_idx ON transliteration_cache (source_lang, target_lang);
```

Intentionally tenant-agnostic: names are public, cache is a shared public good
that compounds across tenants.

### `usage_log`

Daily aggregates. Not per-request.

```sql
CREATE TABLE usage_log (
  tenant_id uuid REFERENCES tenants(id),
  date date NOT NULL,
  lookups int NOT NULL DEFAULT 0,
  cache_hits int NOT NULL DEFAULT 0,
  PRIMARY KEY (tenant_id, date)
);
```

Upserted asynchronously via a background task every N seconds so hot
path never touches usage rows directly.

## Auth model

- **API keys** issued at tenant creation, shown once, stored hashed.
- **Revocation** via `revoked_at` on the tenant row; middleware
  rejects revoked keys in O(1) via in-memory cache refreshed every 60s.
- **Rotation** is manual for v1 (create new tenant → migrate →
  delete old). A `/v1/keys/rotate` endpoint comes when someone needs
  it.
- **No OAuth, no JWTs, no session cookies.** This is not a
  user-facing service.

## Caching strategy

Three layers, in priority order:

1. **In-memory memo** (per process). Python `dict` keyed by
  `(name, source_lang, target_lang)`. LRU-bounded at 50k entries so
  long-running processes don't leak memory. Hit: ~1μs.
2. **Postgres cache** (shared across instances and tenants).
  Keyed by sha256 hash. Hit: 5–20ms.
3. **Deterministic library** (pykakasi / pypinyin / future). Computed
  on miss, result written back to layers 1 and 2. Hit: 1–5ms for
  Japanese and Chinese libs once loaded.

Deterministic results are always cached. LLM-produced results (future
Tier 2) are also cached but with a `method: llm` tag so callers who
want determinism can filter them out.

## Deployment

- **Runtime:** Fly.io, `shared-cpu-1x`, 512 MB. pykakasi + pypinyin
  dictionaries use ~100MB after warmup.
- **Region:** sjc for v1. Other regions only once a customer complains.
- **Database:** Supabase hosted Postgres, free tier. Postgres
  connection pooled via pgBouncer (Supabase default).
- **Secrets:** API keys and Supabase credentials via `fly secrets set`.
- **Logs:** Fly's log stream → Grafana Loki (optional, add when
  billing data matters).

## Observability

Only three metrics matter in v1:

- `translit.lookup.count` tagged by `source_lang`, `target_lang`,
  `method`, `cache_hit`
- `translit.lookup.latency_ms` p50/p95/p99
- `translit.error.count` tagged by error code

Structured JSON logs with `request_id` on every line. No APM until
revenue justifies it.

## Roadmap

### v1 (weekend)
- ja → en, zh → en
- `/v1/transliterate`, `/v1/batch`, `/v1/health`, `/v1/supported`
- API key auth
- Postgres cache
- Roastly as first customer

### v1.1 (next weekend)
- ko → en (Revised Romanization, rule-based, no dict)
- Public status page
- Basic usage dashboard endpoint (`/v1/usage/me`)

### v1.2
- ar → en (Buckwalter / standard Arabic romanization)
- Batch size limit bump to 500
- Simple landing page with curl examples

### v2 (whenever it's interesting)
- Latin → non-Latin (en → ja katakana, en → zh hanzi)
- LLM-backed Tier 2 for unsupported pairs
- Self-serve signup flow
- Stripe billing
- Per-tenant residency options (EU region)

### Rejected for now
- SDKs (a `curl` call is the SDK)
- Sync vs async queues (everything's sync, <20ms)
- GraphQL
- Webhooks
- Dashboards richer than a stats endpoint
