from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import openai
import pandas as pd
import streamlit as st

from holdings_ocr.category_rules import (
    CategoryRule,
    UncategorizedGroup,
    category_rule_id,
    delete_user_category_rule,
    load_user_category_rules,
    save_user_category_rules,
    upsert_user_category_rule,
)
from holdings_ocr.categorizer import load_categories
from holdings_ocr.extractor import MODEL
from holdings_ocr.holdings_cache import PROMPT_FINGERPRINT, extract_with_disk_cache
from holdings_ocr.holdings_service import (
    HoldingsViewModel,
    build_holdings_view_model,
    cost_basis_chart_data,
    format_money,
    market_value_chart_rows,
    return_chart_rows,
    return_value_chart_rows,
)
from holdings_ocr.holdings_storage import (
    SnapshotRecord,
    clear_current_holdings,
    load_current_holdings,
    save_current_holdings,
)
from holdings_ocr.reporter import build_report, render_markdown
from holdings_ocr.schemas import HoldingsSnapshot


@st.cache_data(show_spinner=False)
def _extract_cached(image_bytes: bytes, suffix: str, model_id: str, prompt_fp: str) -> str:
    """Streamlit memory cache around the UI-neutral disk cache."""
    return extract_with_disk_cache(image_bytes, suffix, model_id, prompt_fp)


def _save_user_category_rules_or_warn(rules: list[CategoryRule]) -> bool:
    try:
        save_user_category_rules(rules)
    except OSError as exc:
        st.warning("사용자 분류 규칙을 저장하지 못했어요.")
        st.caption(str(exc))
        return False
    return True


def _render_uncategorized_classifier(
    groups: list[UncategorizedGroup],
    category_options: list[str],
) -> None:
    if not groups:
        return

    total_count = sum(group.count for group in groups)
    st.warning(f"분류되지 않은 {total_count}개 종목이 있어요. 아래에서 테마를 직접 지정해주세요.")
    with st.container(border=True):
        st.markdown("**분류되지 않은 종목 직접 분류**")
        st.caption("테마를 저장하면 같은 종목은 다음 화면부터 자동으로 분류됩니다.")
        with st.form("uncategorized_category_form"):
            assignments: list[dict] = []
            for group in groups:
                raw_names = ", ".join(group.raw_names)
                symbols = ", ".join(group.symbols)
                display_name = f"{raw_names} ({symbols})" if symbols else raw_names
                left, middle, right = st.columns([3, 2, 2])
                left.markdown(f"**{display_name}**")
                left.caption(f"{group.count}개 · {format_money(group.market_value)}")
                selected_category = middle.selectbox(
                    "기존 테마",
                    options=["분류 안 함", *category_options],
                    key=f"category_select_{group.id}",
                )
                new_category = right.text_input(
                    "새 테마",
                    key=f"category_new_{group.id}",
                )
                assignments.append({
                    "group": group,
                    "selected_category": selected_category,
                    "new_category": new_category,
                })

            submitted = st.form_submit_button("선택한 분류 저장", type="primary")

        if submitted:
            rules = load_user_category_rules()
            saved_count = 0
            for assignment in assignments:
                group = assignment["group"]
                selected_category = str(assignment["selected_category"])
                new_category = str(assignment["new_category"]).strip()
                category = new_category or (
                    selected_category if selected_category != "분류 안 함" else ""
                )
                if not category:
                    continue

                rules = upsert_user_category_rule(
                    rules,
                    raw_name=group.raw_names[0],
                    symbol=group.symbols[0] if group.symbols else None,
                    category=category,
                    keys=list(group.keys),
                )
                saved_count += 1

            if saved_count:
                if not _save_user_category_rules_or_warn(rules):
                    return
                st.session_state["category_rules_message"] = (
                    f"{saved_count}개 종목 분류를 저장했어요."
                )
                st.rerun()
            else:
                st.warning("저장할 분류를 선택해주세요.")


def _render_user_category_rules(rules: list[CategoryRule]) -> None:
    if not rules:
        return

    with st.expander(f"사용자 분류 규칙 {len(rules)}개"):
        for idx, rule in enumerate(rules):
            display_name = f"{rule.raw_name} ({rule.symbol})" if rule.symbol else rule.raw_name
            left, right = st.columns([5, 1])
            left.write(f"{display_name} → {rule.category}")
            rule_key_id = category_rule_id(rule.keys)
            if right.button("삭제", key=f"delete_category_rule_{idx}_{rule_key_id}"):
                updated_rules = delete_user_category_rule(rules, idx)
                if not _save_user_category_rules_or_warn(updated_rules):
                    return
                st.session_state["category_rules_message"] = "사용자 분류 규칙을 삭제했어요."
                st.rerun()

        if st.button("전체 삭제", key="delete_all_category_rules"):
            if not _save_user_category_rules_or_warn([]):
                return
            st.session_state["category_rules_message"] = "사용자 분류 규칙을 모두 삭제했어요."
            st.rerun()


