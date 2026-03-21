from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

LogFn = Callable[[str], None]


def _safe_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _normalize_video(entry: dict[str, Any]) -> dict[str, Any]:
    video_id = entry.get("id") or entry.get("video_id")
    if not isinstance(video_id, str) or not video_id:
        raise ValueError("Missing video id in manifest entry")

    original_url = entry.get("webpage_url")
    if isinstance(original_url, str) and original_url.startswith("http"):
        url = original_url
    else:
        url = f"https://youtube.com/watch?v={video_id}"

    channel_name = entry.get("channel") or entry.get("uploader")
    if not isinstance(channel_name, str):
        channel_name = ""

    channel_id = entry.get("channel_id") or entry.get("uploader_id")
    if not isinstance(channel_id, str):
        channel_id = ""

    upload_date = entry.get("upload_date")
    if not isinstance(upload_date, str):
        upload_date = ""

    description = entry.get("description")
    if not isinstance(description, str):
        description = ""

    title = entry.get("title")
    if not isinstance(title, str):
        title = video_id

    return {
        "video_id": video_id,
        "title": title,
        "channel_name": channel_name,
        "channel_id": channel_id,
        "upload_date": upload_date,
        "duration_seconds": _safe_int(entry.get("duration")),
        "url": url,
        "description": description,
        "view_count": _safe_int(entry.get("view_count")),
        "like_count": _safe_int(entry.get("like_count")),
    }


def fetch_manifest(url: str, manifest_path: Path, log: LogFn) -> list[dict]:
    items: list[dict] = []

    list_proc = subprocess.run(
        ["yt-dlp", "--flat-playlist", "-J", url],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(list_proc.stdout)

    entries = data.get("entries") if isinstance(data, dict) else None
    if isinstance(entries, list) and entries:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item_url = entry.get("url")
            if isinstance(item_url, str) and item_url.startswith("http"):
                video_url = item_url
            else:
                video_id = entry.get("id")
                if isinstance(video_id, str):
                    video_url = f"https://youtube.com/watch?v={video_id}"
                else:
                    continue

            try:
                detail_proc = subprocess.run(
                    ["yt-dlp", "-J", video_url],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                full_data = json.loads(detail_proc.stdout)
                if isinstance(full_data, dict):
                    items.append(_normalize_video(full_data))
            except Exception as exc:
                log(f"Manifest warning for entry: {exc}")
    elif isinstance(data, dict):
        items.append(_normalize_video(data))

    manifest_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return items
