from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from holdings_ocr.categorizer import categorize, category_pnl_summary, category_totals
from holdings_ocr.extractor import MODEL, extract_from_image
from holdings_ocr.reporter import build_report, render_markdown
from holdings_ocr.schemas import HoldingsSnapshot


st.set_page_config(page_title="Holdings OCR", layout="wide", page_icon="📊")

# iOS "Add to Home Screen" PWA hints. Streamlit injects these into the body but
# iOS Safari still respects apple-* meta tags wherever they appear.
st.markdown(
    """
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="default">
    <meta name="apple-mobile-web-app-title" content="Holdings">
    <meta name="theme-color" content="#4C78A8">
    """,
    unsafe_allow_html=True,
)

st.title("📊 Stock Holdings OCR")
st.caption("여러 증권사 스크린샷 → 주식명·보유금액·손익액·손익률을 하나의 표로 통합")


with st.sidebar:
    st.subheader("설정")
    if os.environ.get("OPENAI_API_KEY"):
        st.success("OPENAI_API_KEY 감지됨")
    else:
        st.error("OPENAI_API_KEY 미설정")
        st.caption("터미널에서 `export OPENAI_API_KEY=...` 후 streamlit을 재실행하세요.")
    model = st.text_input("VLM 모델", value=MODEL, help="gpt-4o 권장")
    st.divider()
    st.caption("이미지 1장당 약 $0.005–$0.015 (gpt-4o 기준)")


uploaded_files = st.file_uploader(
    "증권사 스크린샷 (여러 장 업로드 가능)",
    type=["png", "jpg", "jpeg", "webp", "gif"],
    accept_multiple_files=True,
)

if not uploaded_files:
    st.info("이미지를 한 장 이상 업로드하면 자동으로 분석이 시작됩니다.")
    st.stop()


@st.cache_data(show_spinner=False)
def _extract_cached(image_bytes: bytes, filename: str, model_id: str) -> str:
    suffix = Path(filename).suffix or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(image_bytes)
        tmp_path = Path(tf.name)
    try:
        snapshot = extract_from_image(tmp_path, model=model_id)
        return snapshot.model_dump_json(indent=2)
    finally:
        tmp_path.unlink(missing_ok=True)


def _format_money(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}원"


def _format_pnl(value: Decimal | None) -> str:
    if value is None:
        return "-"
    if value > 0:
        return f"▲ {value:,}원"
    if value < 0:
        return f"▼ {abs(value):,}원"
    return "0원"


