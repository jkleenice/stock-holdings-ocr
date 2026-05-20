from __future__ import annotations

from datetime import date, datetime

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


def _fng_gauge_figure(value: int, label_ko: str, classification: str) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"font": {"size": 60}},
        title={
            "text": (
                f"<b>{label_ko}</b><br>"
                f"<span style='font-size:0.8em;color:gray'>{classification}</span>"
            ),
            "font": {"size": 22},
        },
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
    return fig


def _fng_history_df(data: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "날짜": datetime.fromtimestamp(int(d["timestamp"])),
            "지수": int(d["value"]),
            "분류": d["value_classification"],
        }
        for d in reversed(data)
    ])


def _fng_item_date(item: dict) -> date:
    return datetime.fromtimestamp(int(item["timestamp"])).date()


def _fng_history_as_of(data: list[dict], as_of_date: date) -> list[dict]:
    sorted_data = sorted(data, key=lambda item: int(item["timestamp"]), reverse=True)
    return [item for item in sorted_data if _fng_item_date(item) <= as_of_date]


def _get_fng_at(data: list[dict], idx: int) -> int | None:
    if idx >= len(data):
        return None
    return int(data[idx]["value"])


def _render_fng_panel(data: list[dict]) -> None:
    st.subheader("기준일 코인 공포·탐욕")
    if not data:
        st.warning("기준일에 사용할 공포·탐욕 지수 데이터가 없어요")
        return

    current = data[0]
    value = int(current["value"])
    classification = current["value_classification"]
    label_ko = _korean_label(classification)
    st.plotly_chart(
        _fng_gauge_figure(value, label_ko, classification),
        use_container_width=True,
    )

    def _safe_metric(col, label: str, past: int | None) -> None:
        if past is None:
            col.metric(label, "데이터 없음")
        else:
            col.metric(label, past, value - past)

    c1, c2, c3 = st.columns(3)
    _safe_metric(c1, "전일", _get_fng_at(data, 1))
    _safe_metric(c2, "7일 전", _get_fng_at(data, 7))
    _safe_metric(c3, "30일 전", _get_fng_at(data, 29))
    st.caption(
        f"지표 기준일: {_fng_item_date(current).isoformat()} · "
        "공포·탐욕 지수는 손익과 무관한 시장 심리 지표예요"
    )


def _render_fng_history(data: list[dict]) -> None:
    if not data:
        return

    with st.expander("공포·탐욕 기준일 이전 30개 추이"):
        df = _fng_history_df(data)
        st.line_chart(df.set_index("날짜")["지수"], height=240)
        st.dataframe(
            df.assign(분류=df["분류"].map(lambda c: f"{_korean_label(c)} ({c})")),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("매시간 자동 갱신 · alternative.me")


def _market_status_summary(data: list[dict], drawdown_rows: list[dict]) -> str:
    parts = []
    if data:
        current = data[0]
        value = int(current["value"])
        parts.append(f"코인 심리는 {_korean_label(current['value_classification'])} {value}점")
    if drawdown_rows:
        worst = drawdown_rows[0]
        worst_amount = max(0.0, -worst["기준일 하락률"])
        parts.append(f"가장 많이 빠진 티커는 {worst['티커']} -{worst_amount:.2f}%")
    if not parts:
        return "공포·탐욕 지수 또는 추적 티커를 불러오면 기준일 상태를 한 줄로 요약해요."
    return " · ".join(parts)


def render() -> None:
    st.title("😱 시장 심리·고점 대비 하락률")
    st.caption("코인 공포·탐욕 지수와 저장한 티커들의 기준일 최고점 대비 하락률을 한 화면에서 봅니다")

    from views import drawdown

    tracked, period, as_of_date = drawdown.render_drawdown_controls(
        key_prefix="market_drawdown",
        show_period=False,
    )

    try:
        data = _fng_history_as_of(_fetch_fng(limit=0), as_of_date)
    except Exception:
        st.error("잠시 후 다시 시도해주세요. 지수 서버에 일시적으로 연결되지 않아요.")
        data = []

    rows: list[dict] = []
    failures: list[tuple[str, str]] = []
    if tracked:
        st.caption(
            f"기준일: {as_of_date.isoformat()} · "
            + "추적 중: "
            + ", ".join(f"`{ticker}`" for ticker in tracked)
        )
        with st.spinner("추적 티커 가격을 불러오는 중..."):
            rows, failures = drawdown.load_drawdown_rows(tracked, period, as_of_date)

    st.info(_market_status_summary(data, rows))

    left, right = st.columns([1.15, 0.85])
    with left:
        _render_fng_panel(data)
    with right:
        drawdown.render_drawdown_top3(rows)

    st.divider()
    if tracked:
        drawdown.render_drawdown_gauges(rows)
        drawdown.render_drawdown_table(rows)
        drawdown.render_drawdown_failures(failures)
    else:
        st.info("추적 티커를 저장하면 전체 하락률 게이지가 여기에 표시됩니다.")
        st.caption("예: AAPL, MSFT, NVDA, QQQ, BTC-USD, 005930.KS")

    _render_fng_history(data[:30])
