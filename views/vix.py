from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st
from holdings_ocr.vix_strategy import (
    VixComparisonViewModel,
    build_vix_comparison_view_model,
    fetch_history_raw,
)


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_history(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Cached wrapper around yfinance history fetches (1 hour TTL)."""
    return fetch_history_raw(ticker, start, end)


def render() -> None:
    st.title("📈 VIX 비교")
    st.caption(
        "**매월 정액 매수 (DCA)** vs **VIX 기준값 도달 시 일시매수** 두 전략 비교. "
        "데이터: Yahoo Finance · 1시간 캐싱 · 현금은 무이자 가정"
    )

    with st.sidebar.form("vix_form"):
        st.subheader("시나리오")
        ticker = st.text_input("티커", value="SPY").upper().strip()
        current_year = datetime.now().year
        start_year = st.number_input(
            "시작 연도", min_value=1990, max_value=current_year, value=2020, step=1
        )
        end_year = st.number_input(
            "종료 연도", min_value=1990, max_value=current_year, value=current_year, step=1
        )
        monthly_amount = st.number_input("월 투자금 ($)", min_value=1.0, value=100.0, step=10.0)
        vix_threshold = st.number_input("VIX 기준값", min_value=5.0, value=30.0, step=1.0)
        submitted = st.form_submit_button("비교 실행", type="primary", width="stretch")

    if submitted:
        st.session_state.pop("vix_result", None)
        if end_year < start_year:
            st.error("종료 연도가 시작 연도보다 빨라야 합니다.")
            return
        if not ticker:
            st.error("티커를 입력해주세요.")
            return

        start = f"{int(start_year)}-01-01"
        end = f"{int(end_year)}-12-31"

        try:
            with st.spinner(f"{ticker} + ^VIX 데이터 수집 중…"):
                prices_df = _fetch_history(ticker, start, end)
                vix_df = _fetch_history("^VIX", start, end)
        except Exception as exc:  # noqa: BLE001
            st.error(f"데이터 가져오기 실패: {exc}")
            return

        if prices_df.empty:
            st.error(f"'{ticker}' 가격 데이터를 찾을 수 없습니다.")
            return
        if vix_df.empty:
            st.error("VIX 데이터를 가져올 수 없습니다.")
            return

        try:
            st.session_state["vix_result"] = build_vix_comparison_view_model(
                ticker=ticker,
                prices=prices_df["close"],
                vix=vix_df["close"],
                monthly_amount=float(monthly_amount),
                vix_threshold=float(vix_threshold),
            )
        except ValueError as exc:
            st.error(str(exc))
            return

    result = st.session_state.get("vix_result")
    if not result:
        st.info("사이드바에서 시나리오를 설정하고 '비교 실행'을 눌러주세요.")
        return

    result: VixComparisonViewModel
    dca = result.dca
    vix_strat = result.vix_strategy

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "A. 매월 매수 최종가치",
        f"${dca.final_value:,.2f}",
        delta=f"${dca.final_value - dca.total_invested:+,.2f}",
    )
    c2.metric(
        "B. VIX 일시매수 최종가치",
        f"${vix_strat.final_value:,.2f}",
        delta=f"${vix_strat.final_value - vix_strat.total_invested:+,.2f}",
    )
    c3.metric("CAGR 차이 (B − A)", f"{(result.vix_cagr - result.dca_cagr) * 100:+.2f}pp")

    st.caption(
        f"기간: {result.start_date} ~ {result.end_date} · "
        f"총 투자금: ${dca.total_invested:,.0f} · "
        f"매수 횟수 A={dca.buy_count}, B={vix_strat.buy_count}"
    )

    # ── Chart 1: 가격 vs VIX 정규화 ────────────────────────────
    st.subheader(f"{result.ticker} 가격 vs VIX (0~100 정규화)")
    norm_long = pd.DataFrame(result.normalized_rows)
    chart1 = (
        alt.Chart(norm_long)
        .mark_line()
        .encode(
            x=alt.X("Date:T", title=None),
            y=alt.Y("정규화:Q", title="0~100"),
            color=alt.Color(
                "시리즈:N",
                scale=alt.Scale(
                    domain=[f"{result.ticker} 가격", "VIX"], range=["#4C78A8", "#e45756"]
                ),
            ),
            tooltip=["Date:T", "시리즈:N", alt.Tooltip("정규화:Q", format=".1f")],
        )
        .properties(height=280)
    )
    st.altair_chart(chart1, width="stretch")

    # ── Chart 2: 자산가치 ──────────────────────────────────────
    st.subheader("자산가치 추이")
    pv_long = pd.DataFrame(result.portfolio_rows)
    chart2 = (
        alt.Chart(pv_long)
        .mark_line()
        .encode(
            x=alt.X("Date:T", title=None),
            y=alt.Y("가치($):Q", title="$"),
            color=alt.Color(
                "전략:N",
                scale=alt.Scale(
                    domain=["매월 매수", "VIX 일시매수"], range=["#4C78A8", "#2ca02c"]
                ),
            ),
            tooltip=["Date:T", "전략:N", alt.Tooltip("가치($):Q", format=",.2f")],
        )
        .properties(height=300)
    )
    st.altair_chart(chart2, width="stretch")

    # ── Chart 3: 현금 보유량 ──────────────────────────────────
    st.subheader("현금 보유량")
    cash_long = pd.DataFrame(result.cash_rows)
    chart3 = (
        alt.Chart(cash_long)
        .mark_line()
        .encode(
            x=alt.X("Date:T", title=None),
            y=alt.Y("현금($):Q", title="$"),
            color=alt.Color(
                "전략:N",
                scale=alt.Scale(
                    domain=["매월 매수", "VIX 일시매수"], range=["#4C78A8", "#2ca02c"]
                ),
            ),
            tooltip=["Date:T", "전략:N", alt.Tooltip("현금($):Q", format=",.2f")],
        )
        .properties(height=220)
    )
    st.altair_chart(chart3, width="stretch")

    # ── Chart 4: 매수 시점 마커 ───────────────────────────────
    st.subheader(f"VIX 매수 시점 (임계값 ≥ {result.vix_threshold:.0f})")
    price_df = pd.DataFrame(result.price_rows)
    buy_df = pd.DataFrame(result.buy_marker_rows)

    price_line = alt.Chart(price_df).mark_line(color="#4C78A8").encode(
        x=alt.X("Date:T"),
        y=alt.Y("price:Q", title=f"{result.ticker} 가격 ($)"),
    )
    if not buy_df.empty:
        buy_marks = alt.Chart(buy_df).mark_point(
            size=90, color="#e45756", filled=True, opacity=0.9
        ).encode(
            x="Date:T",
            y="price:Q",
            tooltip=["Date:T", alt.Tooltip("price:Q", format=",.2f", title="매수가격")],
        )
        combined = (price_line + buy_marks).properties(height=300)
    else:
        combined = price_line.properties(height=300)
    st.altair_chart(combined, width="stretch")

    if vix_strat.buy_count == 0:
        st.info(
            f"이 기간 동안 VIX가 {result.vix_threshold:.0f}을 한 번도 넘지 않았습니다. "
            "VIX 전략은 매수 없이 현금만 누적됐습니다."
        )
