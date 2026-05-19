from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Any


DEFAULT_SUMMARY_MODEL = os.getenv("YOUTUBE_SUMMARY_MODEL", "gpt-4o-mini")
DEFAULT_CATEGORY_RULES = {
    "automation": [
        "automation",
        "workflow",
        "n8n",
        "zapier",
        "자동화",
        "워크플로우",
    ],
    "ai_agent": [
        "agent",
        "ai agent",
        "multi-agent",
        "harness",
        "manus",
        "에이전트",
        "하네스",
    ],
    "coding": [
        "coding",
        "code",
        "programming",
        "developer",
        "cursor",
        "코딩",
        "개발",
    ],
    "devops": [
        "devops",
        "docker",
        "kubernetes",
        "deployment",
        "infra",
        "배포",
        "인프라",
    ],
    "search": [
        "search",
        "retrieval",
        "rag",
        "ranking",
        "query",
        "검색",
        "리트리벌",
        "랭킹",
    ],
    "llm": [
        "llm",
        "gpt",
        "claude",
        "openai",
        "anthropic",
        "gemini",
        "prompt",
        "프롬프트",
        "클로드",
        "모델",
    ],
    "finance": [
        "finance",
        "investment",
        "asset",
        "stock",
        "real estate",
        "money",
        "투자",
        "자산",
        "주식",
        "부동산",
        "현금",
        "금리",
    ],
    "crypto": [
        "crypto",
        "bitcoin",
        "blockchain",
        "stablecoin",
        "비트코인",
        "블록체인",
        "크립토",
        "코인",
        "스테이블코인",
    ],
    "beauty": [
        "beauty",
        "cosmetic",
        "skincare",
        "makeup",
        "뷰티",
        "화장품",
        "스킨케어",
        "메이크업",
        "피부",
    ],
}


class YoutubeExtractionError(RuntimeError):
    """Raised when yt-dlp cannot fetch metadata or subtitles."""


@dataclass(frozen=True)
class YoutubeVideoInfo:
    title: str
    channel: str
    upload_date: str
    duration: int
    url: str
    video_id: str


@dataclass(frozen=True)
class YoutubeSummary:
    problem: str
    method: str
    effect: str
    keywords: list[str]
    category: str
    model: str


@dataclass(frozen=True)
class YoutubeNote:
    video: YoutubeVideoInfo
    transcript: str
    summary: YoutubeSummary | None = None


def extract_video_id(url: str) -> str:
    """Extract the canonical 11-character YouTube video ID from a URL."""
    patterns = [
        r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"유효한 YouTube URL이 아닙니다: {url}")


def get_video_info(url: str) -> YoutubeVideoInfo:
    """Fetch title/channel/upload metadata through yt-dlp without downloading video."""
    result = _run_yt_dlp([
        "--dump-json",
        "--no-download",
        "--no-playlist",
        url,
    ])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise YoutubeExtractionError("yt-dlp 메타데이터 응답을 JSON으로 읽을 수 없습니다.") from exc

    video_id = data.get("id") or extract_video_id(url)
    return YoutubeVideoInfo(
        title=data.get("title") or "제목 없음",
        channel=data.get("channel") or data.get("uploader") or "채널 없음",
        upload_date=_format_upload_date(data.get("upload_date") or ""),
        duration=int(data.get("duration") or 0),
        url=data.get("webpage_url") or url,
        video_id=video_id,
    )


def get_transcript(url: str, *, language: str = "ko") -> str:
    """Download subtitles with yt-dlp and return cleaned transcript text."""
    language = _normalize_language(language)
    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = os.path.join(tmpdir, "sub")
        last_error = ""

        for subtitle_flag in ("--write-sub", "--write-auto-sub"):
            result = _run_yt_dlp(
                [
                    "--skip-download",
                    subtitle_flag,
                    "--sub-lang",
                    language,
                    "--sub-format",
                    "vtt/srt/best",
                    "--no-playlist",
                    "-o",
                    output_template,
                    url,
                ],
                check=False,
            )
            if result.returncode != 0:
                last_error = result.stderr.strip()

            subtitle_files = sorted(
                glob.glob(os.path.join(tmpdir, "*.srt"))
                + glob.glob(os.path.join(tmpdir, "*.vtt"))
            )
            if subtitle_files:
                subtitle_content = Path(subtitle_files[0]).read_text(encoding="utf-8")
                return _clean_transcript(_parse_srt(subtitle_content))

    suffix = f" yt-dlp: {last_error}" if last_error else ""
    raise YoutubeExtractionError(f"{language} 자막을 찾을 수 없습니다.{suffix}")


