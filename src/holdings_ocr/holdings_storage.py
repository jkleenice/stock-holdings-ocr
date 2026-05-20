from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .schemas import HoldingsSnapshot

CURRENT_HOLDINGS_FILE = Path(".cache/holdings-ocr/current_holdings.json")


@dataclass(frozen=True)
class SnapshotRecord:
    name: str
    snapshot: HoldingsSnapshot
    snapshot_json: str


def save_current_holdings(
    records: list[SnapshotRecord],
    path: Path = CURRENT_HOLDINGS_FILE,
) -> None:
    payload = {
        "version": 1,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "files": [
            {"name": record.name, "snapshot_json": record.snapshot_json}
            for record in records
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_current_holdings(
    path: Path = CURRENT_HOLDINGS_FILE,
) -> list[SnapshotRecord]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return []

    records: list[SnapshotRecord] = []
    try:
        for item in files:
            if not isinstance(item, dict):
                return []
            name = str(item["name"])
            snapshot_json = str(item["snapshot_json"])
            snapshot = HoldingsSnapshot.model_validate_json(snapshot_json)
            records.append(SnapshotRecord(name, snapshot, snapshot_json))
    except (KeyError, ValueError):
        return []
    return records


def clear_current_holdings(path: Path = CURRENT_HOLDINGS_FILE) -> None:
    path.unlink(missing_ok=True)
