# Service Level Agreement

What translit commits to, and what callers can reasonably rely on.
Written for the service's own reference — this is NOT a legal document
and NOT customer-facing marketing copy. Customer-facing terms go in a
separate `TERMS.md` once we have paying customers.

## Uptime

| Tier | Target | Measurement window | Exclusions |
|------|--------|--------------------|------------|
| internal (v1) | 99.0% | 30-day rolling | Fly outages, upstream Postgres unavailability, planned maintenance with ≥24h notice |
| pro (future) | 99.9% | 30-day rolling | Same + region-specific outages if customer opted into single-region pricing |

99.0% = ~7 hours/month of allowed downtime. We're on Fly with one
machine in sjc; that's roughly the real-world ceiling before we
introduce multi-region.

## Latency

Measured at the service boundary (excludes caller's network round
trip). Per tier:

| Path | p50 | p95 | p99 | Notes |
|------|-----|-----|-----|-------|
| Cache hit (in-memory) | <1ms | <2ms | <5ms | Same process |
| Cache hit (Postgres) | 8ms | 20ms | 50ms | Includes Supabase round trip |
| Cache miss, deterministic | 10ms | 30ms | 80ms | pykakasi/pypinyin cold-warm |
| Cache miss, batch of 10 | 15ms | 40ms | 100ms | Parallel lib calls |
| Cache miss, LLM fallback (v2) | 400ms | 900ms | 2000ms | OpenRouter-bound |

Cold-start on a fresh Fly machine: first request after a restart may
see +50–150ms as pykakasi loads its dictionary. Subsequent requests
are steady-state.

## Rate limits

Per tenant, per hour:

| Tier | Rate | Burst |
|------|------|-------|
| internal | unlimited | unlimited |
| free (future self-serve) | 1,000/hour | 100/minute |
| pro (future) | 50,000/hour | 500/minute |

Enforced via a sliding-window counter in Postgres. Over-limit returns
429 with `Retry-After`. No queueing — we reject rather than delay.

## Cache hit ratio

Target: **>90% of lookups served from cache after the service has
been running 30 days.**

This is the core promise — once the cache warms, most traffic costs
us nothing beyond a Postgres lookup. Measured via the `cache_hit`
tag on `translit.lookup.count`.

If cache hit ratio drops below 70% sustained over 7 days, investigate
— likely either:
- New traffic source hitting cold names in unfamiliar languages
- Bug in cache write path
- A caller sending noise / random strings

## Error budget

99.0% uptime = ~7h/month error budget. Burn rate alerts:
- Error rate > 1% sustained over 5 minutes → page
- Error rate > 0.1% sustained over 1 hour → email
- Error rate > 0.01% sustained over 24 hours → log only

For v1, "pager" means a push notification to the maintainer. No ops
team exists.

## Versioning and deprecation

- **URL versioning** (`/v1/...`). Breaking changes mean a new prefix,
  not a patch to existing paths.
- **Additive changes** (new fields, new optional params, new methods)
  ship to the current version without notice.
- **Deprecations** get **90 days notice** via email to all active
  tenants and a `Sunset` header on affected endpoints.
- **v1 support commitment:** maintained until v3 ships (i.e. at
  least one major version overlap).

## Support

- **Internal:** Slack DM to maintainer. Response within one business day.
- **Free tier (future):** GitHub issues. Best-effort, no response-time
  commitment.
- **Pro tier (future):** email support with 24-hour business-day response.

## Data handling

- **PII:** names are treated as pseudonymous public data, as described
  in `TENETS.md`. No association with IP, UA, or tenant is written to
  the cache.
- **Retention:** cache rows persist indefinitely; usage logs keep 90
  days then age out.
- **Deletion on request:** a tenant can request removal of specific
  (name, source, target) tuples via support; we'll honor it without
  question. Cache is public; anyone could derive the same output, so
  "deletion" is a best-effort convenience, not a privacy guarantee.
- **Backups:** Supabase daily backups, 7-day retention on free tier.

## Incident process

When the service breaks:

1. Acknowledge within 15 minutes (status page update or similar).
2. Mitigate — restart, rollback, or disable the broken tier.
3. Write a post-incident note in `INCIDENTS.md` (add this file when
   the first incident happens, not before).

## What we do NOT guarantee

- **Quality of transliteration.** We commit to deterministic output,
  not to "linguistically correct for all humans." Hepburn romaji has
  multiple valid forms; we pick one.
- **Identity of output across updates.** Dictionary upgrades (e.g.
  pykakasi bumps) can change outputs for a specific name. We'll note
  these in release notes. If you need frozen output, cache the
  result locally once.
- **Real-time analytics.** Usage counters are eventually consistent,
  lagging real-time by up to 60 seconds.
