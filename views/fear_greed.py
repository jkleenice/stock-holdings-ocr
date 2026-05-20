from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from holdings_ocr.market_sentiment import (
    FearGreedPanelViewModel,
    bar_color,
    build_fng_panel_view_model,
    fetch_fng_raw,
    fng_history_as_of,
    korean_label,
    market_status_summary,
)


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_fng(limit: int = 30) -> list[dict]:
    """Cached wrapper around the Fear & Greed API (1 hour TTL)."""
    return fetch_fng_raw(limit=limit)


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
            "bar": {"color": bar_color(value), "thickness": 0.25},
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


def _render_fng_panel(view_model: FearGreedPanelViewModel) -> None:
    st.subheader("기준일 코인 공포·탐욕")
    if not view_model.has_data or view_model.value is None:
        st.warning("기준일에 사용할 공포·탐욕 지수 데이터가 없어요")
        return

    st.plotly_chart(
        _fng_gauge_figure(view_model.value, view_model.label_ko, view_model.classification),
        width="stretch",
    )

    def _safe_metric(col, label: str, value: int | str, delta: int | None) -> None:
        if value == "—":
            col.metric(label, "데이터 없음")
        else:
            col.metric(label, value, delta)

    c1, c2, c3 = st.columns(3)
    for col, metric in zip((c1, c2, c3), view_model.metrics):
        _safe_metric(col, metric.label, metric.value, metric.delta)
    st.caption(
        f"지표 기준일: {view_model.as_of_date} · "
        "공포·탐욕 지수는 손익과 무관한 시장 심리 지표예요"
    )


def _render_fng_history(view_model: FearGreedPanelViewModel) -> None:
    if not view_model.history_rows:
        return

    with st.expander("공포·탐욕 기준일 이전 30개 추이"):
        df = pd.DataFrame(view_model.history_rows)
        st.line_chart(df.set_index("날짜")["지수"], height=240)
        st.dataframe(
            df.assign(분류=df["분류"].map(lambda c: f"{korean_label(c)} ({c})")),
            width="stretch",
            hide_index=True,
        )
        st.caption("매시간 자동 갱신 · alternative.me")


def render() -> None:
    st.title("😱 시장 심리·고점 대비 하락률")
    st.caption("코인 공포·탐욕 지수와 저장한 티커들의 기준일 최고점 대비 하락률을 한 화면에서 봅니다")

    from views import drawdown

    tracked, period, as_of_date = drawdown.render_drawdown_controls(
        key_prefix="market_drawdown",
        show_period=False,
    )

    try:
        data = fng_history_as_of(_fetch_fng(limit=0), as_of_date)
    except Exception:
        st.error("잠시 후 다시 시도해주세요. 지수 서버에 일시적으로 연결되지 않아요.")
        data = []
    fng_view_model = build_fng_panel_view_model(data)

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

    st.info(market_status_summary(data, rows))

    left, right = st.columns([1.15, 0.85])
    with left:
        _render_fng_panel(fng_view_model)
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

    _render_fng_history(build_fng_panel_view_model(data[:30]))