def extract_youtube_note(
    url: str,
    *,
    language: str = "ko",
    summarize: bool = False,
    summary_model: str = DEFAULT_SUMMARY_MODEL,
    client: Any | None = None,
) -> YoutubeNote:
    """Fetch metadata and transcript, optionally adding an OpenAI-generated summary."""
    video = get_video_info(url)
    transcript = get_transcript(url, language=language)
    summary = (
        summarize_transcript(video, transcript, model=summary_model, client=client)
        if summarize
        else None
    )
    return YoutubeNote(video=video, transcript=transcript, summary=summary)


def summarize_transcript(
    video: YoutubeVideoInfo,
    transcript: str,
    *,
    model: str = DEFAULT_SUMMARY_MODEL,
    client: Any | None = None,
) -> YoutubeSummary:
    """Generate a Korean structured summary and keywords from a transcript."""
    if client is None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency exists in this project
            raise RuntimeError("openai 패키지가 설치되어 있지 않습니다.") from exc

        client = OpenAI()

    transcript_excerpt = transcript[:12000]
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 YouTube 지식 노트를 구조화하는 편집자입니다. "
                    "반드시 JSON 객체 하나만 반환하세요. "
                    "키는 problem, method, effect, keywords 만 허용됩니다. "
                    "problem/method/effect는 각각 한국어 한 문단 문자열이어야 합니다. "
                    "keywords는 4~6개의 핵심 키워드 문자열 배열이어야 합니다. "
                    "제목 낚시 문구를 그대로 반복하지 말고, 영상의 핵심 내용을 보존하세요."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"제목: {video.title}\n"
                    f"채널: {video.channel}\n"
                    f"업로드일: {video.upload_date}\n\n"
                    "다음 자막을 읽고 JSON으로 요약해 주세요.\n"
                    "- problem: 영상이 지적하는 기존 문제\n"
                    "- method: 영상이 제안하는 해결 방법/도구/기법\n"
                    "- effect: 적용 시 기대 효과\n"
                    "- keywords: 검색과 분류에 쓸 핵심 키워드 4~6개\n\n"
                    f"자막:\n{transcript_excerpt}"
                ),
            },
        ],
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI 요약 응답이 비어 있습니다.")

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("OpenAI 요약 응답을 JSON으로 읽을 수 없습니다.") from exc

    problem = _clean_summary_field(payload.get("problem"))
    method = _clean_summary_field(payload.get("method"))
    effect = _clean_summary_field(payload.get("effect"))
    keywords = _normalize_keywords(payload.get("keywords", []), video, transcript)
    category = classify_category(video, transcript, keywords, [problem, method, effect])

    return YoutubeSummary(
        problem=problem,
        method=method,
        effect=effect,
        keywords=keywords,
        category=category,
        model=model,
    )


def classify_category(
    video: YoutubeVideoInfo,
    transcript: str,
    keywords: list[str],
    summary_fields: list[str] | None = None,
) -> str:
    title_text = video.title.lower()
    summary_text = " ".join(summary_fields or []).lower()
    keyword_text = " ".join(keywords).lower()
    transcript_text = transcript[:4000].lower()

    best_category = "uncategorized"
    best_score = 0
    for category, rules in DEFAULT_CATEGORY_RULES.items():
        score = 0
        for rule in rules:
            token = rule.lower()
            if token in keyword_text:
                score += 6
            if token in title_text:
                score += 5
            if token in summary_text:
                score += 3
            if token in transcript_text:
                score += 1
        if score > best_score:
            best_category = category
            best_score = score

    return best_category


