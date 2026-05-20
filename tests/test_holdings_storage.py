import json
from datetime import datetime, timezone
from pathlib import Path

from holdings_ocr.holdings_storage import (
    SnapshotRecord,
    clear_current_holdings,
    load_current_holdings,
    save_current_holdings,
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


def test_save_and_load_current_holdings_round_trip(tmp_path: Path):
    path = tmp_path / "current_holdings.json"
    snapshot = _make_fake_snapshot("first.png")
    snapshot_json = snapshot.model_dump_json(indent=2)

    save_current_holdings([SnapshotRecord("first.png", snapshot, snapshot_json)], path=path)
    loaded = load_current_holdings(path=path)

    assert len(loaded) == 1
    assert loaded[0].name == "first.png"
    assert loaded[0].snapshot.source == "first.png"
    assert json.loads(loaded[0].snapshot_json)["holdings"] == []


def test_save_current_holdings_replaces_existing_file(tmp_path: Path):
    path = tmp_path / "current_holdings.json"
    first = _make_fake_snapshot("first.png")
    second = _make_fake_snapshot("second.png")

    save_current_holdings([SnapshotRecord("first.png", first, first.model_dump_json())], path=path)
    save_current_holdings(
        [SnapshotRecord("second.png", second, second.model_dump_json())],
        path=path,
    )

    loaded = load_current_holdings(path=path)
    assert [record.name for record in loaded] == ["second.png"]


def test_clear_current_holdings_removes_saved_file(tmp_path: Path):
    path = tmp_path / "current_holdings.json"
    snapshot = _make_fake_snapshot("first.png")
    save_current_holdings(
        [SnapshotRecord("first.png", snapshot, snapshot.model_dump_json())],
        path=path,
    )

    clear_current_holdings(path=path)

    assert load_current_holdings(path=path) == []
    assert not path.exists()


def test_load_current_holdings_returns_empty_for_invalid_file(tmp_path: Path):
    path = tmp_path / "current_holdings.json"
    path.write_text("{not-json", encoding="utf-8")

    assert load_current_holdings(path=path) == []
