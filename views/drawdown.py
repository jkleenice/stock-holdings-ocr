from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from holdings_ocr.drawdown import (
    TRACKED_TICKERS_SESSION_KEY,
    load_tracked_tickers,
    parse_ticker_input,
    save_tracked_tickers,
)
from holdings_ocr.drawdown_service import (
    PERIOD_LABELS,
    build_drawdown_rows,
    drawdown_amount,
    drawdown_color,
    drawdown_label,
    fetch_close_prices_raw,
    format_price,
)


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_close_prices(yf_symbol: str, period: str) -> pd.Series:
    return fetch_close_prices_raw(yf_symbol, period)


def _gauge_figure(row: dict) -> go.Figure:
    amount = drawdown_amount(row["기준일 하락률"])
    color = drawdown_color(amount)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=amount,
            number={"suffix": "%", "font": {"size": 34, "color": "#111827"}},
            title={
                "text": (
                    f"<b>{row['티커']}</b><br>"
                    f"<span style='font-size:0.72em;color:#6b7280'>"
                    f"{drawdown_label(amount)} · 고점 {row['고점 날짜']}"
                    "</span>"
                ),
                "font": {"size": 17},
            },
            gauge={
                "axis": {
                    "range": [0, 80],
                    "tickvals": [0, 15, 30, 50, 80],
                    "ticktext": ["0", "15", "30", "50", "80+"],
                    "tickwidth": 1,
                },
                "bar": {"color": color, "thickness": 0.28},
                "bgcolor": "#f3f4f6",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 5], "color": "#d9f2df"},
                    {"range": [5, 15], "color": "#fcf3cf"},
                    {"range": [15, 30], "color": "#fdebd0"},
                    {"range": [30, 80], "color": "#fadbd8"},
                ],
                "threshold": {
                    "line": {"color": "#111827", "width": 3},
                    "thickness": 0.78,
                    "value": min(amount, 80),
                },
            },
        )
    )
    fig.update_layout(
        height=245,
        margin=dict(l=18, r=18, t=62, b=12),
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "Arial, sans-serif"},
    )
    return fig


def _tracked_tickers() -> list[str]:
    if TRACKED_TICKERS_SESSION_KEY not in st.session_state:
        st.session_state[TRACKED_TICKERS_SESSION_KEY] = load_tracked_tickers()
    return list(st.session_state[TRACKED_TICKERS_SESSION_KEY])


def render_drawdown_controls(
    *,
    key_prefix: str = "drawdown",
    show_period: bool = True,
) -> tuple[list[str], str, date]:
    tracked = _tracked_tickers()
    with st.expander("추적 티커 편집", expanded=not tracked):
        if show_period:
            period = st.selectbox(
                "고점 기준 기간",
                options=list(PERIOD_LABELS),
                index=3,
                format_func=lambda key: PERIOD_LABELS[key],
                key=f"{key_prefix}_period",
            )
        else:
            period = "max"

        as_of_date = st.date_input(
            "기준일",
            value=date.today(),
            max_value=date.today(),
            key=f"{key_prefix}_as_of_date",
            help=(
                "선택한 날짜 이전 마지막 거래일 가격을 기준으로 전체 과거 고점 대비 하락률을 계산합니다."
                if not show_period
                else "선택한 날짜 이전 마지막 거래일 가격을 기준으로 선택 기간의 고점 대비 하락률을 계산합니다."
            ),
        )

        with st.form(f"{key_prefix}_tickers_form"):
            ticker_text = st.text_area(
                "추적할 티커",
                value="\n".join(tracked),
                height=140,
                placeholder="AAPL\nMSFT\nNVDA\nQQQ\nBTC-USD",
                help="쉼표, 공백, 줄바꿈으로 여러 티커를 입력할 수 있어요. 005930처럼 6자리 숫자는 005930.KS로 조회합니다.",
            )
            saved = st.form_submit_button("저장", type="primary", width="stretch")

        if saved:
            parsed = parse_ticker_input(ticker_text)
            st.session_state[TRACKED_TICKERS_SESSION_KEY] = parsed
            save_tracked_tickers(parsed)
            _fetch_close_prices.clear()
            st.rerun()

        if st.button("가격 새로고침", width="stretch", key=f"{key_prefix}_refresh"):
            _fetch_close_prices.clear()
            st.rerun()

    return tracked, period, as_of_date


