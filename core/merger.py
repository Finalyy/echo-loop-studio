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
        # Check if it's a number e.g. "12."
        words = cleaned.split()
        if not words:
            return True
        last_word = words[-1].lower()

        # If it's a known abbreviation, not a sentence end
        if last_word in COMMON_ABBREVIATIONS:
            return False

        # If it's digits followed by dot like '3.', it's likely an item number or version
        if last_word[:-1].isdigit():
            return False

        # If single letter followed by dot like 'A.', might be an initial
        if len(last_word) == 2 and last_word[0].isalpha():
            return False

        return True

    return False


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
    """
    Combines two subtitle text snippets with proper spacing.
    Adds a space for Latin/alphabet languages; avoids space for CJK scripts.
    """
    t1 = text1.strip()
    t2 = text2.strip()
    if not t1:
        return t2
    if not t2:
        return t1

    # If t1 ends with CJK and t2 starts with CJK, no space needed
    if is_cjk_char(t1[-1]) and is_cjk_char(t2[0]):
        return f"{t1}{t2}"

    # If t1 ends with dash or hyphen
    if t1.endswith("-") or t1.endswith("—"):
        return f"{t1}{t2}"

    return f"{t1} {t2}"


def merge_short_segments(
    segments: List[SubtitleSegment],
    min_duration: float = 4.0,
    max_duration: float = 8.5,
    silence_gap_threshold: float = 1.5,
) -> List[SubtitleSegment]:
    """
    Merges consecutive short subtitle segments into natural, complete sentences
    simulating Echo Loop's 'Auto-merge short sentences' feature.

    Parameters:
    - segments: list of input SubtitleSegment objects.
    - min_duration: ideal minimum duration (seconds) before closing a sentence (default 4.0s).
    - max_duration: upper limit (seconds) to prevent overly long captions (default 8.5s).
    - silence_gap_threshold: gap (seconds) between segments indicating a speaker pause (default 1.5s).

    Returns:
    - Merged list of SubtitleSegment objects.
    """
    if not segments:
        return []

    merged: List[SubtitleSegment] = []
    
    current_start = segments[0].start
    current_end = segments[0].end
    current_text = segments[0].text.strip()

    for i in range(1, len(segments)):
        next_seg = segments[i]
        next_text = next_seg.text.strip()
        if not next_text:
            continue

        gap = max(0.0, next_seg.start - current_end)
        current_duration = current_end - current_start
        potential_duration = next_seg.end - current_start
        has_sentence_end = is_true_sentence_end(current_text)

        # Condition 1: Long silence gap between speech chunks -> Speaker paused significantly
        if gap >= silence_gap_threshold:
            # Commit current segment and start fresh
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

        # Condition 2: Current text has reached minimum duration AND ends with sentence-ending punctuation
        if current_duration >= min_duration and has_sentence_end:
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

        # Condition 3: Adding next segment would exceed max_duration
        if potential_duration > max_duration:
            # If current duration is reasonable (>= 2.5s) or has sentence end, commit now
            if current_duration >= 2.5 or has_sentence_end:
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

        # Otherwise, merge next segment into current
        current_text = combine_texts(current_text, next_text)
        current_end = max(current_end, next_seg.end)

    # Append the last accumulated segment
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
