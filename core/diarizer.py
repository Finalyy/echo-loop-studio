import os
import re
from typing import List, Optional
from groq import Groq
from core.subtitle import SubtitleSegment

SPEAKER_STYLES = {
    "vietnamese": "Người nói",   # [Người nói A], [Người nói B]
    "english": "Speaker",        # [Speaker A], [Speaker B]
    "short": "",                 # [A], [B]
}


def format_speaker_label(letter: str, style: str) -> str:
    """Formats speaker label according to chosen style."""
    prefix = SPEAKER_STYLES.get(style, "Người nói")
    if prefix:
        return f"[{prefix} {letter}]"
    return f"[{letter}]"


def diarize_segments_batch(
    client: Groq,
    batch_segments: List[SubtitleSegment],
    style: str = "vietnamese",
    model: str = "qwen/qwen3.8-27b",
) -> List[str]:
    """
    Uses Groq LLM (qwen/qwen3.8-27b) to analyze conversation turns and assign speaker labels.
    """
    if not batch_segments:
        return []

    speaker_term = SPEAKER_STYLES.get(style, "Người nói")
    example_a = f"[{speaker_term} A]" if speaker_term else "[A]"
    example_b = f"[{speaker_term} B]" if speaker_term else "[B]"

    # Build prompt input
    lines = []
    for i, seg in enumerate(batch_segments, start=1):
        lines.append(f"[{i}] {seg.text.strip()}")

    transcript_text = "\n".join(lines)

    system_prompt = f"""Bạn là chuyên gia phân tích ngữ cảnh hội thoại và gán nhãn người nói (Speaker Diarization).
Nhiệm vụ: Đọc kỹ đoạn hội thoại dưới đây, phân tích sự tương tác, câu hỏi - đáp, lượt đối thoại giữa các nhân vật và gán nhãn người nói {example_a}, {example_b},... vào đầu mỗi câu.

Quy tắc BẮT BUỘC:
1. KHÔNG được thay đổi, thêm hoặc bớt bất kỳ từ nào của câu gốc.
2. Trả về đúng số lượng câu theo thứ tự từ [1] đến [{len(batch_segments)}].
3. Mỗi dòng bắt đầu bằng [Số thứ tự] [Tên người nói]: Nội dung câu.
Ví dụ:
[1] {example_a}: Xin chào bạn!
[2] {example_b}: Chào bạn, rất vui được gặp lại.
4. Chỉ trả về danh sách các câu đã gán nhãn, không giải thích gì thêm."""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcript_text},
        ],
        temperature=0.1,
    )

    content = response.choices[0].message.content or ""
    labeled_lines = [l.strip() for l in content.splitlines() if l.strip()]

    # Parse output lines matching [i] ...
    result_texts = []
    line_map = {}
    for line in labeled_lines:
        match = re.match(r"^\[(\d+)\]\s*(.*)$", line)
        if match:
            idx = int(match.group(1))
            text = match.group(2).strip()
            line_map[idx] = text

    # Map back to original segments
    for i, seg in enumerate(batch_segments, start=1):
        if i in line_map:
            result_texts.append(line_map[i])
        else:
            # Fallback if an index is missing
            result_texts.append(seg.text)

    return result_texts


def diarize_and_label_speakers(
    segments: List[SubtitleSegment],
    api_key: Optional[str] = None,
    style: str = "vietnamese",
    progress_callback=None,
    batch_size: int = 35,
) -> List[SubtitleSegment]:
    """
    Applies conversational speaker diarization to all subtitle segments using Groq LLM.
    Splits into batches to preserve context while avoiding token limits.
    """
    if not segments:
        return []

    active_key = (api_key or "").strip() or os.environ.get("GROQ_API_KEY", "").strip()
    if not active_key:
        # If no key, return segments unchanged
        return segments

    client = Groq(api_key=active_key)
    labeled_segments: List[SubtitleSegment] = []
    total = len(segments)

    for start_idx in range(0, total, batch_size):
        end_idx = min(start_idx + batch_size, total)
        batch = segments[start_idx:end_idx]

        if progress_callback:
            progress_callback(f"Đang phân biệt người nói (A, B, C...) câu {start_idx+1} đến {end_idx}/{total}...")

        try:
            labeled_texts = diarize_segments_batch(client, batch, style=style)
            for seg, new_text in zip(batch, labeled_texts):
                labeled_segments.append(
                    SubtitleSegment(
                        start=seg.start,
                        end=seg.end,
                        text=new_text,
                        index=seg.index,
                    )
                )
        except Exception as e:
            # On error, keep original segments
            print(f"[!] Lỗi khi phân biệt người nói theo batch: {e}")
            labeled_segments.extend(batch)

    return labeled_segments
