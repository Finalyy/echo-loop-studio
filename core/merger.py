import re
from typing import List
from core.subtitle import SubtitleSegment

# Punctuation marks indicating sentence boundaries across languages
SENTENCE_ENDINGS = (
    ".", "?", "!", "…", "...", 
    "。", "？", "！", "；"
)

# Common abbreviations to avoid false positive splits on dots
COMMON_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "vs.", 
    "etc.", "e.g.", "i.e.", "u.s.", "u.k.", "approx.", "dept.",
    "est.", "gen.", "gov.", "inc.", "ltd.", "no.", "st."
}

# Dangling words that should never end a subtitle sentence
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
    "do", "nên", "các", "những", "một", "về", "như", "được", "bị",
    # German
    "der", "die", "das", "ein", "eine", "und", "oder", "aber", "weil", "dass",
    "in", "an", "auf", "für", "mit", "von", "zu", "ist", "sind", "war"
}


def is_dangling_word(text: str) -> bool:
    """Returns True if the text ends with a dangling preposition, article, or conjunction."""
    cleaned = text.strip().rstrip(".,?!:;…")
    words = cleaned.split()
    if not words:
        return False
    return words[-1].lower() in DANGLING_WORDS


def is_true_sentence_end(text: str) -> bool:
    """
    Checks if a text string ends with a genuine sentence-ending punctuation,
    taking into account abbreviations and numbers (e.g. '3.5', 'Dr.').
    """
    cleaned = text.strip()
    if not cleaned:
        return False

    # Check CJK sentence ends
    if cleaned[-1] in ("。", "？", "！", "；"):
        return True

    # Check Western sentence ends
    if cleaned.endswith(("?", "!", "…", "...")):
        return True

    if cleaned.endswith("."):
        words = cleaned.split()
        if not words:
            return True
        last_word = words[-1].lower()

        # Known abbreviations (Dr., Mr., etc.) are NOT sentence ends
        if last_word in COMMON_ABBREVIATIONS:
            return False

        # Digits followed by dot like '3.', not a sentence end
        if last_word[:-1].isdigit():
            return False

        # Single letter initial like 'A.', not a sentence end
        if len(last_word) == 2 and last_word[0].isalpha():
            return False

        return True

    return False


def is_clause_pause(text: str) -> bool:
    """Checks if text ends with a clause-level pause mark (comma, semicolon, dash)."""
    cleaned = text.strip()
    return cleaned.endswith((",", ";", "—", "-", "，", "；"))


def is_cjk_char(ch: str) -> bool:
    """Returns True if character belongs to Chinese, Japanese, or Korean script ranges."""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF or   # CJK Unified Ideographs
        0x3400 <= code <= 0x4DBF or   # CJK Unified Ideographs Extension A
        0x3040 <= code <= 0x309F or   # Hiragana
        0x30A0 <= code <= 0x30FF or   # Katakana
        0xAC00 <= code <= 0xD7AF      # Hangul Syllables
    )


def combine_texts(text1: str, text2: str) -> str:
    """Combines two subtitle text snippets with proper spacing."""
    t1 = text1.strip()
    t2 = text2.strip()
    if not t1:
        return t2
    if not t2:
        return t1

    if is_cjk_char(t1[-1]) and is_cjk_char(t2[0]):
        return f"{t1}{t2}"

    if t1.endswith("-") or t1.endswith("—"):
        return f"{t1}{t2}"

    return f"{t1} {t2}"


def split_compound_segment(seg: SubtitleSegment) -> List[SubtitleSegment]:
    """
    If a single segment contains multiple distinct sentences separated by (. ? !),
    splits it into separate segments with interpolated timestamps.
    """
    text = seg.text.strip()
    # Pattern to find sentence boundaries inside the text
    pattern = r'(?<=[.?!。？！])\s+(?=[A-ZÀ-Ỹ0-9])'
    parts = re.split(pattern, text)
    if len(parts) <= 1:
        return [seg]

    total_chars = sum(len(p.strip()) for p in parts)
    if total_chars == 0:
        return [seg]

    duration = max(0.5, seg.end - seg.start)
    sub_segments: List[SubtitleSegment] = []
    current_time = seg.start

    for part in parts:
        p_text = part.strip()
        if not p_text:
            continue
        p_duration = duration * (len(p_text) / total_chars)
        p_end = current_time + p_duration
        sub_segments.append(
            SubtitleSegment(
                start=round(current_time, 3),
                end=round(min(p_end, seg.end), 3),
                text=p_text
            )
        )
        current_time = p_end

    if sub_segments:
        sub_segments[-1].end = seg.end

    return sub_segments


