"""End-to-end HTTP tests against the FastAPI app via TestClient.

Covers the contract in DESIGN.md §API contract: auth, status codes, error
envelope, cached flag, batch limits, request-id plumbing.
"""
from __future__ import annotations

import pytest


# --- /v1/health -------------------------------------------------------------

def test_health_is_public(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_has_request_id_header(client):
    r = client.get("/v1/health")
    rid = r.headers.get("x-request-id")
    assert rid and rid.startswith("req_")


def test_client_supplied_request_id_echoed(client):
    r = client.get("/v1/health", headers={"x-request-id": "req_client-supplied"})
    assert r.headers.get("x-request-id") == "req_client-supplied"


# --- /v1/supported ----------------------------------------------------------

def test_supported_public(client):
    r = client.get("/v1/supported")
    assert r.status_code == 200
    body = r.json()
    sources = {p["source"] for p in body["pairs"]}
    assert {"ja", "zh"}.issubset(sources)


# --- auth -------------------------------------------------------------------

def test_missing_api_key_is_401(client):
    r = client.post("/v1/transliterate", json={"name": "たなか", "target_lang": "en"})
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["request_id"].startswith("req_")


def test_bad_api_key_is_401(client):
    r = client.post(
        "/v1/transliterate",
        json={"name": "たなか", "target_lang": "en"},
        headers={"x-api-key": "bogus"},
    )
    assert r.status_code == 401


# --- /v1/transliterate single ----------------------------------------------

def test_transliterate_hiragana(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "たなか", "target_lang": "en"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["phonetic"] == "Tanaka"
    assert body["source_lang"] == "ja"
    assert body["target_lang"] == "en"
    assert body["method"] == "pykakasi"
    assert body["cached"] is False
    assert body["reason"] is None


def test_transliterate_second_call_hits_cache(client, auth_headers):
    payload = {"name": "さくら", "target_lang": "en"}
    r1 = client.post("/v1/transliterate", json=payload, headers=auth_headers)
    r2 = client.post("/v1/transliterate", json=payload, headers=auth_headers)
    assert r1.json()["cached"] is False
    assert r2.json()["cached"] is True
    assert r1.json()["phonetic"] == r2.json()["phonetic"] == "Sakura"


def test_transliterate_kanji_with_ja_hint(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "田中", "source_lang": "ja", "target_lang": "en"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["phonetic"] == "Tanaka"
    assert body["source_lang"] == "ja"


def test_transliterate_kanji_defaults_to_zh(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "田中", "target_lang": "en"},
        headers=auth_headers,
    )
    body = r.json()
    assert body["source_lang"] == "zh"
    assert body["phonetic"] == "Tian Zhong"


def test_honorific_stripped_and_appended(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "カナちゃん", "target_lang": "en"},
        headers=auth_headers,
    )
    assert r.json()["phonetic"] == "Kana-chan"


def test_unsupported_source_returns_200_with_reason(client, auth_headers):
    """Detected source but no romanizer can produce output → 'unsupported_pair'.
    Using an Arabic name not in the curated overlay (the overlay only
    covers ~50 common names; this exercises the fail-soft path)."""
    r = client.post(
        "/v1/transliterate",
        json={"name": "زياده", "target_lang": "en"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["phonetic"] is None
    assert body["method"] is None
    assert body["reason"] == "unsupported_pair"
    assert body["source_lang"] == "ar"


def test_unsupported_target_is_200_with_reason(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "たなか", "target_lang": "ja"},
        headers=auth_headers,
    )
    body = r.json()
    assert body["phonetic"] is None
    assert body["reason"] == "unsupported_pair"


def test_latin_input_returns_reason(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "Tanaka", "target_lang": "en"},
        headers=auth_headers,
    )
    body = r.json()
    assert body["phonetic"] is None
    assert body["reason"] == "unsupported_pair"


# --- en → ja katakana (alkana) ---------------------------------------------

def test_en_to_katakana_single_word(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "John", "target_lang": "ja"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["phonetic"] == "ジョン"
    assert body["method"] == "alkana"
    assert body["target_lang"] == "ja"
    assert body["cached"] is False


def test_en_to_katakana_multi_word(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "John Smith", "target_lang": "ja"},
        headers=auth_headers,
    )
    assert r.json()["phonetic"] == "ジョン・スミス"


def test_en_to_katakana_unknown_word_uses_phonetic_fallback(client, auth_headers):
    """alkana misses fall through to the phonetic engine; HTTP layer
    surfaces a non-None phonetic with method 'alkana' (still the
    overall route — fallback is internal to that path)."""
    r = client.post(
        "/v1/transliterate",
        json={"name": "Joaquin", "target_lang": "ja"},
        headers=auth_headers,
    )
    body = r.json()
    assert body["phonetic"] is not None
    assert body["reason"] is None


def test_en_to_katakana_caches(client, auth_headers):
    payload = {"name": "Christopher", "target_lang": "ja"}
    r1 = client.post("/v1/transliterate", json=payload, headers=auth_headers)
    r2 = client.post("/v1/transliterate", json=payload, headers=auth_headers)
    assert r1.json()["cached"] is False
    assert r2.json()["cached"] is True
    assert r1.json()["phonetic"] == r2.json()["phonetic"] == "クリストファー"


# --- validation -------------------------------------------------------------

def test_missing_name_is_400(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"target_lang": "en"},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_request"


def test_empty_name_is_400(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "", "target_lang": "en"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_missing_target_is_400(client, auth_headers):
    r = client.post(
        "/v1/transliterate",
        json={"name": "たなか"},
        headers=auth_headers,
    )
    assert r.status_code == 400


# --- /v1/transliterate/batch ------------------------------------------------

def test_batch_basic(client, auth_headers):
    r = client.post(
        "/v1/transliterate/batch",
        json={
            "entries": [
                {"name": "カナちゃん", "source_lang": "ja", "target_lang": "en"},
                {"name": "王明", "source_lang": "zh", "target_lang": "en"},
            ]
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2
    assert body["results"][0]["phonetic"] == "Kana-chan"
    assert body["results"][0]["method"] == "pykakasi"
    assert body["results"][1]["phonetic"] == "Wang Ming"
    assert body["results"][1]["method"] == "pypinyin"


def test_batch_mixed_supported_and_unsupported(client, auth_headers):
    r = client.post(
        "/v1/transliterate/batch",
        json={
            "entries": [
                {"name": "たなか", "target_lang": "en"},
                {"name": "زياده", "target_lang": "en"},
            ]
        },
        headers=auth_headers,
    )
    body = r.json()
    assert body["results"][0]["phonetic"] == "Tanaka"
    assert body["results"][1]["phonetic"] is None
    assert body["results"][1]["reason"] == "unsupported_pair"


def test_batch_too_many_entries_is_413(client, auth_headers):
    entries = [{"name": "たなか", "target_lang": "en"}] * 101
    r = client.post(
        "/v1/transliterate/batch",
        json={"entries": entries},
        headers=auth_headers,
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


def test_batch_empty_entries_is_400(client, auth_headers):
    r = client.post(
        "/v1/transliterate/batch",
        json={"entries": []},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_batch_cache_works_across_entries(client, auth_headers):
    payload = {
        "entries": [
            {"name": "ひろし", "target_lang": "en"},
            {"name": "ひろし", "target_lang": "en"},
        ]
    }
    r = client.post("/v1/transliterate/batch", json=payload, headers=auth_headers)
    results = r.json()["results"]
    assert results[0]["cached"] is False
    assert results[1]["cached"] is True
    assert results[0]["phonetic"] == results[1]["phonetic"] == "Hiroshi"


# --- error envelope ---------------------------------------------------------

@pytest.mark.parametrize(
    "status, path, payload, headers_key",
    [
        (401, "/v1/transliterate", {"name": "たなか", "target_lang": "en"}, None),
        (400, "/v1/transliterate", {"target_lang": "en"}, "auth"),
    ],
)
def test_error_envelope_shape(client, auth_headers, status, path, payload, headers_key):
    headers = auth_headers if headers_key == "auth" else {}
    r = client.post(path, json=payload, headers=headers)
    assert r.status_code == status
    body = r.json()
    assert set(body["error"].keys()) == {"code", "message", "request_id"}
    assert body["error"]["request_id"].startswith("req_")
