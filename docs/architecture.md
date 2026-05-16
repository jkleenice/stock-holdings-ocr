# Architecture

## Pipeline

```text
image  ->  extractor (VLM)  ->  HoldingsSnapshot
                                       |
                                       v
                                 normalizer (issuer aliases)
                                       |
                                       v
                                 reporter  ->  AggregatedReport  ->  markdown / JSON
```

## Module boundaries

- `extractor` knows about images and the VLM API. It does *not* know about issuer aliases or aggregation. One row in the image becomes one `Holding`.
- `normalizer` knows about symbol -> issuer mapping and curated Korean raw-name aliases. It is pure: snapshot in, positions out.
- `reporter` validates single-currency math, computes weights, and formats. No I/O beyond the snapshot/report objects.

## Two kinds of "merge"

When the user says "merge Alphabet A and C," there are two distinct operations and both happen inside `aggregate_by_issuer`:

1. **Same issuer, different share class** — `GOOGL` + `GOOG` -> `Alphabet`, driven by `data/aliases/issuer_aliases.yaml`.
2. **Same symbol, different account** — Account #1's `GOOGL` + Account #2's `GOOGL` collapse into one row that lists both accounts in `accounts: [...]`.

Keep these conceptually separate even though they share an implementation path; they have different failure modes (bad alias vs lost account attribution).

## Normalization precedence

Normalization is intentionally conservative:

1. Symbol alias match (`GOOGL` -> `Alphabet`)
2. Korean raw-name alias match (`알파벳 A` -> `Alphabet`)
3. Symbol passthrough if visible
4. Raw-name passthrough otherwise

This keeps the stronger identifier in control while still allowing Korean screenshots to collapse known issuers.

## Currency and quantity semantics

- v1 assumes a single report currency per snapshot. Mixed currencies fail fast instead of being summed.
- `quantity=None` means "not visible in the screenshot," not zero.
- `market_value` is required for aggregated reporting because report totals and weight percentages are value-based.

## Why VLM over Tesseract for v1

Broker screenshots are dense tables with mixed fonts, locale-specific number formats, and inconsistent column orders. VLM handles layout variance natively. Once a working baseline exists, a cheaper Tesseract path can be added behind the same `extract_from_image` interface.

## Contract with future `stock` integration

The stable interface is `HoldingsSnapshot`. If this package is later absorbed into the `stock` monorepo as `packages/holdings-ocr/`, the simulator can consume a `HoldingsSnapshot` as the initial portfolio without depending on extractor internals.
