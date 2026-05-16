from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st
import yfinance as yf


@dataclass(frozen=True)
class SimulationResult:
    """Output of a single strategy simulation over a daily price series."""

    timeline: pd.DataFrame  # cols: shares, cash, value, buy(bool), invested — indexed by date
    final_value: float
    total_invested: float
    buy_count: int


def _first_trading_days_of_month(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return one date per (year, month) — the earliest trading day present in `index`."""
    if len(index) == 0:
        return pd.DatetimeIndex([])
    months = pd.PeriodIndex(index, freq="M")
    df = pd.DataFrame({"date": index, "month": months})
    firsts = df.groupby("month")["date"].min()
    return pd.DatetimeIndex(firsts.values)


def simulate_dca(prices: pd.Series, monthly_amount: float) -> SimulationResult:
    """Invest `monthly_amount` on the first trading day of each month present in `prices`."""
    if prices.empty:
        return SimulationResult(timeline=pd.DataFrame(), final_value=0.0, total_invested=0.0, buy_count=0)

    buy_days = set(_first_trading_days_of_month(prices.index))
    rows: list[dict] = []
    shares = 0.0
    cash = 0.0
    invested = 0.0
    buy_count = 0

    for date, price in prices.items():
        price_f = float(price)
        is_buy = date in buy_days and monthly_amount > 0 and price_f > 0
        if is_buy:
            shares += monthly_amount / price_f
            invested += monthly_amount
            buy_count += 1
        rows.append({
            "date": date,
            "shares": shares,
            "cash": cash,
            "value": shares * price_f + cash,
            "buy": is_buy,
            "invested": invested,
        })

    timeline = pd.DataFrame(rows).set_index("date")
    return SimulationResult(
        timeline=timeline,
        final_value=float(timeline["value"].iloc[-1]),
        total_invested=float(timeline["invested"].iloc[-1]),
        buy_count=buy_count,
    )


def simulate_vix_lumpsum(
    prices: pd.Series,
    vix: pd.Series,
    monthly_amount: float,
    vix_threshold: float,
) -> SimulationResult:
    """Accrue `monthly_amount` monthly as cash. When VIX >= threshold, buy with entire cash balance."""
    if prices.empty:
        return SimulationResult(timeline=pd.DataFrame(), final_value=0.0, total_invested=0.0, buy_count=0)

    common = prices.index.intersection(vix.index)
    p = prices.loc[common]
    v = vix.loc[common]
    accrual_days = set(_first_trading_days_of_month(common))

    rows: list[dict] = []
    shares = 0.0
    cash = 0.0
    invested = 0.0
    buy_count = 0

    for date in common:
        price_f = float(p.loc[date])
        vix_f = float(v.loc[date])

        if date in accrual_days and monthly_amount > 0:
            cash += monthly_amount
            invested += monthly_amount

        is_buy = False
        if vix_f >= vix_threshold and cash > 0 and price_f > 0:
            shares += cash / price_f
            cash = 0.0
            is_buy = True
            buy_count += 1

        rows.append({
            "date": date,
            "shares": shares,
            "cash": cash,
            "value": shares * price_f + cash,
            "buy": is_buy,
            "invested": invested,
        })

    timeline = pd.DataFrame(rows).set_index("date")
    return SimulationResult(
        timeline=timeline,
        final_value=float(timeline["value"].iloc[-1]),
        total_invested=float(timeline["invested"].iloc[-1]),
        buy_count=buy_count,
    )


def compute_cagr(start_value: float, end_value: float, years: float) -> float:
    """Compound annual growth rate. Returns 0 for nonsensical inputs."""
    if start_value <= 0 or years <= 0 or end_value <= 0:
        return 0.0
    return (end_value / start_value) ** (1.0 / years) - 1.0


def _fetch_history_raw(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Pull daily close prices via yfinance. Returns DataFrame with single 'close' column."""
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        close_col = next((c for c in df.columns if c[0] == "Close"), None)
        if close_col is None:
            return pd.DataFrame()
        close = df[close_col]
    else:
        if "Close" not in df.columns:
            return pd.DataFrame()
        close = df["Close"]

    out = pd.DataFrame({"close": close})
    out.index.name = "Date"
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_history(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Cached wrapper around `_fetch_history_raw` (1 hour TTL)."""
    return _fetch_history_raw(ticker, start, end)


def _range_scale(series: pd.Series) -> pd.Series:
    """Rescale a series to [0, 100] over its own min/max."""
    s = series.dropna()
    if s.empty:
        return series
    lo = float(s.min())
    hi = float(s.max())
    if hi == lo:
        return pd.Series([50.0] * len(series), index=series.index)
    return (series - lo) / (hi - lo) * 100.0


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
        submitted = st.form_submit_button("비교 실행", type="primary", use_container_width=True)

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

        prices = prices_df["close"]
        vix = vix_df["close"]
        common = prices.index.intersection(vix.index)
        prices = prices.loc[common]
        vix = vix.loc[common]

        if len(common) < 30:
            st.error(f"기간이 너무 짧습니다 (거래일 {len(common)}일).")
            return

        dca = simulate_dca(prices, float(monthly_amount))
        vix_strat = simulate_vix_lumpsum(
            prices, vix, float(monthly_amount), float(vix_threshold)
        )

        st.session_state["vix_result"] = {
            "prices": prices,
            "vix": vix,
            "dca": dca,
            "vix_strat": vix_strat,
            "ticker": ticker,
            "vix_threshold": float(vix_threshold),
        }

    result = st.session_state.get("vix_result")
    if not result:
        st.info("사이드바에서 시나리오를 설정하고 '비교 실행'을 눌러주세요.")
        return

    prices: pd.Series = result["prices"]
    vix: pd.Series = result["vix"]
    dca: SimulationResult = result["dca"]
    vix_strat: SimulationResult = result["vix_strat"]
    ticker: str = result["ticker"]
    vix_threshold: float = result["vix_threshold"]

    years = (prices.index.max() - prices.index.min()).days / 365.25
    cagr_dca = compute_cagr(dca.total_invested, dca.final_value, years)
    cagr_vix = compute_cagr(vix_strat.total_invested, vix_strat.final_value, years)

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
    c3.metric("CAGR 차이 (B − A)", f"{(cagr_vix - cagr_dca) * 100:+.2f}pp")

    st.caption(
        f"기간: {prices.index.min().date()} ~ {prices.index.max().date()} · "
        f"총 투자금: ${dca.total_invested:,.0f} · "
        f"매수 횟수 A={dca.buy_count}, B={vix_strat.buy_count}"
    )

    # ── Chart 1: 가격 vs VIX 정규화 ────────────────────────────
    st.subheader(f"{ticker} 가격 vs VIX (0~100 정규화)")
    norm = pd.DataFrame({
        f"{ticker} 가격": _range_scale(prices),
        "VIX": _range_scale(vix),
    })
    norm.index.name = "Date"
    norm_long = norm.reset_index().melt(id_vars=["Date"], var_name="시리즈", value_name="정규화")
    chart1 = (
        alt.Chart(norm_long)
        .mark_line()
        .encode(
            x=alt.X("Date:T", title=None),
            y=alt.Y("정규화:Q", title="0~100"),
            color=alt.Color(
                "시리즈:N",
                scale=alt.Scale(
                    domain=[f"{ticker} 가격", "VIX"], range=["#4C78A8", "#e45756"]
                ),
            ),
            tooltip=["Date:T", "시리즈:N", alt.Tooltip("정규화:Q", format=".1f")],
        )
        .properties(height=280)
    )
    st.altair_chart(chart1, use_container_width=True)

    # ── Chart 2: 자산가치 ──────────────────────────────────────
    st.subheader("자산가치 추이")
    pv = pd.DataFrame({
        "매월 매수": dca.timeline["value"],
        "VIX 일시매수": vix_strat.timeline["value"],
    })
    pv.index.name = "Date"
    pv_long = pv.reset_index().melt(id_vars=["Date"], var_name="전략", value_name="가치($)")
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
    st.altair_chart(chart2, use_container_width=True)

    # ── Chart 3: 현금 보유량 ──────────────────────────────────
    st.subheader("현금 보유량")
    cash = pd.DataFrame({
        "매월 매수": dca.timeline["cash"],
        "VIX 일시매수": vix_strat.timeline["cash"],
    })
    cash.index.name = "Date"
    cash_long = cash.reset_index().melt(id_vars=["Date"], var_name="전략", value_name="현금($)")
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
    st.altair_chart(chart3, use_container_width=True)

    # ── Chart 4: 매수 시점 마커 ───────────────────────────────
    st.subheader(f"VIX 매수 시점 (임계값 ≥ {vix_threshold:.0f})")
    price_df = prices.reset_index()
    price_df.columns = ["Date", "price"]
    buy_idx = vix_strat.timeline[vix_strat.timeline["buy"]].index
    buy_df = pd.DataFrame({"Date": buy_idx, "price": prices.reindex(buy_idx).values})

    price_line = alt.Chart(price_df).mark_line(color="#4C78A8").encode(
        x=alt.X("Date:T"),
        y=alt.Y("price:Q", title=f"{ticker} 가격 ($)"),
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
    st.altair_chart(combined, use_container_width=True)

    if vix_strat.buy_count == 0:
        st.info(
            f"이 기간 동안 VIX가 {vix_threshold:.0f}을 한 번도 넘지 않았습니다. "
            "VIX 전략은 매수 없이 현금만 누적됐습니다."
        )
