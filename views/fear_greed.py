from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st


FNG_URL = "https://api.alternative.me/fng/"


def _fetch_fng_raw(limit: int = 30) -> list[dict]:
    """Pull Crypto Fear & Greed history from alternative.me. No caching — testable."""
    response = requests.get(FNG_URL, params={"limit": limit}, timeout=10)
    response.raise_for_status()
    return response.json()["data"]


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_fng(limit: int = 30) -> list[dict]:
    """Cached wrapper around `_fetch_fng_raw` (1 hour TTL)."""
    return _fetch_fng_raw(limit=limit)


def _bar_color(value: int) -> str:
    if value < 25:
        return "#e45756"
    if value < 45:
        return "#f4a261"
    if value < 55:
        return "#e9c46a"
    if value < 75:
        return "#9acd32"
    return "#2ca02c"


def _korean_label(classification: str) -> str:
    mapping = {
        "Extreme Fear": "극도의 공포",
        "Fear": "공포",
        "Neutral": "중립",
        "Greed": "탐욕",
        "Extreme Greed": "극도의 탐욕",
    }
    return mapping.get(classification, classification)


def _metric_value(v: int | None) -> int | str:
    """Return the value itself, or em-dash when None. Critically: 0 stays 0 (not falsy fallback)."""
    return v if v is not None else "—"


def _metric_delta(current: int, prior: int | None) -> int | None:
    """Signed difference; None when prior is missing so Streamlit hides the delta indicator."""
    return (current - prior) if prior is not None else None


def render() -> None:
    st.title("😱 코인 공포·탐욕 지수")
    st.caption("0(극도의 공포)에서 100(극도의 탐욕)까지, 비트코인 시장 심리를 보여드려요")

    try:
        data = _fetch_fng(limit=30)
    except Exception:
        st.error("잠시 후 다시 시도해주세요. 지수 서버에 일시적으로 연결되지 않아요.")
        return

    if not data:
        st.warning("지금은 표시할 데이터가 없어요")
        return

    current = data[0]
    value = int(current["value"])
    classification = current["value_classification"]
    label_ko = _korean_label(classification)

    # ── 자동차 계기판 스타일 게이지 ────────────────────────────
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"font": {"size": 60}},
        title={"text": f"<b>{label_ko}</b><br><span style='font-size:0.8em;color:gray'>{classification}</span>", "font": {"size": 22}},
        domain={"x": [0, 1], "y": [0, 1]},
        gauge={
            "axis": {
                "range": [0, 100],
                "tickwidth": 1,
                "tickvals": [0, 25, 45, 55, 75, 100],
                "ticktext": ["0", "25", "45", "55", "75", "100"],
            },
            "bar": {"color": _bar_color(value), "thickness": 0.25},
            "steps": [
                {"range": [0, 25], "color": "#fadbd8"},
                {"range": [25, 45], "color": "#fdebd0"},
                {"range": [45, 55], "color": "#fcf3cf"},
                {"range": [55, 75], "color": "#d5f5e3"},
                {"range": [75, 100], "color": "#abebc6"},
            ],
            "threshold": {
                "line": {"color": "black", "width": 4},
                "thickness": 0.85,
                "value": value,
            },
        },
    ))
    fig.update_layout(
        height=360,
        margin=dict(l=20, r=20, t=80, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── 비교 지표 (어제/일주일/한 달 전 대비) ────────────────
    def _get_at(idx: int) -> int | None:
        if idx >= len(data):
            return None
        return int(data[idx]["value"])

    yesterday = _get_at(1)
    week_ago = _get_at(7)
    month_ago = _get_at(29)

    def _safe_metric(col, label: str, past: int | None) -> None:
        if past is None:
            col.metric(label, "데이터 없음")
        else:
            col.metric(label, past, value - past)

    c1, c2, c3 = st.columns(3)
    _safe_metric(c1, "어제", yesterday)
    _safe_metric(c2, "지난주", week_ago)
    _safe_metric(c3, "한 달 전", month_ago)
    st.caption("▲는 탐욕 쪽, ▼는 공포 쪽으로 움직였다는 뜻이에요")
    st.caption("공포·탐욕 지수는 손익과 무관한 시장 심리 지표예요")

    # ── 30일 추이 ────────────────────────────────────────────────
    st.subheader("30일 추이")
    df = pd.DataFrame([
        {
            "날짜": datetime.fromtimestamp(int(d["timestamp"])),
            "지수": int(d["value"]),
            "분류": d["value_classification"],
        }
        for d in reversed(data)
    ])
    st.line_chart(df.set_index("날짜")["지수"], height=240)

    with st.expander("30일 데이터 보기"):
        st.dataframe(
            df.assign(분류=df["분류"].map(lambda c: f"{_korean_label(c)} ({c})")),
            use_container_width=True,
            hide_index=True,
        )

    st.caption("매시간 자동 갱신 · alternative.me")