def _format_pct(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


# ── 이미지 미리보기 ─────────────────────────────────────────────
with st.expander(f"업로드한 이미지 {len(uploaded_files)}장 보기", expanded=len(uploaded_files) <= 3):
    cols = st.columns(min(len(uploaded_files), 4))
    for idx, f in enumerate(uploaded_files):
        cols[idx % len(cols)].image(f, use_container_width=True, caption=f.name)


# ── 추출 ────────────────────────────────────────────────────────
results: list[tuple[str, HoldingsSnapshot, str]] = []
errors: list[tuple[str, str]] = []

progress = st.progress(0.0, text="VLM 호출 준비…")
for i, f in enumerate(uploaded_files, start=1):
    progress.progress((i - 1) / len(uploaded_files), text=f"분석 중: {f.name} ({i}/{len(uploaded_files)})")
    try:
        snap_json = _extract_cached(f.getvalue(), f.name, model)
        snap = HoldingsSnapshot.model_validate_json(snap_json)
        results.append((f.name, snap, snap_json))
    except Exception as exc:
        errors.append((f.name, str(exc)))
progress.progress(1.0, text=f"완료: {len(results)}장 성공 / {len(errors)}장 실패")

for name, err in errors:
    st.error(f"❌ {name}: {err}")

if not results:
    st.stop()


# ── 통합 표 ─────────────────────────────────────────────────────
show_source = len(results) > 1
rows = []
for source_name, snap, _ in results:
    for h in snap.holdings:
        row = {
            "주식명": h.raw_name,
            "보유금액": _format_money(h.market_value),
            "손익액": _format_pnl(h.unrealized_pnl),
            "손익률": _format_pct(h.unrealized_pnl_pct),
        }
        if show_source:
            row["출처"] = source_name
        rows.append(row)

st.subheader("통합 추출 결과")
total_holdings = sum(len(snap.holdings) for _, snap, _ in results)
st.caption(f"이미지 {len(results)}장에서 {total_holdings}개 종목 추출")

df = pd.DataFrame(rows)
st.dataframe(df, use_container_width=True, hide_index=True)

st.download_button(
    "통합 결과 CSV 다운로드",
    data=df.to_csv(index=False).encode("utf-8-sig"),
    file_name="holdings_combined.csv",
    mime="text/csv",
)


# ── 카테고리별 합산 ────────────────────────────────────────────
st.subheader("카테고리별 합산")
st.caption("`data/categories.yaml`에 정의된 분류 기준. 한 종목은 한 카테고리에만 속합니다.")

all_holdings = [h for _, snap, _ in results for h in snap.holdings]
try:
    cat_buckets, uncategorized = categorize(all_holdings)
except ValueError as exc:
    st.error(f"카테고리 정의 오류: {exc}")
    st.stop()

totals = category_totals(cat_buckets)
pnl_summary = category_pnl_summary(cat_buckets)
grand_total = sum(totals.values(), Decimal(0))

cat_rows = []
for cat, holdings in cat_buckets.items():
    total = totals[cat]
    weight = (total / grand_total * Decimal("100")) if grand_total > 0 else Decimal(0)
    cat_pnl, cat_return = pnl_summary[cat]
    cat_rows.append({
        "카테고리": cat,
        "총 보유금액": _format_money(total),
        "비중": f"{weight:.2f}%",
        "총 손익액": _format_pnl(cat_pnl),
        "수익률": _format_pct(cat_return),
        "종목 수": len(holdings),
        "포함 종목": ", ".join(sorted({h.raw_name for h in holdings})),
        "_sort": total,
    })
cat_rows.sort(key=lambda r: r["_sort"], reverse=True)
for r in cat_rows:
    del r["_sort"]

if cat_rows:
    cat_df = pd.DataFrame(cat_rows)
    st.dataframe(cat_df, use_container_width=True, hide_index=True)

    sort_mode = st.radio(
        "차트 기준",
        options=["금액", "수익률", "수익률 + 보유", "금액 + 원금"],
        horizontal=True,
        key="chart_sort_mode",
    )

    if sort_mode == "금액":
        chart_rows = [
            {"카테고리": cat, "금액": float(totals[cat])}
            for cat in cat_buckets
        ]
        chart_rows.sort(key=lambda x: x["금액"], reverse=True)
        if chart_rows:
            chart_df = pd.DataFrame(chart_rows)
            ordered_categories = chart_df["카테고리"].tolist()
            chart = (
                alt.Chart(chart_df)
                .mark_bar()
                .encode(
                    x=alt.X("카테고리:N", sort=ordered_categories, title=None),
                    y=alt.Y("금액:Q", title="금액 (원)"),
                    tooltip=[
                        alt.Tooltip("카테고리:N"),
                        alt.Tooltip("금액:Q", format=",.0f"),
                    ],
                )
                .properties(height=300)
            )
            st.altair_chart(chart, use_container_width=True)
    elif sort_mode == "수익률":
        chart_rows = []
        for cat in cat_buckets:
            _, ret = pnl_summary[cat]
            if ret is not None:
                chart_rows.append({
                    "카테고리": cat,
                    "수익률": float(ret),
                    "보유금액": float(totals[cat]),
                })
        chart_rows.sort(key=lambda x: x["수익률"], reverse=True)

        if chart_rows:
            chart_df = pd.DataFrame(chart_rows)
            ordered_categories = chart_df["카테고리"].tolist()
            chart = (
                alt.Chart(chart_df)
                .mark_circle(opacity=0.85)
                .encode(
                    x=alt.X("카테고리:N", sort=ordered_categories, title=None),
                    y=alt.Y("수익률:Q", title="수익률 (%)"),
                    size=alt.Size(
                        "보유금액:Q",
                        title="보유금액 (원)",
                        scale=alt.Scale(range=[150, 2500]),
                        legend=alt.Legend(format=",.0f"),
                    ),
                    color=alt.condition(
                        alt.datum["수익률"] < 0,
                        alt.value("#e45756"),
                        alt.value("#54a24b"),
                    ),
                    tooltip=[
                        alt.Tooltip("카테고리:N"),
                        alt.Tooltip("수익률:Q", format=".2f", title="수익률 (%)"),
                        alt.Tooltip("보유금액:Q", format=",.0f", title="보유금액 (원)"),
                    ],
                )
                .properties(height=350)
            )
            st.altair_chart(chart, use_container_width=True)
            st.caption("원 크기 = 보유금액, 색상 = 수익률 부호 (초록=수익, 빨강=손실)")
        else:
            st.info("수익률 데이터가 있는 카테고리가 없습니다.")
    elif sort_mode == "수익률 + 보유":
        chart_rows = []
        for cat in cat_buckets:
            _, ret = pnl_summary[cat]
            chart_rows.append({
                "카테고리": cat,
                "보유금액": float(totals[cat]),
                "수익률": float(ret) if ret is not None else None,
            })
        chart_rows.sort(key=lambda x: x["보유금액"], reverse=True)

        if chart_rows:
            chart_df = pd.DataFrame(chart_rows)
            ordered_categories = chart_df["카테고리"].tolist()
            bars = (
                alt.Chart(chart_df)
                .mark_bar(color="#7AAEDB", opacity=0.7)
                .encode(
                    x=alt.X("카테고리:N", sort=ordered_categories, title=None),
                    y=alt.Y("보유금액:Q", title="보유금액 (원)", axis=alt.Axis(format=",.0f")),
                    tooltip=[
                        alt.Tooltip("카테고리:N"),
                        alt.Tooltip("보유금액:Q", format=",.0f", title="보유금액 (원)"),
                        alt.Tooltip("수익률:Q", format=".2f", title="수익률 (%)"),
                    ],
                )
            )
            dots = (
                alt.Chart(chart_df)
                .mark_circle(size=220, opacity=0.95)
                .encode(
                    x=alt.X("카테고리:N", sort=ordered_categories),
                    y=alt.Y(
                        "수익률:Q",
                        title="수익률 (%)",
                        axis=alt.Axis(orient="right"),
                    ),
                    color=alt.condition(
                        alt.datum["수익률"] < 0,
                        alt.value("#e45756"),
                        alt.value("#54a24b"),
                    ),
                    tooltip=[
                        alt.Tooltip("카테고리:N"),
                        alt.Tooltip("수익률:Q", format=".2f", title="수익률 (%)"),
                    ],
                )
            )
            chart = (
                alt.layer(bars, dots)
                .resolve_scale(y="independent")
                .properties(height=380)
            )
            st.altair_chart(chart, use_container_width=True)
            st.caption("막대 = 보유금액 (왼쪽 축, 큰 금액 순) · 원 = 수익률 (오른쪽 축, 초록/빨강)")
    else:  # 금액 + 원금
        chart_rows = []
        skipped: list[str] = []
        for cat in cat_buckets:
            market = totals[cat]
            pnl, _ = pnl_summary[cat]
            if pnl is None:
                skipped.append(cat)
                continue
            cost = market - pnl
            chart_rows.append({
                "카테고리": cat,
                "보유금액": float(market),
                "원금": float(cost),
            })
        chart_rows.sort(key=lambda x: x["보유금액"], reverse=True)

        if chart_rows:
            long_rows = []
            label_rows = []
            for r in chart_rows:
                long_rows.append({"카테고리": r["카테고리"], "구분": "원금", "금액": r["원금"]})
                long_rows.append({"카테고리": r["카테고리"], "구분": "보유금액", "금액": r["보유금액"]})
                profit = r["보유금액"] - r["원금"]
                sign = "+" if profit >= 0 else "−"
                label_rows.append({
                    "카테고리": r["카테고리"],
                    "위치": max(r["보유금액"], r["원금"]),
                    "수익금": profit,
                    "라벨": f"{sign}{abs(profit):,.0f}원",
                })
            long_df = pd.DataFrame(long_rows)
            label_df = pd.DataFrame(label_rows)
            ordered_categories = [r["카테고리"] for r in chart_rows]
            bars = (
                alt.Chart(long_df)
                .mark_bar()
                .encode(
                    x=alt.X("카테고리:N", sort=ordered_categories, title=None),
                    xOffset=alt.XOffset("구분:N", sort=["원금", "보유금액"]),
                    y=alt.Y("금액:Q", title="금액 (원)", axis=alt.Axis(format=",.0f")),
                    color=alt.Color(
                        "구분:N",
                        scale=alt.Scale(
                            domain=["원금", "보유금액"],
                            range=["#B0B0B0", "#4C78A8"],
                        ),
                        legend=alt.Legend(title=None, orient="top"),
                    ),
                    tooltip=[
                        alt.Tooltip("카테고리:N"),
                        alt.Tooltip("구분:N"),
                        alt.Tooltip("금액:Q", format=",.0f", title="금액 (원)"),
                    ],
                )
            )
            profit_labels = (
                alt.Chart(label_df)
                .mark_text(
                    align="center",
                    baseline="bottom",
                    dy=-6,
                    fontSize=11,
                    fontWeight="bold",
                )
                .encode(
                    x=alt.X("카테고리:N", sort=ordered_categories),
                    y=alt.Y("위치:Q"),
                    text=alt.Text("라벨:N"),
                    color=alt.condition(
                        alt.datum["수익금"] < 0,
                        alt.value("#c44545"),
                        alt.value("#2e7d32"),
                    ),
                )
            )
            chart = (bars + profit_labels).properties(height=400)
            st.altair_chart(chart, use_container_width=True)
            st.caption("회색 = 원금 · 파랑 = 현재 보유금액 · 막대 위 숫자 = 수익금 (초록=수익, 빨강=손실)")
        if skipped:
            st.caption(f"⚠️ 손익 정보가 없어 원금을 계산할 수 없는 카테고리는 제외됨: {', '.join(skipped)}")
else:
    st.info("분류된 종목이 없습니다.")

if uncategorized:
    with st.expander(f"⚠️ 미분류 {len(uncategorized)}개 — `data/categories.yaml`에 추가하면 자동 합산됩니다"):
        for h in uncategorized:
            st.text(f"• {h.raw_name}  ({_format_money(h.market_value)})")


# ── 상세 / 디버그 ──────────────────────────────────────────────
with st.expander("상세 / 디버그"):
    # 발행사 단위 합산: 모든 holdings를 하나의 가짜 스냅샷으로 합쳐서 시도
    merged = HoldingsSnapshot(
        source=" + ".join(name for name, _, _ in results),
        extracted_at=datetime.now(timezone.utc),
        holdings=[h for _, snap, _ in results for h in snap.holdings],
    )
    try:
        report = build_report(merged)
        st.markdown("**발행사 단위 합산 리포트 (전체 이미지 통합)**")
        st.markdown(render_markdown(report))
    except Exception as exc:
        st.warning(f"합산 리포트 생성 실패: {exc}")
        st.caption("이미지마다 통화가 다른 경우 등에서 발생할 수 있습니다.")

    st.markdown("**이미지별 스냅샷 / 원본 텍스트**")
    tabs = st.tabs([name for name, _, _ in results])
    for tab, (name, snap, snap_json) in zip(tabs, results):
        with tab:
            st.code(snap_json, language="json")
            st.markdown("원본 텍스트 (audit)")
            st.text(snap.raw_text or "(없음)")
            st.download_button(
                f"{name} 스냅샷 다운로드 (.json)",
                data=snap_json,
                file_name=f"{Path(name).stem}_snapshot.json",
                mime="application/json",
                key=f"dl_{name}",
            )
