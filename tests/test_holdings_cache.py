import json
from datetime import datetime, timezone
from pathlib import Path

from holdings_ocr.holdings_cache import (
    PROMPT_FINGERPRINT,
    content_hash,
    extract_with_disk_cache,
)
from holdings_ocr.schemas import HoldingsSnapshot


def _make_fake_snapshot(source: str) -> HoldingsSnapshot:
    return HoldingsSnapshot(
        source=source,
        extracted_at=datetime.now(timezone.utc),
        holdings=[],
        broker_hint=None,
        raw_text="",
    )


def test_prompt_fingerprint_is_sixteen_hex_chars():
    assert len(PROMPT_FINGERPRINT) == 16
    int(PROMPT_FINGERPRINT, 16)


def test_content_hash_same_inputs_produce_same_key():
    assert content_hash(b"image-bytes", "gpt-4o", "fp1") == content_hash(
        b"image-bytes",
        "gpt-4o",
        "fp1",
    )


def test_content_hash_changes_when_inputs_change():
    baseline = content_hash(b"img", "gpt-4o", "fp1")
    assert baseline != content_hash(b"img2", "gpt-4o", "fp1")
    assert baseline != content_hash(b"img", "gpt-4o-mini", "fp1")
    assert baseline != content_hash(b"img", "gpt-4o", "fp2")


def test_content_hash_is_64_hex_chars():
    key = content_hash(b"img", "gpt-4o", "fp")
    int(key, 16)
    assert len(key) == 64


def test_disk_cache_returns_existing_file_without_calling_extractor(tmp_path: Path):
    image_bytes = b"image-bytes-for-cache-hit"
    model = "gpt-4o"
    prompt_fp = "abc123"
    cache_key = content_hash(image_bytes, model, prompt_fp)

    cache_dir = tmp_path / "snapshots"
    cache_dir.mkdir()
    cached_json = '{"holdings": [], "broker_hint": null, "raw_text": "cached"}'
    (cache_dir / f"{cache_key}.json").write_text(cached_json, encoding="utf-8")

    def fail_extract(*args, **kwargs):
        raise AssertionError("extractor must not be called on cache hit")

    result = extract_with_disk_cache(
        image_bytes,
        ".png",
        model,
        prompt_fp,
        cache_dir=cache_dir,
        extractor=fail_extract,
    )
    assert result == cached_json


def test_disk_cache_writes_new_file_on_miss(tmp_path: Path):
    image_bytes = b"image-bytes-for-cache-miss"
    model = "gpt-4o"
    prompt_fp = "xyz789"
    cache_dir = tmp_path / "snapshots"

    def fake_extract(path, model):
        return _make_fake_snapshot(str(path))

    result = extract_with_disk_cache(
        image_bytes,
        ".png",
        model,
        prompt_fp,
        cache_dir=cache_dir,
        extractor=fake_extract,
    )
    assert json.loads(result)["holdings"] == []

    cache_key = content_hash(image_bytes, model, prompt_fp)
    cache_file = cache_dir / f"{cache_key}.json"
    assert cache_file.exists()
    assert cache_file.read_text(encoding="utf-8") == result


def test_disk_cache_second_call_hits_cache_and_skips_extractor(tmp_path: Path):
    image_bytes = b"image-for-double-call"
    model = "gpt-4o"
    prompt_fp = "p1"
    cache_dir = tmp_path / "snapshots"
    call_count = {"n": 0}

    def fake_extract(path, model):
        call_count["n"] += 1
        return _make_fake_snapshot(str(path))

    extract_with_disk_cache(
        image_bytes,
        ".png",
        model,
        prompt_fp,
        cache_dir=cache_dir,
        extractor=fake_extract,
    )
    extract_with_disk_cache(
        image_bytes,
        ".jpeg",
        model,
        prompt_fp,
        cache_dir=cache_dir,
        extractor=fake_extract,
    )

    assert call_count["n"] == 1
