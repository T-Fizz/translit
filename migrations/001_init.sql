-- Initial schema for translit v1.
-- Verbatim from DESIGN.md §Data model. Run against Supabase Postgres.

create extension if not exists pgcrypto;

-- tenants ---------------------------------------------------------------
create table if not exists tenants (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    api_key_hash text unique not null,
    created_at timestamptz default now(),
    revoked_at timestamptz,
    tier text not null default 'free'   -- free | pro | internal
);

-- transliteration_cache -------------------------------------------------
-- Tenant-agnostic on purpose (TENETS §3, §5): names are public; cache is a
-- shared public good that compounds across tenants.
create table if not exists transliteration_cache (
    hash text primary key,               -- sha256(name|source_lang|target_lang)[:32]
    name text not null,
    source_lang text not null,
    target_lang text not null,
    phonetic text not null,
    method text not null,                -- pykakasi | pypinyin | llm
    created_at timestamptz default now()
);
create index if not exists transliteration_cache_lang_idx
    on transliteration_cache (source_lang, target_lang);

-- usage_log (daily aggregates) ------------------------------------------
-- Intentionally not per-request. Upserts happen async every N seconds so
-- the hot path never touches these rows.
create table if not exists usage_log (
    tenant_id uuid references tenants(id) on delete cascade,
    date date not null,
    lookups int not null default 0,
    cache_hits int not null default 0,
    primary key (tenant_id, date)
);
