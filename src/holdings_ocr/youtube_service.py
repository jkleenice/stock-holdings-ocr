from __future__ import annotations

from dataclasses import dataclass

from .youtube import YoutubeNote, build_markdown, sanitize_filename


@dataclass(frozen=True)
class YoutubeNoteViewModel:
    title: str
    channel: str
    upload_date: str
    transcript_length: int
    markdown: str
    download_filename: str
    has_summary: bool
    summary_problem: str
    summary_method: str
    summary_effect: str
    summary_keywords: list[str]
    summary_category: str
    transcript: str


def download_filename(note: YoutubeNote) -> str:
    return f"{sanitize_filename(note.video.title)}.md"


def build_youtube_note_view_model(note: YoutubeNote) -> YoutubeNoteViewModel:
    summary = note.summary
    return YoutubeNoteViewModel(
        title=note.video.title,
        channel=note.video.channel,
        upload_date=note.video.upload_date or "-",
        transcript_length=len(note.transcript),
        markdown=build_markdown(note),
        download_filename=download_filename(note),
        has_summary=summary is not None,
        summary_problem=summary.problem if summary else "",
        summary_method=summary.method if summary else "",
        summary_effect=summary.effect if summary else "",
        summary_keywords=list(summary.keywords) if summary else [],
        summary_category=summary.category if summary else "",
        transcript=note.transcript,
    )