def _render_theme_charts(view_model: HoldingsViewModel, sort_mode: str) -> None:
    if sort_mode == "평가금액":
        chart_rows = market_value_chart_rows(view_model)
        if not chart_rows:
            return
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
        st.altair_chart(chart, width="stretch")
        return

    if sort_mode == "수익률":
        chart_rows = return_chart_rows(view_model)
        if not chart_rows:
            st.info("수익률 데이터가 있는 테마가 없어요")
            return
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
        st.altair_chart(chart, width="stretch")
        st.caption("초록=수익, 빨강=손실")
        return

    if sort_mode == "수익률·평가금액":
        chart_rows = return_value_chart_rows(view_model)
        if not chart_rows:
            return
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
        chart = alt.layer(bars, dots).resolve_scale(y="independent").properties(height=380)
        st.altair_chart(chart, width="stretch")
        st.caption("막대=평가금액, 점=수익률 (초록=수익, 빨강=손실)")
        return

    chart_data = cost_basis_chart_data(view_model)
    if chart_data.long_rows:
        long_df = pd.DataFrame(chart_data.long_rows)
        label_df = pd.DataFrame(chart_data.label_rows)
        bars = (
            alt.Chart(long_df)
            .mark_bar()
            .encode(
                x=alt.X("카테고리:N", sort=chart_data.ordered_categories, title=None),
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
                x=alt.X("카테고리:N", sort=chart_data.ordered_categories),
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
        st.altair_chart(chart, width="stretch")
        st.caption("회색=원금, 파랑=평가금액, 위 숫자=손익 (초록=수익, 빨강=손실)")
    if chart_data.skipped:
        st.caption(f"⚠️  손익 정보가 없는 테마는 제외됐어요: {', '.join(chart_data.skipped)}")


def _merged_snapshot(records: list[SnapshotRecord]) -> HoldingsSnapshot:
    return HoldingsSnapshot(
        source=" + ".join(record.name for record in records),
        extracted_at=datetime.now(timezone.utc),
        holdings=[holding for record in records for holding in record.snapshot.holdings],
    )


def render() -> None:
    st.title("📊 내 보유종목")
    st.caption("여러 증권사 스크린샷을 한 번에 합쳐서 보여드려요")

    saved_records = load_current_holdings()

    with st.sidebar:
        st.subheader("분석 설정")
        if os.environ.get("OPENAI_API_KEY"):
            st.success("분석 준비 완료")
        else:
            st.error("분석 키가 설정되지 않았어요")
            st.caption("관리자에게 문의해주세요")
        model = st.text_input("분석 모델", value=MODEL, help="gpt-4o 권장")
        if saved_records:
            st.divider()
            st.success("저장된 보유종목 표시 중")
            if st.button("새로 등록", type="primary", width="stretch"):
                clear_current_holdings()
                st.rerun()

    records: list[SnapshotRecord] = []
    errors: list[tuple[str, str]] = []

    if saved_records:
        records = saved_records
        st.info("마지막으로 분석한 보유종목을 불러왔어요. 새 캡처로 바꾸려면 왼쪽의 새로 등록을 누르세요.")
    else:
        uploaded_files = st.file_uploader(
            "증권사 앱 캡처 (여러 장 가능)",
            type=["png", "jpg", "jpeg", "webp", "gif"],
            accept_multiple_files=True,
        )

        if not uploaded_files:
            st.info("증권사 앱 캡처를 올려주세요. 자동으로 분석할게요.")
            return

        with st.expander(f"올린 이미지 {len(uploaded_files)}장", expanded=len(uploaded_files) <= 3):
            cols = st.columns(min(len(uploaded_files), 4))
            for idx, uploaded in enumerate(uploaded_files):
                cols[idx % len(cols)].image(
                    uploaded,
                    width="stretch",
                    caption=uploaded.name,
                )

        original_order = {uploaded.name: i for i, uploaded in enumerate(uploaded_files)}
        total = len(uploaded_files)
        progress = st.progress(0.0, text=f"분석 중... (0/{total})")
        done = 0

        def _extract_one(uploaded) -> tuple[str, str | None, str | None, float]:
            suffix = Path(uploaded.name).suffix or ".png"
            t0 = time.perf_counter()
            try:
                snapshot_json = _extract_cached(
                    uploaded.getvalue(),
                    suffix,
                    model,
                    PROMPT_FINGERPRINT,
                )
                return (uploaded.name, snapshot_json, None, time.perf_counter() - t0)
            except openai.AuthenticationError:
                return (
                    uploaded.name,
                    None,
                    "OpenAI 인증 실패 — Streamlit Secrets의 OPENAI_API_KEY 확인",
                    time.perf_counter() - t0,
                )
            except openai.RateLimitError:
                return (
                    uploaded.name,
                    None,
                    "OpenAI 호출 한도 초과 — 잠시 후 다시 시도",
                    time.perf_counter() - t0,
                )
            except openai.APITimeoutError:
                return (
                    uploaded.name,
                    None,
                    "OpenAI 응답 시간 초과 — 다시 시도",
                    time.perf_counter() - t0,
                )
            except Exception as exc:  # noqa: BLE001
                return (uploaded.name, None, str(exc), time.perf_counter() - t0)

        wall_start = time.perf_counter()
        per_task_elapsed: list[tuple[str, float]] = []
        with ThreadPoolExecutor(max_workers=min(total, 4)) as executor:
            future_to_file = {executor.submit(_extract_one, uploaded): uploaded for uploaded in uploaded_files}
            for future in as_completed(future_to_file):
                name, snapshot_json, err, elapsed = future.result()
                per_task_elapsed.append((name, elapsed))
                done += 1
                progress.progress(done / total, text=f"분석 중... ({done}/{total})")
                if err is not None:
                    errors.append((name, err))
                else:
                    snapshot = HoldingsSnapshot.model_validate_json(snapshot_json)
                    records.append(SnapshotRecord(name, snapshot, snapshot_json))
        wall_elapsed = time.perf_counter() - wall_start

        records.sort(key=lambda record: original_order[record.name])
        errors.sort(key=lambda error: original_order[error[0]])
        progress.progress(1.0, text=f"{len(records)}장 분석 완료")

        sum_elapsed = sum(elapsed for _, elapsed in per_task_elapsed)
        parallelism_hint = "병렬 ✓" if wall_elapsed < sum_elapsed * 0.7 else "직렬 의심 ⚠️"
        st.caption(
            f"⏱ 전체 {wall_elapsed:.1f}초 · 각 합계 {sum_elapsed:.1f}초 · {parallelism_hint}"
        )

        if records:
            try:
                save_current_holdings(records)
                st.success("이번 분석 결과를 저장했어요. 다음에 다시 열어도 이 보유종목을 먼저 보여줍니다.")
            except OSError as exc:
                st.warning("분석 결과를 저장하지 못했어요.")
                st.caption(str(exc))

        for name, err in errors:
            with st.container():
                st.warning(f"⚠️  {name} 분석에 실패했어요. 잠시 후 다시 올려주세요.")
                with st.expander("자세한 오류 보기"):
                    st.caption(err)

    if not records:
        return

    try:
        user_category_rules = load_user_category_rules()
        view_model = build_holdings_view_model(
            records,
            user_category_rules=user_category_rules,
            base_categories=load_categories(),
        )
    except ValueError as exc:
        st.error(f"카테고리 정의 오류: {exc}")
        return

    st.caption(
        f"{view_model.source_count}장에서 {view_model.total_holdings}개 종목을 찾았어요 · "
        f"이번 분석 약 ${view_model.source_count * 0.01:.2f}"
    )

    st.subheader("테마별로 보기")
    category_rules_message = st.session_state.get("category_rules_message")
    if category_rules_message:
        st.success(category_rules_message)
        del st.session_state["category_rules_message"]

    if view_model.category_rows:
        sort_mode = st.radio(
            "차트 기준",
            options=["원금 대비 현재", "평가금액", "수익률", "수익률·평가금액"],
            horizontal=True,
            key="chart_sort_mode",
        )
        _render_theme_charts(view_model, sort_mode)
        st.dataframe(
            pd.DataFrame(view_model.category_rows),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("분류된 종목이 없어요")

    _render_uncategorized_classifier(
        view_model.uncategorized_groups,
        view_model.category_options,
    )
    _render_user_category_rules(view_model.user_category_rules)

    st.subheader("전체 종목")
    holdings_df = pd.DataFrame(view_model.holding_rows)
    st.dataframe(holdings_df, width="stretch", hide_index=True)

    st.download_button(
        "엑셀로 받기",
        data=holdings_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="holdings_combined.csv",
        mime="text/csv",
    )

    with st.expander("자세히 보기"):
        try:
            report = build_report(_merged_snapshot(records))
            st.markdown("**회사별 합계**")
            st.markdown(render_markdown(report))
        except Exception as exc:
            st.warning("합계를 만들지 못했어요")
            st.caption(str(exc))

        st.markdown("**이미지별 결과**")
        tabs = st.tabs([record.name for record in records])
        for tab, record in zip(tabs, records):
            with tab:
                st.code(record.snapshot_json, language="json")
                st.markdown("원문 텍스트")
                st.text(record.snapshot.raw_text or "(없음)")
                st.download_button(
                    f"{record.name} 원본 데이터 받기",
                    data=record.snapshot_json,
                    file_name=f"{Path(record.name).stem}_snapshot.json",
                    mime="application/json",
                    key=f"dl_{record.name}",
                )
