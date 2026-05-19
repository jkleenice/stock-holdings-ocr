from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from holdings_ocr import cli
from holdings_ocr.youtube import (
    YoutubeNote,
    YoutubeSummary,
    YoutubeVideoInfo,
    _clean_transcript,
    _parse_srt,
    build_markdown,
    classify_category,
    extract_video_id,
    get_transcript,
    get_video_info,
    save_note_markdown,
    summarize_transcript,
)


def _video() -> YoutubeVideoInfo:
    return YoutubeVideoInfo(
        title="GPT 검색 자동화",
        channel="Bagel Labs",
        upload_date="2026-05-16",
        duration=123,
        url="https://www.youtube.com/watch?v=abc123def45",
        video_id="abc123def45",
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123def45",
        "https://youtu.be/abc123def45",
        "https://www.youtube.com/embed/abc123def45",
        "https://www.youtube.com/shorts/abc123def45",
    ],
)
def test_extract_video_id_accepts_common_url_shapes(url: str):
    assert extract_video_id(url) == "abc123def45"


def test_get_video_info_uses_python_module_yt_dlp(monkeypatch):
    payload = {
        "id": "abc123def45",
        "title": "테스트 영상",
        "channel": "테스트 채널",
        "upload_date": "20260516",
        "duration": 91,
        "webpage_url": "https://www.youtube.com/watch?v=abc123def45",
    }

    def fake_run(command, capture_output, text, timeout):
        assert command[:3] == [sys.executable, "-m", "yt_dlp"]
        assert "--dump-json" in command
        assert capture_output is True
        assert text is True
        assert timeout == 120
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("holdings_ocr.youtube.subprocess.run", fake_run)

    info = get_video_info("https://youtu.be/abc123def45")

    assert info.title == "테스트 영상"
    assert info.channel == "테스트 채널"
    assert info.upload_date == "2026-05-16"
    assert info.duration == 91
    assert info.video_id == "abc123def45"


def test_get_transcript_falls_back_to_auto_subtitles(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, capture_output, text, timeout):
        calls.append(command)
        if "--write-auto-sub" in command:
            output_template = command[command.index("-o") + 1]
            Path(f"{output_template}.ko.vtt").write_text(
                "WEBVTT\n\n"
                "00:00:00.000 --> 00:00:02.000\n"
                "<b>안녕하세요.</b>\n\n"
                "00:00:02.000 --> 00:00:04.000\n"
                "안녕하세요.\n\n"
                "00:00:04.000 --> 00:00:06.000\n"
                "다음 문장입니다.\n",
                encoding="utf-8",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("holdings_ocr.youtube.subprocess.run", fake_run)

    transcript = get_transcript("https://youtu.be/abc123def45", language="ko")

    assert len(calls) == 2
    assert "--write-sub" in calls[0]
    assert "--write-auto-sub" in calls[1]
    assert transcript == "안녕하세요. 다음 문장입니다."


def test_parse_srt_removes_indexes_timecodes_tags_and_consecutive_duplicates():
    srt = (
        "1\n00:00:00,000 --> 00:00:01,000\n<i>Hello.</i>\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nHello.\n\n"
        "3\n00:00:02,000 --> 00:00:03,000\nWorld.\n"
    )

    assert _parse_srt(srt) == "Hello. World."


def test_clean_transcript_groups_every_four_sentences():
    text = "One. Two. Three. Four. Five."

    assert _clean_transcript(text) == "One. Two. Three. Four.\n\nFive."


def test_build_markdown_writes_raw_note_shape():
    note = YoutubeNote(video=_video(), transcript="자막 원문")

    markdown = build_markdown(note, extracted_on=date(2026, 5, 16))

    assert 'title: "GPT 검색 자동화"' in markdown
    assert 'extracted: "2026-05-16"' in markdown
    assert "## 요약" not in markdown
    assert markdown.rstrip().endswith("자막 원문")


def test_build_markdown_includes_summary_keywords_and_category():
    note = YoutubeNote(
        video=_video(),
        transcript="자막 원문",
        summary=YoutubeSummary(
            problem="문제",
            method="방법",
            effect="효과",
            keywords=["GPT", "검색"],
            category="llm",
            model="gpt-4o-mini",
        ),
    )

    markdown = build_markdown(note, extracted_on=date(2026, 5, 16))

    assert 'category: "llm"' in markdown
    assert "summary_model" not in markdown
    assert "## 요약" in markdown
    assert "- **제안 방법**: 방법" in markdown
    assert "`GPT` `검색`" in markdown


def test_save_note_markdown_accepts_directory_output(tmp_path: Path):
    note = YoutubeNote(video=_video(), transcript="자막 원문")

    path = save_note_markdown(note, tmp_path)

    assert path.name == "GPT_검색_자동화.md"
    assert path.read_text(encoding="utf-8").rstrip().endswith("자막 원문")


def test_summarize_transcript_normalizes_payload_and_classifies_category():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "problem": "<b>검색 품질이 낮다</b>",
                            "method": "GPT와 RAG를 결합한다.",
                            "effect": "검색 정확도가 오른다.",
                            "keywords": ["GPT", "RAG", "검색", "GPT"],
                        }
                    )
                )
            )
        ]
    )
    completions = SimpleNamespace(create=lambda **kwargs: response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    summary = summarize_transcript(_video(), "GPT와 RAG 검색을 설명합니다.", client=client)

    assert summary.problem == "&lt;b&gt;검색 품질이 낮다&lt;/b&gt;"
    assert summary.keywords == ["GPT", "RAG", "검색"]
    assert summary.category == "search"


@pytest.mark.parametrize(
    "title,keywords,expected",
    [
        ("현금 들고 있으면 바보인 이유", ["금리", "자산배분", "부동산"], "finance"),
        ("비트코인을 아직도 인정할 수 없다면 봐야할 영상", ["비트코인", "블록체인"], "crypto"),
        ("2026 뷰티 트렌드 화장품 성분 Check", ["스킨케어", "화장품"], "beauty"),
    ],
)
def test_classify_category_matches_knowledge_youtube_folders(title, keywords, expected):
    video = YoutubeVideoInfo(
        title=title,
        channel="테스트",
        upload_date="2026-05-16",
        duration=1,
        url="https://www.youtube.com/watch?v=abc123def45",
        video_id="abc123def45",
    )

    assert classify_category(video, "", keywords) == expected


def test_cli_youtube_writes_markdown_file(tmp_path: Path, monkeypatch, capsys):
    note = YoutubeNote(video=_video(), transcript="자막 원문")

    def fake_extract(url, language, summarize, summary_model):
        assert url == "https://youtu.be/abc123def45"
        assert language == "ko"
        assert summarize is False
        assert summary_model == "gpt-4o-mini"
        return note

    monkeypatch.setattr(cli, "extract_youtube_note", fake_extract)

    rc = cli.main(["youtube", "https://youtu.be/abc123def45", "-o", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / "GPT_검색_자동화.md").exists()
    assert "GPT_검색_자동화.md" in capsys.readouterr().out