def load_drawdown_rows(
    tracked: list[str],
    period: str,
    as_of_date: date | str | pd.Timestamp | None = None,
) -> tuple[list[dict], list[tuple[str, str]]]:
    return build_drawdown_rows(
        tracked,
        period,
        as_of_date,
        fetch_close_prices=_fetch_close_prices,
    )


def render_drawdown_top3(rows: list[dict]) -> None:
    st.subheader("가장 많이 빠진 티커")
    if not rows:
        st.info("추적 티커를 등록하면 여기서 하락률 TOP 3를 바로 볼 수 있어요.")
        return

    for rank, row in enumerate(rows[:3], start=1):
        amount = drawdown_amount(row["기준일 하락률"])
        st.markdown(f"**{rank}. {row['티커']}**")
        st.progress(
            min(amount / 80, 1.0),
            text=(
                f"고점 대비 -{amount:.2f}% · "
                f"회복 필요 +{row['회복 필요 상승률']:.2f}%"
            ),
        )
        st.caption(
            f"기준가 {format_price(row['기준가'])} ({row['기준가 날짜']}) · "
            f"고점 {format_price(row['고점'])} ({row['고점 날짜']})"
        )


def render_drawdown_gauges(rows: list[dict]) -> None:
    if not rows:
        st.error("조회 가능한 티커가 없어요. 티커 표기를 확인해주세요.")
        return

    st.subheader("전체 추적 티커")
    for start in range(0, len(rows), 3):
        cols = st.columns(3)
        for col, row in zip(cols, rows[start : start + 3]):
            with col.container(border=True):
                st.plotly_chart(
                    _gauge_figure(row),
                    width="stretch",
                    config={"displayModeBar": False},
                )
                st.caption(
                    f"기준가 {format_price(row['기준가'])} ({row['기준가 날짜']}) · "
                    f"고점 {format_price(row['고점'])} · "
                    f"회복 필요 +{row['회복 필요 상승률']:.2f}%"
                )


def render_drawdown_table(rows: list[dict]) -> None:
    if not rows:
        return

    with st.expander("하락률 상세 표"):
        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config={
                "기준가": st.column_config.NumberColumn("기준가", format="%.4f"),
                "고점": st.column_config.NumberColumn("고점", format="%.4f"),
                "기준일 하락률": st.column_config.NumberColumn(
                    "기준일 하락률",
                    format="%.2f%%",
                ),
                "회복 필요 상승률": st.column_config.NumberColumn(
                    "회복 필요 상승률",
                    format="%.2f%%",
                ),
            },
        )


def render_drawdown_failures(failures: list[tuple[str, str]]) -> None:
    if failures:
        with st.expander(f"조회 실패 {len(failures)}개"):
            for ticker, message in failures:
                st.text(f"{ticker}: {message}")


def render_drawdown_section(*, show_heading: bool = True) -> None:
    if show_heading:
        st.subheader("고점 대비 하락률")
    st.caption("직접 저장한 티커들의 기준일 가격이 최고점에서 얼마나 내려왔는지 추적해요")

    tracked, period, as_of_date = render_drawdown_controls()

    if not tracked:
        st.info("추적할 티커를 입력하고 저장해주세요.")
        st.caption("예: AAPL, MSFT, NVDA, QQQ, BTC-USD, 005930.KS")
        return

    st.caption(
        f"기준일: {as_of_date.isoformat()} · "
        + "추적 중: "
        + ", ".join(f"`{ticker}`" for ticker in tracked)
    )
    with st.spinner("추적 티커 가격을 불러오는 중..."):
        rows, failures = load_drawdown_rows(tracked, period, as_of_date)

    render_drawdown_top3(rows)
    render_drawdown_gauges(rows)
    render_drawdown_table(rows)
    render_drawdown_failures(failures)


def render() -> None:
    st.title("📉 고점 대비 하락률")
    render_drawdown_section(show_heading=False)
