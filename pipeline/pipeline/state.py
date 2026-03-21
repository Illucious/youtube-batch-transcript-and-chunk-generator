from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_data_layout(data_dir: Path) -> None:
    (data_dir / "audio").mkdir(parents=True, exist_ok=True)
    (data_dir / "transcripts").mkdir(parents=True, exist_ok=True)
    (data_dir / "chunks").mkdir(parents=True, exist_ok=True)
    if not (data_dir / "manifest.json").exists():
        (data_dir / "manifest.json").write_text("[]\n", encoding="utf-8")
    if not (data_dir / "state.json").exists():
        (data_dir / "state.json").write_text("{}\n", encoding="utf-8")


class StateStore:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self._state = self._read()

    def _read(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        raw = self.state_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def _write(self) -> None:
        tmp_path = self.state_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.state_path)

    def is_chunked(self, video_id: str) -> bool:
        record = self._state.get(video_id, {})
        return isinstance(record, dict) and record.get("status") == "chunked"

    def update(self, video_id: str, status: str, **fields: Any) -> None:
        record: dict[str, Any]
        existing = self._state.get(video_id)
        if isinstance(existing, dict):
            record = existing.copy()
        else:
            record = {}

        record["status"] = status
        record["updated_at"] = utc_now_iso()
        for key, value in fields.items():
            record[key] = value

        self._state[video_id] = record
        self._write()
