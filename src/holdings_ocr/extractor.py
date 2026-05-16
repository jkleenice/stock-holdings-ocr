from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from .schemas import Holding, HoldingsSnapshot

if TYPE_CHECKING:
    from openai import OpenAI


MODEL = "gpt-4o"

EXTRACTION_PROMPT = """You are a precise OCR extractor for stock brokerage screenshots.
Extract every position visible in the image and return STRICT JSON matching this schema:

{
  "holdings": [
    {
      "raw_name": "<security name exactly as shown, including Korean text if present>",
      "symbol": "<ticker if visible, else null>",
      "quantity": <number or null>,
      "market_value": <number or null>,
      "currency": "<3-letter code>",
      "account": "<account label if visible, else null>",
      "unrealized_pnl": <number or null>,
      "unrealized_pnl_pct": <number or null>
    }
  ],
  "broker_hint": "<primary broker/app if clearly identifiable, else null>",
  "raw_text": "<full visible text, for audit>"
}

Rules:
- Numbers must be plain JSON numbers (no commas, no currency symbols).
- If a field is not visible, use null. Do not invent values.
- Preserve visible Korean names exactly in `raw_name`. Do not translate or expand truncated names.
- If a ticker is not explicitly visible, `symbol` must be null.
- If the screen shows values in 원, ₩, or KRW, emit `currency` as `KRW`.
- If the screen shows values in $, US$, or USD, emit `currency` as `USD`.
- Do not guess currency from the nationality of the company.
- If quantity is not visible, set `quantity` to null. Do not infer it from market value, gain/loss, or percentages.
- If gain/loss is shown as ▲/▼ plus an amount and percent, extract those into `unrealized_pnl` and `unrealized_pnl_pct`.
- Broker or account icons may inform `broker_hint` or `account` only when the label is clear from nearby text.
- Ignore status-bar chrome such as time, signal, battery, and back-navigation UI.
- One row in the image = one holding entry. Do NOT merge or aggregate positions.
- Return JSON only, no prose, no markdown fences.
"""


def extract_from_image(
    image_path: str | Path,
    *,
    client: "OpenAI | None" = None,
    model: str = MODEL,
) -> HoldingsSnapshot:
    """Send an image to the VLM and parse the response into a HoldingsSnapshot.

    Aggregation never happens here — the extractor passes rows through 1:1.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(path)

    if client is None:
        from openai import OpenAI

        client = OpenAI()

    image_b64 = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    media_type = _guess_media_type(path)

    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract holdings."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}",
                        },
                    },
                ],
            },
        ],
    )

    text = response.choices[0].message.content or ""
    payload = json.loads(text)

    return HoldingsSnapshot(
        source=str(path),
        extracted_at=datetime.now(timezone.utc),
        holdings=[Holding(**h) for h in payload.get("holdings", [])],
        broker_hint=payload.get("broker_hint"),
        raw_text=payload.get("raw_text"),
        extractor_model=model,
    )


def _guess_media_type(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "image/png")
