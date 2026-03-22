# YouTube to RAG Ingestion Pipeline (Local, Tkinter)

This project is a local-first ingestion pipeline that takes a YouTube playlist or channel URL, downloads audio for each video, transcribes with local Whisper, chunks transcripts with overlap and timestamps, and saves machine-readable JSON artifacts for downstream RAG indexing.

All processing runs locally. No web framework or hosted API is used.

## Features

- Local GUI built with `tkinter` (single window workflow)
- URL input for playlist or channel
- Whisper model selector: `tiny`, `base`, `small`, `medium`, `large-v3`
- Sequential processing (one video at a time)
- Graceful stop using `threading.Event` (stops after current video)
- Progress tracking across the full manifest
- Live logs in GUI + persisted rotating logs on disk
- Resumable pipeline via `state.json`
- Failure isolation: failed videos are marked and pipeline continues

## Project Structure

```text
pipeline/
├── main.py
├── gui.py
├── cleanup.py
├── requirements.txt
├── README.md
├── pipeline/
│   ├── __init__.py
│   ├── manifest.py
│   ├── transcriber.py
│   ├── chunker.py
│   └── state.py
└── data/
    ├── manifest.json
    ├── state.json
    ├── logs/
    │   └── pipeline.log
    ├── audio/
    ├── transcripts/
    └── chunks/
```

## Requirements

- Python 3.10+
- `uv`
- `ffmpeg` installed and available in `PATH`
- Internet connection for YouTube download + initial Whisper model download

Python dependencies are in `requirements.txt`:

- `yt-dlp`
- `openai-whisper`
- `torch`

> **Note:** `requirements.txt` includes `--extra-index-url https://download.pytorch.org/whl/cu128` so that `pip`/`uv` can fetch the CUDA 12.8 build of PyTorch. If you don't have an NVIDIA GPU, the CPU-only wheel will still work — the extra index is simply preferred when a matching CUDA build is available.

`tkinter` is part of Python stdlib on macOS Python distributions that include Tk.

## Quickstart (uv)

From repository root:

```bash
uv venv
uv pip install -r pipeline/requirements.txt
uv run python pipeline/main.py
```

## GUI Usage

1. Paste a YouTube playlist or channel URL (must be a `youtube.com` or `youtu.be` link).
2. Choose Whisper model size.
3. Click **Start**.
4. Watch live progress/logs.
5. Click **Stop** to halt gracefully after current video completes.

Summary counters at the bottom show:

- Total
- Completed
- Failed
- Skipped

## Pipeline Stages

For each video, sequentially:

1. **Manifested**: metadata gathered from `yt-dlp`
2. **Audio Downloaded**: audio-only file downloaded into `data/audio/`
3. **Transcribed**: Whisper transcription with `language="en"` (forced English) saved to `data/transcripts/{video_id}.json`. Word-level timestamps are enabled when Triton is available (Linux only); otherwise segment-level timestamps are used.
4. **Chunked**: transcript chunked (~400 words, 50 overlap) to `data/chunks/{video_id}.json`
5. **Cleanup**: temporary audio removed

If any stage fails, video is marked `failed` in state and processing continues.

> **Language:** Transcription is auto translated to English as i think this will be more useful for the RAG pipeline. If you need multi-language support, change the `language` parameter in `pipeline/transcriber.py`.

## Resumability and State

`data/state.json` stores per-video status and stage metadata.

- Videos with `status == "chunked"` are skipped on reruns.
- State is updated after each stage.
- Writes are atomic (temporary file + replace).

This allows safe reruns without reprocessing completed videos.

## Manifest Schema (`data/manifest.json`)

Each entry includes:

- `video_id`
- `title`
- `channel_name`
- `channel_id`
- `upload_date`
- `duration_seconds`
- `url`
- `description`
- `view_count`
- `like_count`

## Transcript Output (`data/transcripts/{video_id}.json`)

Raw Whisper JSON output is stored per video with segment and word-level timing data.

## Chunk Output (`data/chunks/{video_id}.json`)

Each chunk includes:

- `video_id`
- `title`
- `channel_name`
- `upload_date`
- `chunk_index`
- `text`
- `timestamp_start`
- `timestamp_end`
- `word_count`
- `youtube_url_with_timestamp`

Timestamp URL format:

`https://youtube.com/watch?v={video_id}&t={int(timestamp_start)}s`

## Logging

The app logs in two places:

1. **Live GUI logs** (timestamped + colored by severity)
2. **Persistent file logs** in `data/logs/pipeline.log`

File logging uses rotation:

- max size: ~2MB per file
- backups kept: 5

Severity levels:

- `INFO`
- `WARNING`
- `ERROR`

## Device Behavior (Cross-platform)

Whisper model loading always prefers GPU first in this order:

1. `cuda` (NVIDIA GPU, common on Windows/Linux)
2. `mps` (Apple Silicon GPU on macOS)
3. `cpu` fallback

If GPU initialization fails, the app falls back to CPU and continues.

## Common Issues

- `yt-dlp` fails on some videos: usually age-restriction, unavailable, or region block. The pipeline marks these as failed and continues.
- Missing `ffmpeg`: install it and retry.
- Slow transcription: use smaller model (`tiny`/`base`) for speed.
- Empty chunks: some transcripts may not contain word-level data for specific media; output can be empty for that video.
- Invalid URL: the GUI validates that the URL starts with `youtube.com` or `youtu.be` before starting.

## Cleanup

To reset the pipeline and remove all generated data (audio, transcripts, chunks, logs, and state), run the included cleanup script. **Ensure the GUI is closed before running** to avoid file locking errors on Windows:

```bash
uv run python pipeline/cleanup.py
```

## Development Notes

- GUI remains responsive because the pipeline runs in a background thread.
- Inter-thread communication uses `queue.Queue` events.
- Stop control uses `threading.Event`.
- No single video failure should crash the full run.
- `video_id` values from `yt-dlp` are sanitized to reject path separators, preventing path traversal in file writes.
