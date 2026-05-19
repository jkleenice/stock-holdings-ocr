# stock-holdings-ocr

Extract stock holdings from broker screenshots, normalize share-class aliases and curated Korean issuer names, and produce an aggregated portfolio report.

## What it does

1. **Extract** — VLM (OpenAI `gpt-4o`) reads an image of a broker portfolio and returns structured holdings as JSON.
2. **Normalize** — Maps symbol aliases and curated Korean raw names (e.g., `알파벳 A` + `알파벳 C`) to a single issuer, and collapses the same issuer held across multiple accounts.
3. **Report** — Aggregates by issuer, enforces a single-currency snapshot, and renders markdown or JSON with portfolio weights.
4. **YouTube notes** — Extracts YouTube video metadata and subtitles into Markdown notes, with optional OpenAI summaries.

## Quick start

```bash
make setup
export OPENAI_API_KEY=sk-...

# Extract holdings from an image into a snapshot file
.venv/bin/holdings-ocr extract path/to/broker.png -o snapshot.json

# Render an aggregated report
.venv/bin/holdings-ocr report snapshot.json

# Extract Korean subtitles from a YouTube URL into Markdown
.venv/bin/holdings-ocr youtube "https://www.youtube.com/watch?v=..." -o youtube_notes/
```

## Streamlit UI

```bash
make ui
```

Opens a local app at `http://localhost:8501`. Drag in a screenshot, see the report, snapshot JSON, and raw audit text. Caches results by image+model so re-renders don't re-bill the API.

The sidebar also includes **유튜브 자막 추출**. Paste a YouTube URL to fetch metadata and subtitles through `yt-dlp`; enable AI summary when `OPENAI_API_KEY` is set.

## Structure

```
src/holdings_ocr/
  schemas.py     # Pydantic models: Holding, HoldingsSnapshot, AggregatedReport
  extractor.py   # Image -> HoldingsSnapshot via OpenAI vision (gpt-4o)
  normalizer.py  # Symbol/raw-name -> issuer mapping + grouping
  reporter.py    # HoldingsSnapshot -> AggregatedReport (markdown / JSON)
  youtube.py     # YouTube metadata/subtitle extraction and Markdown notes
  cli.py         # `holdings-ocr extract`, `report`, and `youtube`
data/aliases/
  issuer_aliases.yaml   # issuer -> [symbols]  (Alphabet: [GOOGL, GOOG] ...)
  korean_names.yaml     # issuer -> [raw Korean names]
tests/                  # unit tests; extractor is exercised via fixtures
docs/                   # architecture and prompt design
```

## Current v1 rules

- Every extracted holding must carry an explicit 3-letter currency code.
- Mixed-currency snapshots fail fast at report time.
- Missing share count stays `null` in the snapshot and renders as `-` in markdown.
- ETFs remain independent issuers unless you add an explicit alias.

## Future fit with the `stock` repo

The `HoldingsSnapshot` schema is the stable contract. Once this stabilizes, the package can move into the `stock` monorepo as `packages/holdings-ocr/` and feed the simulator's initial-portfolio input. Until then, keeping it separate avoids mixing the simulator's determinism/audit rules with the extractor's faster iteration loop.
