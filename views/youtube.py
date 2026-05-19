from __future__ import annotations

import os

import streamlit as st

from holdings_ocr.youtube import (
    YoutubeExtractionError,
    YoutubeNote,
    build_markdown,
    extract_youtube_note,
    sanitize_filename,
)


@st.cache_data(show_spinner=False)
def _extract_cached(url: str, language: str, summarize: bool, model: str) -> YoutubeNote:
    return extract_youtube_note(
        url,
        language=language,
        summarize=summarize,
        summary_model=model,
    )


def _download_filename(note: YoutubeNote) -> str:
    return f"{sanitize_filename(note.video.title)}.md"


def render() -> None:
    st.title("🎬 유튜브 자막 추출")
    st.caption("유튜브 URL에서 메타데이터와 자막을 가져와 Markdown 노트로 정리해요")

    has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    with st.sidebar:
        st.subheader("추출 설정")
        language = st.text_input("자막 언어", value="ko", help="예: ko, en, ko,en")
        summarize = st.checkbox(
            "AI 요약 생성",
            value=has_openai_key,
            disabled=not has_openai_key,
            help="OPENAI_API_KEY가 있을 때만 사용할 수 있어요.",
        )
        model = st.text_input("요약 모델", value="gpt-4o-mini", disabled=not summarize)
        if has_openai_key:
            st.success("요약 사용 가능")
        else:
            st.caption("OPENAI_API_KEY가 없으면 자막 원문만 추출합니다.")

    url = st.text_input(
        "유튜브 URL",
        placeholder="https://www.youtube.com/watch?v=...",
    )
    run = st.button("추출", type="primary", use_container_width=True)

    if run:
        if not url.strip():
            st.error("유튜브 URL을 입력해주세요.")
            return
        try:
            with st.spinner("영상 정보와 자막을 가져오는 중..."):
                st.session_state["youtube_note"] = _extract_cached(
                    url.strip(),
                    language.strip(),
                    summarize,
                    model.strip() or "gpt-4o-mini",
                )
        except ValueError as exc:
            st.error(str(exc))
            return
        except YoutubeExtractionError as exc:
            st.error(str(exc))
            st.caption("자막이 없거나, 비공개/연령 제한 영상이거나, yt-dlp가 설치되지 않았을 수 있어요.")
            return
        except Exception as exc:  # noqa: BLE001
            st.error("추출에 실패했어요.")
            st.caption(str(exc))
            return

    note = st.session_state.get("youtube_note")
    if not note:
        st.info("URL을 입력하고 추출을 누르면 자막과 Markdown을 확인할 수 있어요.")
        return

    markdown = build_markdown(note)
    video = note.video

    st.subheader(video.title)
    c1, c2, c3 = st.columns(3)
    c1.metric("채널", video.channel)
    c2.metric("업로드", video.upload_date or "-")
    c3.metric("자막 길이", f"{len(note.transcript):,}자")

    tab_summary, tab_transcript, tab_markdown = st.tabs(["요약", "원문", "Markdown"])
    with tab_summary:
        if note.summary:
            st.markdown("### 요약")
            st.markdown(f"- **기존 문제**: {note.summary.problem}")
            st.markdown(f"- **제안 방법**: {note.summary.method}")
            st.markdown(f"- **효과**: {note.summary.effect}")
            st.markdown("### 키워드")
            st.markdown(" ".join(f"`{keyword}`" for keyword in note.summary.keywords))
            st.caption(f"분류: `{note.summary.category}`")
        else:
            st.info("AI 요약 생성을 켜고 다시 추출하면 knowledge/youtube 형식의 요약과 키워드가 추가됩니다.")
    with tab_transcript:
        st.text_area("자막 원문", note.transcript, height=420)
    with tab_markdown:
        st.code(markdown, language="markdown")

    st.download_button(
        "Markdown 받기",
        data=markdown.encode("utf-8"),
        file_name=_download_filename(note),
        mime="text/markdown",
        use_container_width=True,
    )
