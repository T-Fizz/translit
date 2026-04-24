# Tenets

Non-negotiable principles for the translit service. Changes to this file
should be discussed, not slipped in.

## 1. Deterministic over probabilistic by default

For every supported language pair we ship a dictionary-based or rules-based
romanizer. An LLM is only considered for pairs where no reasonable open-source
library exists, and even then it's a clearly-flagged Tier 2 result the caller
can opt out of.

**Why:** LLMs produce the same input → different output across calls, miss
long-vowel marks, and ignore strict script rules. Users see the result
rendered next to their own name; inconsistency is uncanny.

## 2. Pure function, no side effects beyond cache writes

Same input (name, source_lang, target_lang) always produces the same output.
No user_id influence, no time-of-day randomness, no A/B buckets. The only
I/O is an idempotent cache write.

**Why:** Determinism is the product. Callers lean on it for multi-device
consistency (same name → same transliteration on every client).

## 3. Cache is the moat

Every resolved transliteration is persisted and shared across tenants.
Popular names (田中, 王明, カナちゃん) cost the service exactly one
computation in its lifetime. The value of the service grows with every
query it answers.

**Why:** Compute is trivially replicable; a warm, broad, battle-tested
cache isn't. This is the asset that compounds.

## 4. Fail soft — never crash the caller

Unsupported pair → `null` phonetic + `reason: "unsupported_pair"`.
Rate limit hit → HTTP 429 with Retry-After.
Internal error → HTTP 5xx with a request ID; never a stack trace.
No endpoint ever returns a 4xx/5xx that requires the caller to parse
free-text error messages.

**Why:** Callers embed us in their critical path. If we crash, they
degrade. Our failure modes must be machine-readable.

## 5. No PII in the cache

Cache keys and values are names and their transliterations — public
information by design. We do not store:
  - tenant_id on cache rows (cache is tenant-agnostic)
  - IP, user-agent, or any request metadata tied to a person
  - Original user-submitted content other than the name being romanized

Usage logs are aggregate (per-tenant counters), not per-request.

**Why:** Names appear in usernames, game handles, and forum posts —
pseudonymous at worst. The cache is read-mostly, shared, and safe to
dump/backup without a privacy review.

## 6. Open standards, no vendor lock-in

HTTP + JSON, UTF-8, ISO 639-1 language codes, no GraphQL, no gRPC, no
SDK-required endpoints. `curl` must be sufficient to exercise every
route. API versioning via URL prefix (`/v1/...`), not headers.

**Why:** Our target customer is a developer who wants to ship a feature
this afternoon. SDKs are a tax on that.

## 7. Language coverage grows by dictionary, not by prompt

Adding a new language means adding a dictionary-backed romanizer and a
test suite, not tweaking a system prompt. If the only way to support a
pair is an LLM call, that's an explicit Tier 2 tag with a different
SLA and price point.

**Why:** Keeps the core predictable and cheap. LLM-fallback SKUs can
exist for completeness but must never subsidize quality regressions in
the core.

## 8. Read-optimized, write-tolerant

Reads are the 99% path. A cache hit should never block on a write, a
network hop to Postgres, or a log flush. Writes can be batched,
eventually-consistent, and fire-and-forget.

**Why:** We're selling lookup speed more than compute speed.