def merge_short_segments(
    segments: List[SubtitleSegment],
    min_duration: float = 4.0,
    max_duration: float = 8.5,
    silence_gap_threshold: float = 1.2,
    soft_max_duration: float = 12.0,
) -> List[SubtitleSegment]:
    """
    Merges consecutive short subtitle segments into natural, complete sentences
    simulating Echo Loop's 'Auto-merge short sentences' feature.

    Enhanced sentence boundary logic:
    - Never splits mid-sentence (after dangling words or incomplete clauses).
    - Preserves complete thoughts (up to soft_max_duration) rather than cutting mid-sentence.
    - Honors natural silence pauses (gap >= silence_gap_threshold).
    - Breaks at commas or clause pauses when reaching upper limits.
    """
    if not segments:
        return []

    # First pass: split any single segments that contain multiple sentences
    expanded: List[SubtitleSegment] = []
    for s in segments:
        expanded.extend(split_compound_segment(s))

    merged: List[SubtitleSegment] = []
    current_start = expanded[0].start
    current_end = expanded[0].end
    current_text = expanded[0].text.strip()

    for i in range(1, len(expanded)):
        next_seg = expanded[i]
        next_text = next_seg.text.strip()
        if not next_text:
            continue

        gap = max(0.0, next_seg.start - current_end)
        current_duration = current_end - current_start
        potential_duration = next_seg.end - current_start
        has_sentence_end = is_true_sentence_end(current_text)
        has_clause_end = is_clause_pause(current_text)
        dangling = is_dangling_word(current_text)

        # Condition 1: Significant silence gap -> Speaker took a breath / paused talking
        if gap >= silence_gap_threshold and not dangling:
            merged.append(
                SubtitleSegment(
                    start=current_start,
                    end=current_end,
                    text=current_text,
                    index=len(merged) + 1,
                )
            )
            current_start = next_seg.start
            current_end = next_seg.end
            current_text = next_text
            continue

        # Condition 2: Sentence has ended naturally and reached comfortable duration
        if current_duration >= min_duration and has_sentence_end and not dangling:
            merged.append(
                SubtitleSegment(
                    start=current_start,
                    end=current_end,
                    text=current_text,
                    index=len(merged) + 1,
                )
            )
            current_start = next_seg.start
            current_end = next_seg.end
            current_text = next_text
            continue

        # Condition 3: Approaching standard max_duration
        if potential_duration > max_duration:
            # Sub-case 3a: We have a true sentence end -> Commit cleanly!
            if has_sentence_end and not dangling:
                merged.append(
                    SubtitleSegment(
                        start=current_start,
                        end=current_end,
                        text=current_text,
                        index=len(merged) + 1,
                    )
                )
                current_start = next_seg.start
                current_end = next_seg.end
                current_text = next_text
                continue

            # Sub-case 3b: We have a natural clause break (comma/dash) and reasonable duration
            if has_clause_end and current_duration >= 5.0 and not dangling:
                merged.append(
                    SubtitleSegment(
                        start=current_start,
                        end=current_end,
                        text=current_text,
                        index=len(merged) + 1,
                    )
                )
                current_start = next_seg.start
                current_end = next_seg.end
                current_text = next_text
                continue

            # Sub-case 3c: Sentence is NOT finished, but we haven't hit soft_max_duration (12s).
            # KEEP MERGING to prevent cutting off mid-sentence!
            if potential_duration <= soft_max_duration:
                current_text = combine_texts(current_text, next_text)
                current_end = max(current_end, next_seg.end)
                continue

            # Sub-case 3d: Exceeded soft_max_duration (>12s). Only cut if NOT ending with dangling word
            if not dangling:
                merged.append(
                    SubtitleSegment(
                        start=current_start,
                        end=current_end,
                        text=current_text,
                        index=len(merged) + 1,
                    )
                )
                current_start = next_seg.start
                current_end = next_seg.end
                current_text = next_text
                continue

        # Default: continue accumulating
        current_text = combine_texts(current_text, next_text)
        current_end = max(current_end, next_seg.end)

    # Append remaining
    if current_text:
        merged.append(
            SubtitleSegment(
                start=current_start,
                end=current_end,
                text=current_text,
                index=len(merged) + 1,
            )
        )

    return merged
