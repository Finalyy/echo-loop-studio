import html
import re
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class SubtitleSegment:
    start: float  # seconds
    end: float    # seconds
    text: str
    index: int = 1

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def seconds_to_srt_timestamp(seconds: float) -> str:
    """
    Converts seconds (e.g. 83.456) to SRT timestamp format: 00:01:23,456
    """
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        secs += 1
        millis -= 1000
    if secs >= 60:
        minutes += 1
        secs -= 60
    if minutes >= 60:
        hours += 1
        minutes -= 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def srt_timestamp_to_seconds(timestamp: str) -> float:
    """
    Parses timestamp string (SRT '00:01:23,456' or VTT '00:01:23.456' or '01:23.456') into seconds.
    """
    timestamp = timestamp.strip().replace(",", ".")
    parts = timestamp.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    else:
        return float(parts[0])


def clean_html_tags(text: str) -> str:
    """
    Thoroughly cleans HTML and formatting tags from subtitle text.
    Handles:
    - Standard tags: <font color="...">, <i>, </i>, <b>, </b>, <u>, </u>
    - WebVTT tags: <c.color...>, </c>, <v Speaker>, <lang en>, <ruby>, <rt>
    - Inline timestamp tags: <00:00:01.000>
    - HTML entity decoding: &amp;, &quot;, &#39;, &nbsp;, &gt;, &lt;
    - WebVTT styling annotations & line breaks
    """
    if not text:
        return ""

    # Unescape HTML entities first (&amp; -> &, &quot; -> ", etc.)
    cleaned = html.unescape(text)

    # Remove inline timestamp tags e.g. <00:01:23.456>
    cleaned = re.sub(r"<\d{2}:\d{2}:\d{2}[\.,]\d{3}>", "", cleaned)
    cleaned = re.sub(r"<\d{2}:\d{2}[\.,]\d{3}>", "", cleaned)

    # Remove all HTML/XML-like tags (<font color=...>, <c>, </c>, <i>, </i>, <v ...>, etc.)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)

    # Remove ASS/SSA style tags like {\an8}, {\pos(100,200)}
    cleaned = re.sub(r"\{[^}]*\}", "", cleaned)

    # Normalize whitespace: convert multiple spaces or tabs into a single space
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()]
    # Remove empty lines
    lines = [line for line in lines if line]

    return "\n".join(lines)


def deduplicate_rolling_captions(segments: List[SubtitleSegment]) -> List[SubtitleSegment]:
    """
    Auto-generated platform captions (like YouTube) often produce rolling lines,
    where consecutive subtitle blocks repeat the previous line plus 1-2 new words.
    This function detects and deduplicates consecutive repeated lines.
    """
    if not segments:
        return []

    cleaned_segments: List[SubtitleSegment] = []
    last_text = ""

    for seg in segments:
        cur_text = seg.text.strip()
        if not cur_text:
            continue

        # Check if text is identical to last segment
        if cur_text == last_text:
            # If identical, extend the previous segment's end time
            if cleaned_segments:
                cleaned_segments[-1].end = max(cleaned_segments[-1].end, seg.end)
            continue

        # Check if last_text is a prefix of cur_text (rolling caption)
        if last_text and cur_text.startswith(last_text):
            # E.g. last: "Hello everyone", cur: "Hello everyone welcome to"
            # Instead of keeping both, we can either keep cur or update last.
            # If the timestamp overlaps or immediately follows, update the last segment text & end.
            if cleaned_segments and (seg.start - cleaned_segments[-1].end <= 0.8):
                cleaned_segments[-1].text = cur_text
                cleaned_segments[-1].end = max(cleaned_segments[-1].end, seg.end)
                last_text = cur_text
                continue

        cleaned_segments.append(
            SubtitleSegment(
                start=seg.start,
                end=seg.end,
                text=cur_text,
                index=len(cleaned_segments) + 1,
            )
        )
        last_text = cur_text

    return cleaned_segments


def parse_srt_content(srt_content: str) -> List[SubtitleSegment]:
    """
    Parses a raw SRT string (or VTT converted string) into a list of SubtitleSegment objects.
    Cleans HTML tags and normalizes timestamps.
    """
    if not srt_content:
        return []

    # Strip BOM and normalize line endings
    srt_content = srt_content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")

    # Regular expression for timestamp line:
    # 00:00:01,000 --> 00:00:04,500
    # Also tolerates dot notation: 00:00:01.000 --> 00:00:04.500
    time_pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{3}|\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{3}|\d{2}:\d{2}[,\.]\d{3})"
    )

    blocks = re.split(r"\n\s*\n", srt_content.strip())
    segments: List[SubtitleSegment] = []

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue

        time_line_idx = -1
        match = None
        for i, line in enumerate(lines):
            match = time_pattern.search(line)
            if match:
                time_line_idx = i
                break

        if not match or time_line_idx == -1:
            continue

        start_str, end_str = match.groups()
        try:
            start_sec = srt_timestamp_to_seconds(start_str)
            end_sec = srt_timestamp_to_seconds(end_str)
        except Exception:
            continue

        # Text is all lines following the timestamp line
        raw_text = "\n".join(lines[time_line_idx + 1 :])
        cleaned_text = clean_html_tags(raw_text)

        if cleaned_text and end_sec > start_sec:
            segments.append(
                SubtitleSegment(
                    start=start_sec,
                    end=end_sec,
                    text=cleaned_text,
                    index=len(segments) + 1,
                )
            )

    return deduplicate_rolling_captions(segments)


def segments_to_srt(segments: List[SubtitleSegment]) -> str:
    """
    Converts a list of SubtitleSegment objects into standard SRT file format string.
    """
    srt_lines = []
    for i, seg in enumerate(segments, start=1):
        start_ts = seconds_to_srt_timestamp(seg.start)
        end_ts = seconds_to_srt_timestamp(seg.end)
        # Format text, ensuring single space between lines if multiple lines exist
        text = seg.text.strip()
        srt_lines.append(f"{i}\n{start_ts} --> {end_ts}\n{text}\n")

    return "\n".join(srt_lines)