def build_markdown(note: YoutubeNote, *, extracted_on: date | None = None) -> str:
    extracted = extracted_on or date.today()
    video = note.video
    frontmatter = [
        "---",
        f'title: "{_yaml_escape(video.title)}"',
        f'source: "{_yaml_escape(video.url)}"',
        f'channel: "{_yaml_escape(video.channel)}"',
        f'upload_date: "{_yaml_escape(video.upload_date)}"',
        f'extracted: "{extracted.isoformat()}"',
    ]
    if note.summary:
        frontmatter.append(f'category: "{_yaml_escape(note.summary.category)}"')
    frontmatter.append("---")

    body = [
        f"# {_markdown_escape(video.title)}",
        "",
        "| 항목 | 내용 |",
        "|------|------|",
        f"| 채널 | {_markdown_escape(video.channel)} |",
        f"| 업로드 | {_markdown_escape(video.upload_date)} |",
        f"| 원본 | {_markdown_escape(video.url)} |",
        "",
        "---",
        "",
    ]

    if note.summary:
        body.extend(
            [
                "## 요약",
                "",
                f"- **기존 문제**: {note.summary.problem}",
                f"- **제안 방법**: {note.summary.method}",
                f"- **효과**: {note.summary.effect}",
                "",
                "## 키워드",
                "",
                " ".join(f"`{_keyword_escape(keyword)}`" for keyword in note.summary.keywords),
                "",
                "---",
                "",
            ]
        )

    body.extend([note.transcript, ""])
    return "\n".join(frontmatter + [""] + body)


def save_note_markdown(note: YoutubeNote, output: Path) -> Path:
    """Write Markdown to a file, or to a sanitized filename inside a directory."""
    output = Path(output)
    if output.suffix.lower() == ".md":
        path = output
    else:
        path = output / f"{sanitize_filename(note.video.title)}.md"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_markdown(note), encoding="utf-8")
    return path


def sanitize_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "", title)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return (cleaned or "youtube_transcript")[:80]


def _run_yt_dlp(
    args: list[str],
    *,
    check: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "yt_dlp", *args]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise YoutubeExtractionError("yt-dlp 실행 시간이 초과되었습니다.") from exc

    if check and result.returncode != 0:
        stderr = result.stderr.strip() or "알 수 없는 오류"
        raise YoutubeExtractionError(f"yt-dlp 실패: {stderr}")
    return result


def _parse_srt(srt_content: str) -> str:
    lines = srt_content.strip().splitlines()
    text_lines: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line == "WEBVTT" or line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if re.match(r"^\d+$", line):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        if line:
            text_lines.append(line)

    deduped: list[str] = []
    for line in text_lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)

    return " ".join(deduped)


def _clean_transcript(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\[.*?\]", "", text).strip()
    if not text:
        return ""

    sentences = re.split(r"(?<=[.?!。])\s+", text)
    paragraphs: list[str] = []
    current: list[str] = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        current.append(sentence)
        if len(current) >= 4:
            paragraphs.append(" ".join(current))
            current = []

    if current:
        paragraphs.append(" ".join(current))

    return "\n\n".join(paragraphs)


def _normalize_keywords(keywords: Any, video: YoutubeVideoInfo, transcript: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    if isinstance(keywords, list):
        for keyword in keywords:
            if not isinstance(keyword, str):
                continue
            cleaned = re.sub(r"[`\n\r]+", " ", keyword)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if not cleaned:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            normalized.append(cleaned)
            seen.add(key)
            if len(normalized) >= 6:
                break

    if normalized:
        return normalized

    fallback = re.findall(r"[A-Za-z0-9+#.-]{2,}|[가-힣]{2,}", f"{video.title} {transcript[:1000]}")
    for token in fallback:
        cleaned = token.strip(".#")
        key = cleaned.casefold()
        if len(cleaned) < 2 or key in seen:
            continue
        normalized.append(cleaned)
        seen.add(key)
        if len(normalized) >= 6:
            break

    if not normalized:
        raise RuntimeError("키워드를 생성할 수 없습니다.")
    return normalized


def _clean_summary_field(value: Any) -> str:
    if not isinstance(value, str):
        raise RuntimeError("요약 필드는 문자열이어야 합니다.")
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        raise RuntimeError("요약 필드가 비어 있습니다.")
    return escape(cleaned, quote=False)


def _normalize_language(language: str) -> str:
    cleaned = re.sub(r"\s+", "", language)
    if not cleaned:
        raise ValueError("자막 언어 코드를 입력해야 합니다.")
    return cleaned


def _format_upload_date(value: str) -> str:
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _keyword_escape(value: str) -> str:
    return escape(value, quote=False).replace("`", "")


def _markdown_escape(value: str) -> str:
    return escape(value, quote=False).replace("|", "\\|")
