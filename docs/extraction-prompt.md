# Extraction prompt

The live prompt is `EXTRACTION_PROMPT` in `src/holdings_ocr/extractor.py`. This document explains the design constraints behind it.

## Design rules

1. **Strict JSON output** — no prose, no markdown fences. Anything else makes the parser brittle.
2. **Pass-through, not aggregation** — one row in the image equals one holding entry. Aggregation happens in `normalizer.py`, never in the extractor. Mixing the two inside the prompt hides bugs (e.g., a hallucinated merge looks like a legitimate alias collapse).
3. **Null over invention** — missing fields are `null`. The model must not guess. The cost of a wrong number is much higher than the cost of an unfilled field.
4. **Audit trail** — `raw_text` captures the visible text so downstream consumers can verify what the VLM saw without re-running the model.
5. **Korean UI is first-class** — preserve Korean security names in `raw_name`, emit `KRW` when the screen shows `원`/`₩`, and keep `quantity: null` when the share count is not visible.
6. **No identity inference in extraction** — do not infer tickers from Korean company names. Canonical issuer mapping happens later in `normalizer.py`.

## Tuning workflow

When extraction fails on a new broker UI:

1. Save the image to `tests/fixtures/` (gitignored).
2. Add a regression test that loads the image and asserts on key fields.
3. Adjust the prompt or model only after the failing test is in place.

This keeps prompt changes from silently breaking previously-working broker formats.

## Korean brokerage notes

- `raw_name` should contain the exact visible label, even when it is Korean or truncated.
- `symbol` should stay `null` unless the ticker is explicitly shown.
- `unrealized_pnl` and `unrealized_pnl_pct` may be extracted from nearby ▲/▼ gain-loss lines when they clearly belong to the row.
- Broker badges and account icons are advisory metadata. They may populate `broker_hint` or `account`, but they must not change issuer identity or currency.
