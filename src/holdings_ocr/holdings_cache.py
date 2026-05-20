from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Callable
from pathlib import Path

from .extractor import EXTRACTION_PROMPT, MODEL, extract_from_image
from .schemas import HoldingsSnapshot

PROMPT_FINGERPRINT = hashlib.sha256(EXTRACTION_PROMPT.encode("utf-8")).hexdigest()[:16]
CACHE_DIR = Path(".cache/holdings-ocr/snapshots")
Extractor = Callable[..., HoldingsSnapshot]


def content_hash(image_bytes: bytes, model_id: str, prompt_fp: str) -> str:
    """Stable content-addressed key. Same image + model + prompt -> same hash."""
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(b"\x00")
    h.update(model_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(prompt_fp.encode("utf-8"))
    return h.hexdigest()


def extract_to_snapshot_json(
    image_bytes: bytes,
    suffix: str,
    model_id: str = MODEL,
    *,
    extractor: Extractor = extract_from_image,
) -> str:
    """Pure extraction boundary: bytes -> temporary file -> snapshot JSON."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(image_bytes)
        tmp_path = Path(tf.name)
    try:
        snapshot = extractor(tmp_path, model=model_id)
        return snapshot.model_dump_json(indent=2)
    finally:
        tmp_path.unlink(missing_ok=True)


def extract_with_disk_cache(
    image_bytes: bytes,
    suffix: str,
    model_id: str,
    prompt_fp: str,
    *,
    cache_dir: Path = CACHE_DIR,
    extractor: Extractor = extract_from_image,
) -> str:
    """Disk cache layer around OCR extraction. Cache write failures do not break extraction."""
    cache_key = content_hash(image_bytes, model_id, prompt_fp)
    cache_file = cache_dir / f"{cache_key}.json"
    if cache_file.exists():
        try:
            return cache_file.read_text(encoding="utf-8")
        except OSError:
            pass

    snapshot_json = extract_to_snapshot_json(
        image_bytes,
        suffix,
        model_id,
        extractor=extractor,
    )

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(snapshot_json, encoding="utf-8")
    except OSError:
        pass

    return snapshot_json
