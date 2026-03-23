from __future__ import annotations

import json
from pathlib import Path

from pipeline.transcriber import LogFn

CHUNK_SIZE_WORDS = 400
OVERLAP_WORDS = 50


def _collect_words(transcript: dict) -> list[dict]:
    """Extract word-level entries from transcript.

    Prefers word-level timestamps when available (Triton/Linux).
    Falls back to segment-level timestamps otherwise, splitting
    segment text into individual words that share the segment's
    start/end time.
    """
    words: list[dict] = []
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        return words

    for segment in segments:
        if not isinstance(segment, dict):
            continue

        # Try word-level data first
        seg_words = segment.get("words")
        if isinstance(seg_words, list) and seg_words:
            for word in seg_words:
                if not isinstance(word, dict):
                    continue
                text = word.get("word")
                start = word.get("start")
                end = word.get("end")
                if not isinstance(text, str):
                    continue
                if not isinstance(start, (int, float)) or not isinstance(
                    end, (int, float)
                ):
                    continue
                normalized = " ".join(text.strip().split())
                if not normalized:
                    continue
                words.append(
                    {"word": normalized, "start": float(start), "end": float(end)}
                )
        else:
            # Fallback: use segment-level timestamps
            text = segment.get("text", "")
            seg_start = segment.get("start")
            seg_end = segment.get("end")
            if not isinstance(text, str) or not text.strip():
                continue
            if not isinstance(seg_start, (int, float)) or not isinstance(
                seg_end, (int, float)
            ):
                continue
            for token in text.strip().split():
                normalized = " ".join(token.strip().split())
                if normalized:
                    words.append(
                        {
                            "word": normalized,
                            "start": float(seg_start),
                            "end": float(seg_end),
                        }
                    )

    return words


def chunk_transcript(transcript_path: Path, video_meta: dict, log: LogFn) -> list[dict]:
    transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    words = _collect_words(transcript)
    chunks: list[dict] = []
    video_id = video_meta["video_id"]
    title = video_meta.get("title", "")
    channel_name = video_meta.get("channel_name", "")
    upload_date = video_meta.get("upload_date", "")

    if not words:
        log(f"No word-level timestamps for {video_id}; creating empty chunk list.")
        return chunks

    step = CHUNK_SIZE_WORDS - OVERLAP_WORDS
    index = 0
    chunk_index = 0

    while index < len(words):
        slice_words = words[index : index + CHUNK_SIZE_WORDS]
        if not slice_words:
            break

        text = " ".join(item["word"] for item in slice_words).strip()
        start = slice_words[0]["start"]
        end = slice_words[-1]["end"]

        chunks.append(
            {
                "video_id": video_id,
                "title": title,
                "channel_name": channel_name,
                "upload_date": upload_date,
                "chunk_index": chunk_index,
                "text": text,
                "timestamp_start": start,
                "timestamp_end": end,
                "word_count": len(slice_words),
                "youtube_url_with_timestamp": f"https://youtube.com/watch?v={video_id}&t={int(start)}s",
            }
        )

        chunk_index += 1
        if index + CHUNK_SIZE_WORDS >= len(words):
            break
        index += step

    log(f"Created {len(chunks)} chunks for {video_id}.")
    return chunks
