import json
import os
import re
from typing import List, Optional
from groq import Groq
from core.subtitle import SubtitleSegment

# Punctuation marks indicating sentence boundaries across languages
SENTENCE_TERMINALS = (".", "?", "!", "…", "...", "。", "？", "！", "；")

# Dangling words that should never end a subtitle line
DANGLING_WORDS = {
    # English
    "the", "a", "an", "of", "to", "in", "on", "at", "for", "with", "by", "from",
    "as", "that", "which", "who", "whom", "whose", "and", "or", "but", "because",
    "if", "when", "while", "where", "after", "before", "so", "than", "is", "are",
    "was", "were", "will", "would", "can", "could", "should", "my", "your", "his",
    "her", "our", "their", "its", "into", "onto", "about",
    # Vietnamese
    "của", "và", "hoặc", "nhưng", "mà", "để", "cho", "với", "trong", "trên",
    "dưới", "tại", "từ", "đến", "rằng", "là", "thì", "nếu", "khi", "bởi", "vì",
    "do", "nên", "các", "những", "một", "về", "như", "được", "bị"
}


def is_dangling(text: str) -> bool:
    """Checks if a text snippet ends with a dangling word or incomplete clause."""
    cleaned = text.strip().rstrip(".,?!:;…")
    words = cleaned.split()
    if not words:
        return False
    return words[-1].lower() in DANGLING_WORDS


def ai_segment_batch(
    client: Groq,
    raw_segments: List[SubtitleSegment],
    model: str = "qwen/qwen3.8-27b",
    language: str = "en",
) -> List[SubtitleSegment]:
    """
    Uses Groq LLM to analyze raw subtitle segments and group them into complete,
    coherent sentences without awkward mid-sentence breaks.
    """
    if not raw_segments:
        return []

    input_data = [
        {"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()}
        for seg in raw_segments
        if seg.text.strip()
    ]
    if not input_data:
        return []

    system_prompt = """Bạn là chuyên gia ngôn ngữ học và biên tập phụ đề cho ứng dụng luyện nghe lặp (Shadowing / Echo Loop).
Nhiệm vụ của bạn: Nhận các phân đoạn phụ đề thô (thường bị ngắt vụn hoặc thiếu dấu câu) và tổ chức lại thành các CÂU NÓI TRỌN VẸN, TỰ NHIÊN, HOÀN CHỈNH Ý NGHĨA.

QUY TẮC CỐT LÕI:
1. CÂU NÓI PHẢI TRỌN VẸN:
   - Mỗi phân đoạn phụ đề phải là một câu hoàn chỉnh về ngữ pháp và ý nghĩa.
   - TUYỆT ĐỐI KHÔNG ngắt câu ở giữa cụm từ, sau liên từ ('and', 'because', 'rằng', 'là',...), hoặc trước động từ chính.
2. ĐIỂM NGẮT HỢP LÝ:
   - Chỉ ngắt khi kết thúc trọn vẹn câu (thêm dấu chấm, hỏi, cảm thán hợp lý).
   - Nếu một câu quá dài (> 10-12 giây), chỉ được ngắt ở mệnh đề độc lập có dấu phẩy hoặc điểm người nói ngừng nghỉ tự nhiên.
3. KHỚP MỐC THỜI GIAN:
   - 'start': thời gian bắt đầu (giây) của đoạn đầu tiên trong câu.
   - 'end': thời gian kết thúc (giây) của đoạn cuối cùng trong câu.
4. GIỮ NGUYÊN TỪ NGỮ GỐC:
   - Giữ nguyên 100% nội dung lời nói, chỉ sửa dấu câu và viết hoa đầu câu cho chuẩn mực.

ĐỊNH DẠNG ĐẦU RA BẮT BUỘC (JSON DUY NHẤT):
{
  "sentences": [
    {"start": float, "end": float, "text": "Câu nói hoàn chỉnh..."}
  ]
}"""

    user_prompt = f"Ngôn ngữ chính: {language}\nDanh sách đoạn thô:\n" + json.dumps(input_data, ensure_ascii=False)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        parsed_sentences = data.get("sentences", [])

        if not parsed_sentences:
            return raw_segments

        # Reconcile timestamps against raw segments
        result: List[SubtitleSegment] = []
        min_start = raw_segments[0].start
        max_end = raw_segments[-1].end
        last_end = min_start

        for item in parsed_sentences:
            text = str(item.get("text", "")).strip()
            if not text:
                continue

            raw_s = float(item.get("start", last_end))
            raw_e = float(item.get("end", raw_s + 3.0))

            start = max(min_start, raw_s)
            if result and start < result[-1].start:
                start = result[-1].end

            end = max(start + 0.5, raw_e)
            if end > max_end + 1.0:
                end = max_end

            result.append(
                SubtitleSegment(
                    start=round(start, 3),
                    end=round(end, 3),
                    text=text,
                    index=len(result) + 1,
                )
            )
            last_end = end

        return result if result else raw_segments

    except Exception as e:
        print(f"[!] AI segmentation batch error: {e}")
        return raw_segments


def ai_optimize_sentences(
    segments: List[SubtitleSegment],
    api_key: Optional[str] = None,
    language: str = "en",
    progress_callback=None,
    batch_size: int = 25,
) -> List[SubtitleSegment]:
    """
    Processes all segments in sliding batches using Groq LLM to produce
    naturally complete sentences with optimal pausing.
    """
    if not segments:
        return []

    active_key = (api_key or "").strip() or os.environ.get("GROQ_API_KEY", "").strip()
    if not active_key:
        return segments

    client = Groq(api_key=active_key)
    optimized_segments: List[SubtitleSegment] = []
    total = len(segments)

    for start_idx in range(0, total, batch_size):
        end_idx = min(start_idx + batch_size, total)
        batch = segments[start_idx:end_idx]

        if progress_callback:
            progress_callback(
                f"🧠 AI đang phân tích và chia câu trọn vẹn (Đoạn {start_idx+1} đến {end_idx}/{total})..."
            )

        processed = ai_segment_batch(
            client=client,
            raw_segments=batch,
            language=language,
        )
        optimized_segments.extend(processed)

    # Re-index all segments
    for idx, seg in enumerate(optimized_segments, start=1):
        seg.index = idx

    return optimized_segments
