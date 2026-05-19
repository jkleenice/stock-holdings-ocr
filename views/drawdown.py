from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from holdings_ocr.drawdown import (
    TRACKED_TICKERS_SESSION_KEY,
    compute_drawdown_stats,
    load_tracked_tickers,
    parse_ticker_input,
    save_tracked_tickers,
    to_yfinance_symbol,
)


PERIOD_LABELS = {
    "1y": "최근 1년",
    "3y": "최근 3년",
    "5y": "최근 5년",
    "max": "전체 기간",
}


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_close_prices(yf_symbol: str, period: str) -> pd.Series:
    df = yf.download(
        yf_symbol,
        period=period,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    return _extract_close_series(df)


def _extract_close_series(df: pd.DataFrame | None) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype=float)

    if isinstance(df.columns, pd.MultiIndex):
        close_col = next((col for col in df.columns if col[0] == "Close"), None)
        if close_col is None:
            return pd.Series(dtype=float)
        close = df[close_col]
    else:
        if "Close" not in df.columns:
            return pd.Series(dtype=float)
        close = df["Close"]

    return pd.to_numeric(close, errors="coerce").dropna()


def _format_price(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    if value >= 10:
        return f"{value:,.2f}"
    return f"{value:,.4f}"


def _drawdown_amount(drawdown_pct: float) -> float:
    return max(0.0, -drawdown_pct)


def _drawdown_color(drawdown_amount: float) -> str:
    if drawdown_amount < 5:
        return "#2ca02c"
    if drawdown_amount < 15:
        return "#e9c46a"
    if drawdown_amount < 30:
        return "#f4a261"
    return "#e45756"


def _drawdown_label(drawdown_amount: float) -> str:
    if drawdown_amount < 5:
        return "고점 근처"
    if drawdown_amount < 15:
        return "약한 조정"
    if drawdown_amount < 30:
        return "중간 조정"
    return "큰 하락"


def _gauge_figure(row: dict) -> go.Figure:
    amount = _drawdown_amount(row["오늘 하락률"])
    color = _drawdown_color(amount)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=amount,
            number={"suffix": "%", "font": {"size": 34, "color": "#111827"}},
            title={
                "text": (
                    f"<b>{row['티커']}</b><br>"
                    f"<span style='font-size:0.72em;color:#6b7280'>"
                    f"{_drawdown_label(amount)} · 고점 {row['고점 날짜']}"
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


def render_drawdown_controls(*, key_prefix: str = "drawdown") -> tuple[list[str], str]:
    tracked = _tracked_tickers()
    with st.expander("추적 티커 편집", expanded=not tracked):
        period = st.selectbox(
            "고점 기준 기간",
            options=list(PERIOD_LABELS),
            index=3,
            format_func=lambda key: PERIOD_LABELS[key],
            key=f"{key_prefix}_period",
        )

        with st.form(f"{key_prefix}_tickers_form"):
            ticker_text = st.text_area(
                "추적할 티커",
                value="\n".join(tracked),
                height=140,
                placeholder="AAPL\nMSFT\nNVDA\nQQQ\nBTC-USD",
                help="쉼표, 공백, 줄바꿈으로 여러 티커를 입력할 수 있어요. 005930처럼 6자리 숫자는 005930.KS로 조회합니다.",
            )
            saved = st.form_submit_button("저장", type="primary", use_container_width=True)

        if saved:
            parsed = parse_ticker_input(ticker_text)
            st.session_state[TRACKED_TICKERS_SESSION_KEY] = parsed
            save_tracked_tickers(parsed)
            _fetch_close_prices.clear()
            st.rerun()

        if st.button("가격 새로고침", use_container_width=True, key=f"{key_prefix}_refresh"):
            _fetch_close_prices.clear()
            st.rerun()

    return tracked, period


def load_drawdown_rows(
    tracked: list[str],
    period: str,
) -> tuple[list[dict], list[tuple[str, str]]]:
    rows: list[dict] = []
    failures: list[tuple[str, str]] = []

    for ticker in tracked:
        yf_symbol = to_yfinance_symbol(ticker)
        try:
            close = _fetch_close_prices(yf_symbol, period)
            stats = compute_drawdown_stats(close)
        except Exception as exc:  # noqa: BLE001
            failures.append((ticker, str(exc)))
            continue

        rows.append(
            {
                "티커": ticker,
                "조회 티커": yf_symbol,
                "현재가": stats.current_price,
                "고점": stats.peak_price,
                "고점 날짜": stats.peak_date.date().isoformat(),
                "오늘 하락률": stats.drawdown_pct,
                "회복 필요 상승률": stats.recovery_pct,
            }
        )

    rows.sort(key=lambda row: _drawdown_amount(row["오늘 하락률"]), reverse=True)
    return rows, failures


def render_drawdown_top3(rows: list[dict]) -> None:
    st.subheader("가장 많이 빠진 티커")
    if not rows:
        st.info("추적 티커를 등록하면 여기서 하락률 TOP 3를 바로 볼 수 있어요.")
        return

    for rank, row in enumerate(rows[:3], start=1):
        amount = _drawdown_amount(row["오늘 하락률"])
        st.markdown(f"**{rank}. {row['티커']}**")
        st.progress(
            min(amount / 80, 1.0),
            text=(
                f"고점 대비 -{amount:.2f}% · "
                f"회복 필요 +{row['회복 필요 상승률']:.2f}%"
            ),
        )
        st.caption(
            f"오늘 {_format_price(row['현재가'])} · "
            f"고점 {_format_price(row['고점'])} ({row['고점 날짜']})"
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
                    use_container_width=True,
                    config={"displayModeBar": False},
                )
                st.caption(
                    f"오늘 {_format_price(row['현재가'])} · "
                    f"고점 {_format_price(row['고점'])} · "
                    f"회복 필요 +{row['회복 필요 상승률']:.2f}%"
                )


def render_drawdown_table(rows: list[dict]) -> None:
    if not rows:
        return

    with st.expander("하락률 상세 표"):
        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "현재가": st.column_config.NumberColumn("현재가", format="%.4f"),
                "고점": st.column_config.NumberColumn("고점", format="%.4f"),
                "오늘 하락률": st.column_config.NumberColumn("오늘 하락률", format="%.2f%%"),
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
    st.caption("직접 저장한 티커들의 오늘 가격이 최고점에서 얼마나 내려왔는지 추적해요")

    tracked, period = render_drawdown_controls()

    if not tracked:
        st.info("추적할 티커를 입력하고 저장해주세요.")
        st.caption("예: AAPL, MSFT, NVDA, QQQ, BTC-USD, 005930.KS")
        return

    st.caption("추적 중: " + ", ".join(f"`{ticker}`" for ticker in tracked))
    with st.spinner("추적 티커 가격을 불러오는 중..."):
        rows, failures = load_drawdown_rows(tracked, period)

    render_drawdown_top3(rows)
    render_drawdown_gauges(rows)
    render_drawdown_table(rows)
    render_drawdown_failures(failures)


def render() -> None:
    st.title("📉 고점 대비 하락률")
    render_drawdown_section(show_heading=False)
