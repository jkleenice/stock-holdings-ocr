from __future__ import annotations

import hashlib
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import altair as alt
import openai
import pandas as pd
import streamlit as st

from holdings_ocr.categorizer import categorize, category_pnl_summary, category_totals
from holdings_ocr.extractor import EXTRACTION_PROMPT, MODEL, extract_from_image
from holdings_ocr.reporter import build_report, render_markdown
from holdings_ocr.schemas import HoldingsSnapshot

# Cache invalidates automatically when the extraction prompt changes.
PROMPT_FINGERPRINT = hashlib.sha256(EXTRACTION_PROMPT.encode("utf-8")).hexdigest()[:16]

# On-disk cache of OCR results. Survives Streamlit's in-memory cache eviction
# within the container lifetime. Gitignored — never committed to a public repo.
CACHE_DIR = Path(".cache/holdings-ocr/snapshots")


def _content_hash(image_bytes: bytes, model_id: str, prompt_fp: str) -> str:
    """Stable content-addressed key. Same image + model + prompt → same hash."""
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(b"\x00")
    h.update(model_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(prompt_fp.encode("utf-8"))
    return h.hexdigest()


def _extract_to_snapshot_json(image_bytes: bytes, suffix: str, model_id: str) -> str:
    """Pure: bytes → API call → snapshot JSON. No caching."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(image_bytes)
        tmp_path = Path(tf.name)
    try:
        snapshot = extract_from_image(tmp_path, model=model_id)
        return snapshot.model_dump_json(indent=2)
    finally:
        tmp_path.unlink(missing_ok=True)


def _extract_with_disk_cache(
    image_bytes: bytes,
    suffix: str,
    model_id: str,
    prompt_fp: str,
    cache_dir: Path = CACHE_DIR,
) -> str:
    """Disk cache layer — read existing file on hit, write on miss. No API on hit."""
    cache_key = _content_hash(image_bytes, model_id, prompt_fp)
    cache_file = cache_dir / f"{cache_key}.json"
    if cache_file.exists():
        try:
            return cache_file.read_text(encoding="utf-8")
        except OSError:
            pass  # corrupt/unreadable — fall through to re-extract

    snapshot_json = _extract_to_snapshot_json(image_bytes, suffix, model_id)

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(snapshot_json, encoding="utf-8")
    except OSError:
        pass  # disk write failure must not break the response

    return snapshot_json


@st.cache_data(show_spinner=False)
def _extract_cached(image_bytes: bytes, suffix: str, model_id: str, prompt_fp: str) -> str:
    """In-memory cache wrapping the disk cache wrapping the API."""
    return _extract_with_disk_cache(image_bytes, suffix, model_id, prompt_fp)


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
    # 의도적으로 ▲/▼ 부호 없이 표시 — 변동 없음을 시각적으로 구분
    return "0원"


def _format_pct(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def render() -> None:
    st.title("📊 내 보유종목")
    st.caption("여러 증권사 스크린샷을 한 번에 합쳐서 보여드려요")

    with st.sidebar:
        st.subheader("분석 설정")
        if os.environ.get("OPENAI_API_KEY"):
            st.success("분석 준비 완료")
        else:
            st.error("분석 키가 설정되지 않았어요")
            st.caption("관리자에게 문의해주세요")
        model = st.text_input("분석 모델", value=MODEL, help="gpt-4o 권장")

    uploaded_files = st.file_uploader(
        "증권사 앱 캡처 (여러 장 가능)",
        type=["png", "jpg", "jpeg", "webp", "gif"],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        st.info("증권사 앱 캡처를 올려주세요. 자동으로 분석할게요.")
        return

    # ── 이미지 미리보기 ─────────────────────────────────────────────
    with st.expander(f"올린 이미지 {len(uploaded_files)}장", expanded=len(uploaded_files) <= 3):
        cols = st.columns(min(len(uploaded_files), 4))
        for idx, f in enumerate(uploaded_files):
            cols[idx % len(cols)].image(f, use_container_width=True, caption=f.name)

    # ── 추출 (병렬 호출) ───────────────────────────────────────────
    results: list[tuple[str, HoldingsSnapshot, str]] = []
    errors: list[tuple[str, str]] = []

    original_order = {f.name: i for i, f in enumerate(uploaded_files)}
    total = len(uploaded_files)
    progress = st.progress(0.0, text=f"분석 중... (0/{total})")
    done = 0

    def _extract_one(uploaded) -> tuple[str, str | None, str | None, float]:
        suffix = Path(uploaded.name).suffix or ".png"
        t0 = time.perf_counter()
        try:
            snap_json = _extract_cached(
                uploaded.getvalue(), suffix, model, PROMPT_FINGERPRINT
            )
            return (uploaded.name, snap_json, None, time.perf_counter() - t0)
        except openai.AuthenticationError:
            return (uploaded.name, None, "OpenAI 인증 실패 — Streamlit Secrets의 OPENAI_API_KEY 확인", time.perf_counter() - t0)
        except openai.RateLimitError:
            return (uploaded.name, None, "OpenAI 호출 한도 초과 — 잠시 후 다시 시도", time.perf_counter() - t0)
        except openai.APITimeoutError:
            return (uploaded.name, None, "OpenAI 응답 시간 초과 — 다시 시도", time.perf_counter() - t0)
        except Exception as exc:  # noqa: BLE001
            return (uploaded.name, None, str(exc), time.perf_counter() - t0)

    wall_start = time.perf_counter()
    per_task_elapsed: list[tuple[str, float]] = []
    with ThreadPoolExecutor(max_workers=min(total, 4)) as executor:
        future_to_file = {executor.submit(_extract_one, f): f for f in uploaded_files}
        for future in as_completed(future_to_file):
            name, snap_json, err, elapsed = future.result()
            per_task_elapsed.append((name, elapsed))
            done += 1
            progress.progress(done / total, text=f"분석 중... ({done}/{total})")
            if err is not None:
                errors.append((name, err))
            else:
                snap = HoldingsSnapshot.model_validate_json(snap_json)
                results.append((name, snap, snap_json))
    wall_elapsed = time.perf_counter() - wall_start

    results.sort(key=lambda r: original_order[r[0]])
    errors.sort(key=lambda e: original_order[e[0]])
    progress.progress(1.0, text=f"{len(results)}장 분석 완료")

    # 진단용: 벽시계 vs 각 작업 합계. 병렬이면 wall ≪ sum.
    sum_elapsed = sum(t for _, t in per_task_elapsed)
    parallelism_hint = "병렬 ✓" if wall_elapsed < sum_elapsed * 0.7 else "직렬 의심 ⚠️"
    st.caption(
        f"⏱ 전체 {wall_elapsed:.1f}초 · 각 합계 {sum_elapsed:.1f}초 · {parallelism_hint}"
    )

    for name, err in errors:
        with st.container():
            st.warning(f"⚠️  {name} 분석에 실패했어요. 잠시 후 다시 올려주세요.")
            with st.expander("자세한 오류 보기"):
                st.caption(err)

    if not results:
        return

    # ── 통합 표 ─────────────────────────────────────────────────────
    show_source = len(results) > 1
    rows = []
    for source_name, snap, _ in results:
        for h in snap.holdings:
            row = {
                "종목": h.raw_name,
                "평가금액": _format_money(h.market_value),
                "손익": _format_pnl(h.unrealized_pnl),
                "수익률": _format_pct(h.unrealized_pnl_pct),
            }
            if show_source:
                row["출처"] = source_name
            rows.append(row)

    st.subheader("전체 종목")
    total_holdings = sum(len(snap.holdings) for _, snap, _ in results)
    st.caption(
        f"{len(results)}장에서 {total_holdings}개 종목을 찾았어요 · "
        f"이번 분석 약 ${len(results) * 0.01:.2f}"
    )

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.download_button(
        "엑셀로 받기",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name="holdings_combined.csv",
        mime="text/csv",
    )

    # ── 테마별로 보기 ────────────────────────────────────────────
    st.subheader("테마별로 보기")

    all_holdings = [h for _, snap, _ in results for h in snap.holdings]
    try:
        cat_buckets, uncategorized = categorize(all_holdings)
    except ValueError as exc:
        st.error(f"카테고리 정의 오류: {exc}")
        return

    totals = category_totals(cat_buckets)
    pnl_summary = category_pnl_summary(cat_buckets)
    grand_total = sum(totals.values(), Decimal(0))

    cat_rows = []
    for cat, holdings in cat_buckets.items():
        total = totals[cat]
        weight = (total / grand_total * Decimal("100")) if grand_total > 0 else Decimal(0)
        cat_pnl, cat_return = pnl_summary[cat]
        cat_rows.append({
            "테마": cat,
            "평가금액": _format_money(total),
            "비중": f"{weight:.2f}%",
            "손익": _format_pnl(cat_pnl),
            "수익률": _format_pct(cat_return),
            "종목 수": len(holdings),
            "종목": ", ".join(sorted({h.raw_name for h in holdings})),
            "_sort": total,
        })
    cat_rows.sort(key=lambda r: r["_sort"], reverse=True)
    for r in cat_rows:
        del r["_sort"]

    if cat_rows:
        sort_mode = st.radio(
            "차트 기준",
            options=["원금 대비 현재", "평가금액", "수익률", "수익률·평가금액"],
            horizontal=True,
            key="chart_sort_mode",
        )

        cat_df = pd.DataFrame(cat_rows)
        st.dataframe(cat_df, use_container_width=True, hide_index=True)

        if sort_mode == "평가금액":
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
                st.caption("초록=수익, 빨강=손실")
            else:
                st.info("수익률 데이터가 있는 테마가 없어요")
        elif sort_mode == "수익률·평가금액":
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
                st.caption("막대=평가금액, 점=수익률 (초록=수익, 빨강=손실)")
        else:  # 원금 대비 현재
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
                st.caption("회색=원금, 파랑=평가금액, 위 숫자=손익 (초록=수익, 빨강=손실)")
            if skipped:
                st.caption(f"⚠️  손익 정보가 없는 테마는 제외됐어요: {', '.join(skipped)}")
    else:
        st.info("분류된 종목이 없어요")

    if uncategorized:
        with st.expander(f"⚠️  분류되지 않은 {len(uncategorized)}개 종목"):
            for h in uncategorized:
                st.text(f"• {h.raw_name}  ({_format_money(h.market_value)})")

    # ── 자세히 보기 ──────────────────────────────────────────────
    with st.expander("자세히 보기"):
        merged = HoldingsSnapshot(
            source=" + ".join(name for name, _, _ in results),
            extracted_at=datetime.now(timezone.utc),
            holdings=[h for _, snap, _ in results for h in snap.holdings],
        )
        try:
            report = build_report(merged)
            st.markdown("**회사별 합계**")
            st.markdown(render_markdown(report))
        except Exception as exc:
            st.warning("합계를 만들지 못했어요")
            st.caption(str(exc))

        st.markdown("**이미지별 결과**")
        tabs = st.tabs([name for name, _, _ in results])
        for tab, (name, snap, snap_json) in zip(tabs, results):
            with tab:
                st.code(snap_json, language="json")
                st.markdown("원문 텍스트")
                st.text(snap.raw_text or "(없음)")
                st.download_button(
                    f"{name} 원본 데이터 받기",
                    data=snap_json,
                    file_name=f"{Path(name).stem}_snapshot.json",
                    mime="application/json",
                    key=f"dl_{name}",
                )
