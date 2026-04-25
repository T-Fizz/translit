# Competitive Analysis

Honest survey of the transliteration-as-a-service landscape. No pitch
language. The question: is this worth building beyond internal use?

## What already exists

### Commercial APIs (enterprise-tier)

**Google Cloud Translation API (v3)**
- Has a `transliterate` method tucked into the Translation product
- Supports ~30 scripts via NMT backend
- Pricing: $20 per 1M characters translated; `detect_language` separate
- Auth: OAuth2 / service accounts via Google Cloud IAM
- DX: generally painful for solo devs — you're provisioning IAM roles to
  look up a name
- Quality: good on the pairs it supports, generalist (not name-aware)

**Microsoft Azure Translator — Transliterate endpoint**
- Dedicated `/transliterate` route, `POST` takes a script pair and array of strings
- 34+ scripts including Indic, Arabic, Thai, CJK
- Pricing: ~$10 per 1M characters, with a free 2M/month tier
- Auth: subscription key header, much friendlier than Google
- Quality: solid; best-in-class for Indic and Arabic imo
- **Closest existing competitor to this service.** Main issues: enterprise
  sign-up flow, no npm-install-and-go feel, pricing gated on committing to
  an Azure plan.

**Yandex Translate API**
- Used to have decent transliteration, pivoted Russia-regional
- Free tier killed, opaque for Western devs
- Effectively unavailable as of late 2025

**IBM Watson Language Translator**
- Has transliteration as a side feature; deprecated-adjacent
- Not a serious option in 2026

### Open-source libraries (not services)

| Lib | Lang pair | Notes |
|---|---|---|
| `pykakasi` | ja → romaji | Hepburn, solid. What we use. |
| `pypinyin` | zh → pinyin | Mature, fast. What we use. |
| `kuroshiro` (+ kuromoji) | ja → romaji | JS, browser-capable, ~12MB dict |
| `hangul-romanize` | ko → Revised Romanization | Rules-based, lightweight |
| `buckwalter` / `arabic-buckwalter-transliteration` | ar → latin | Academic-grade |
| `ICU.Transliterator` (via PyICU) | many | Powerful, heavy binary dep |
| `Unidecode` | any → ASCII | Lossy "nearest letter" — not real transliteration |

All free, all require infra to run. None are "hosted service".

### Consumer / accessibility tools (not dev-facing)

- **Google Input Tools** — consumer keyboard, no public API
- **Lexilogos** — web form, no API
- **Translit.cc** — web form, CC-licensed, ad-supported
- **Bhashini** — Indian government's transliteration push, Indic-only,
  B2G-focused, not really developer-facing

## Where the gap is (and isn't)

### Real gap

1. **Developer-friendly SaaS tier is missing.** The market is bimodal:
   free OSS library (you host it) or enterprise API (you sign a contract).
   There's no Stripe/Resend/Postmark equivalent for transliteration —
   sign up, paste key, go. The closest is Azure Translate, which is still
   enterprise-flavored.

2. **Nothing is name-aware.** Every service treats transliteration as
   generic string → string. Names have conventions none of them handle:
   - Japanese honorifics (`カナちゃん` → `Kana-chan` vs `Kanachan`)
   - Korean surname-first ordering
   - Chinese given-name spacing (王明 → "Wang Ming" not "Wangming")
   - Arabic `al-` / `el-` treatment
   - Russian patronymics
   A service that nails names specifically is differentiated.

3. **No "best engine per pair" routing.** pykakasi is best for ja,
   pypinyin for zh, hangul-romanize for ko, ICU for Indic — but no
   hosted service composes them. A meta-service that picks the right
   underlying engine per pair and presents one API would be novel.

### Not really a gap

1. **Generic string transliteration** is fine via Azure. Competing on
   that is a bad bet — they have more languages and a bigger team.

2. **LLM-based transliteration is getting cheaper.** Claude Haiku 4.5
   scored 13/13 on our name benchmark; a raw API call is now ~$0.0001
   per name. This caps the ceiling on what anyone will pay for a
   dedicated service. We're selling determinism, speed, and the
   moat-cache — not raw capability the LLM doesn't have.

## Market size (honest)

Who actually needs this?

- Language-learning apps (probably the biggest real segment)
- Multilingual party games / social apps with international rooms
- Content platforms with user-generated handles (e.g. displaying
  Japanese usernames to English audiences)
- Address normalization for shipping / forms
- Search indexing (romaji-queryable Japanese content)
- Podcast / video transcript indexing

TAM estimate: low. Probably a few thousand potential paying developers
worldwide. Typical spend per dev would be $10–100/month. Rough ceiling
of a focused business: a few $k MRR from indie devs, maybe $10–30k MRR
if it penetrates language-learning startups well.

**It's a niche, not a rocketship.** Closer to Postmark or Pirsch
(transactional email / privacy analytics) than Stripe.

## What this service brings that fills the gap

Ranked by how differentiated each is:

1. **Name-aware by design** — honorific detection, script-specific
   conventions, CJK ambiguity resolution via `source_lang` hint. None of
   the commercial competitors do this. Strong differentiator.
2. **Deterministic over LLM-based** — same input always produces the
   same output. Azure's NMT-based `transliterate` can drift between
   calls; our pykakasi-backed pipeline can't. Matters in UIs where
   identity/consistency is on-screen.
3. **Developer DX** — API key in a header, no OAuth dance, no pricing
   PDF, no enterprise sales call. Closest existing option is Azure;
   we're easier.
4. **Transparent fallback** — response includes `method` field
   (`pykakasi`, `pypinyin`, `cache`, `llm`) so callers can observe and
   opt out of probabilistic tiers.
5. **Cache-as-moat** — over time a name corpus emerges that would take
   a new entrant years to build. Weak differentiator early, strong
   differentiator later.

## What this service does NOT bring

- **Breadth.** Azure supports 34+ scripts at launch, we'll support 2.
  Catching up on coverage is work measured in months, not days.
- **Enterprise trust signals.** Single founder, no SOC 2, no datacenter
  residency options. Enterprise buyers will not use this.
- **Translation.** We do not translate content. Related but distinct
  market; a caller still needs Azure/DeepL for the sentence-level work.

## Verdict

Real gap, modest size. Worth building for internal use across the
user's apps (Roastly, language-exchange, future) regardless of
business outcome — cost of ownership is low, lock-in savings are real.
Monetizing externally is a longer road: the tech is ~2 weekends, the
marketing-and-docs-and-support business around it is ~6 months of
evenings before meaningful MRR.

Reasonable plan: ship as internal tool, open-source it early, let
external adoption happen organically, add billing when traffic from
outside your own apps justifies it.
