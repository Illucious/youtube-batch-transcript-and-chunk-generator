from __future__ import annotations

import logging
import queue
import threading
import traceback
import json
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import END, BOTH, LEFT, RIGHT, VERTICAL, X, Y, Text, StringVar, Tk
from tkinter import messagebox, ttk

from pipeline.chunker import chunk_transcript
from pipeline.manifest import fetch_manifest
from pipeline.state import StateStore, ensure_data_layout
from pipeline.transcriber import (
    cleanup_audio_file,
    download_audio,
    load_whisper_model,
    transcribe_audio,
)


MODELS = ["tiny", "base", "small", "medium", "large-v3"]


class IngestionGUI:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("YouTube to RAG Ingestion")
        self.root.geometry("920x640")

        self.app_dir = Path(__file__).resolve().parent
        self.data_dir = self.app_dir / "data"
        self.logs_dir = self.data_dir / "logs"
        ensure_data_layout(self.data_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.state_store = StateStore(self.data_dir / "state.json")
        self.event_queue: queue.Queue[dict] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.logger = self._setup_logger()

        self.url_var = StringVar()
        self.model_var = StringVar(value="base")

        self.total_var = StringVar(value="0")
        self.completed_var = StringVar(value="0")
        self.failed_var = StringVar(value="0")
        self.skipped_var = StringVar(value="0")

        self._build_ui()
        self._log(f"Logger initialized at {self.logs_dir / 'pipeline.log'}")
        self.root.after(120, self._drain_queue)

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("yt_to_rag_gui")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.handlers.clear()

        log_path = self.logs_dir / "pipeline.log"
        file_handler = RotatingFileHandler(
            log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        return logger

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=BOTH, expand=True)

        top = ttk.Frame(container)
        top.pack(fill=X)

        ttk.Label(top, text="Playlist/Channel URL:").pack(side=LEFT)
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.pack(side=LEFT, fill=X, expand=True, padx=(8, 8))

        ttk.Label(top, text="Model:").pack(side=LEFT)
        self.model_combo = ttk.Combobox(
            top, textvariable=self.model_var, values=MODELS, state="readonly", width=12
        )
        self.model_combo.pack(side=LEFT, padx=(8, 8))

        self.start_btn = ttk.Button(top, text="Start", command=self.start)
        self.start_btn.pack(side=LEFT)
        self.stop_btn = ttk.Button(
            top, text="Stop", command=self.stop, state="disabled"
        )
        self.stop_btn.pack(side=LEFT, padx=(8, 0))

        self.progress = ttk.Progressbar(container, mode="determinate")
        self.progress.pack(fill=X, pady=(12, 8))

        log_frame = ttk.LabelFrame(container, text="Live Log", padding=8)
        log_frame.pack(fill=BOTH, expand=True)

        self.log_widget = Text(log_frame, wrap="word", height=18)
        self.log_widget.configure(state="disabled")
        self.log_widget.tag_configure("INFO", foreground="#1f2937")
        self.log_widget.tag_configure("WARNING", foreground="#b45309")
        self.log_widget.tag_configure("ERROR", foreground="#b91c1c")

        scroll = ttk.Scrollbar(
            log_frame, orient=VERTICAL, command=self.log_widget.yview
        )
        self.log_widget.configure(yscrollcommand=scroll.set)

        self.log_widget.pack(side=LEFT, fill=BOTH, expand=True)
        scroll.pack(side=RIGHT, fill=Y)

        summary = ttk.LabelFrame(container, text="Summary", padding=8)
        summary.pack(fill=X, pady=(8, 0))

        ttk.Label(summary, text="Total:").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.total_var).grid(
            row=0, column=1, padx=(4, 18), sticky="w"
        )
        ttk.Label(summary, text="Completed:").grid(row=0, column=2, sticky="w")
        ttk.Label(summary, textvariable=self.completed_var).grid(
            row=0, column=3, padx=(4, 18), sticky="w"
        )
        ttk.Label(summary, text="Failed:").grid(row=0, column=4, sticky="w")
        ttk.Label(summary, textvariable=self.failed_var).grid(
            row=0, column=5, padx=(4, 18), sticky="w"
        )
        ttk.Label(summary, text="Skipped:").grid(row=0, column=6, sticky="w")
        ttk.Label(summary, textvariable=self.skipped_var).grid(
            row=0, column=7, padx=(4, 0), sticky="w"
        )

    def _log(self, message: str, level: str = "INFO") -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}\n"

        if level == "ERROR":
            self.logger.error(message)
        elif level == "WARNING":
            self.logger.warning(message)
        else:
            self.logger.info(message)

        self.log_widget.configure(state="normal")
        self.log_widget.insert(END, line, level)
        self.log_widget.configure(state="disabled")
        self.log_widget.see(END)

    def start(self) -> None:
        url = self.url_var.get().strip()
        model = self.model_var.get().strip()
        if not url:
            messagebox.showerror(
                "Missing URL", "Please provide a playlist or channel URL."
            )
            return
        if model not in MODELS:
            messagebox.showerror("Invalid model", "Select a valid Whisper model.")
            return
        if self.worker and self.worker.is_alive():
            return

        self.stop_event.clear()
        self._set_running(True)
        self._log("Starting pipeline...")
        self.worker = threading.Thread(
            target=self._run_pipeline, args=(url, model), daemon=True
        )
        self.worker.start()

    def stop(self) -> None:
        self.stop_event.set()
        self._log(
            "Stop requested. Pipeline will stop after the current video.", "WARNING"
        )
        self.stop_btn.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.url_entry.configure(state="disabled" if running else "normal")
        self.model_combo.configure(state="disabled" if running else "readonly")

    def _emit_log(self, message: str, level: str = "INFO") -> None:
        self.event_queue.put({"type": "log", "message": message, "level": level})

    def _emit_summary(
        self, total: int, completed: int, failed: int, skipped: int
    ) -> None:
        self.event_queue.put(
            {
                "type": "summary",
                "total": total,
                "completed": completed,
                "failed": failed,
                "skipped": skipped,
            }
        )
        processed = completed + failed + skipped
        progress = 0.0 if total == 0 else (processed / total) * 100.0
        self.event_queue.put({"type": "progress", "value": progress})

    def _run_pipeline(self, url: str, model_name: str) -> None:
        try:
            manifest_path = self.data_dir / "manifest.json"
            transcripts_dir = self.data_dir / "transcripts"
            chunks_dir = self.data_dir / "chunks"
            audio_dir = self.data_dir / "audio"

            self._emit_log("Fetching manifest from YouTube...")
            videos = fetch_manifest(url, manifest_path, self._emit_log)
            self._emit_log(f"Manifest ready with {len(videos)} videos.")

            self._emit_log(f"Loading Whisper model: {model_name}...")
            whisper_model = load_whisper_model(model_name, self._emit_log)
            self._emit_log("Whisper model loaded.")

            completed = 0
            failed = 0
            skipped = 0
            total = len(videos)
            self._emit_summary(total, completed, failed, skipped)

            for index, video in enumerate(videos, start=1):
                video_id = video["video_id"]
                title = video.get("title") or video_id

                if self.stop_event.is_set():
                    self._emit_log("Stop requested. Halting before next video.")
                    break

                if self.state_store.is_chunked(video_id):
                    skipped += 1
                    self._emit_log(
                        f"[{index}/{total}] Skipping {video_id} (already chunked)."
                    )
                    self._emit_summary(total, completed, failed, skipped)
                    continue

                self._emit_log(f"[{index}/{total}] Processing {video_id}: {title}")
                audio_path: Path | None = None
                try:
                    self.state_store.update(video_id, "manifested", title=title)

                    audio_path = download_audio(
                        video_id, video["url"], audio_dir, self._emit_log
                    )
                    self.state_store.update(
                        video_id, "audio_downloaded", audio_path=str(audio_path)
                    )

                    transcript = transcribe_audio(
                        whisper_model, audio_path, self._emit_log
                    )
                    transcript_path = transcripts_dir / f"{video_id}.json"
                    transcript_path.write_text(
                        json.dumps(transcript, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    self.state_store.update(
                        video_id, "transcribed", transcript_path=str(transcript_path)
                    )

                    chunks_json = chunk_transcript(
                        transcript_path, video, self._emit_log
                    )
                    chunk_path = chunks_dir / f"{video_id}.json"
                    chunk_path.write_text(
                        json.dumps(chunks_json, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    self.state_store.update(
                        video_id, "chunked", chunk_path=str(chunk_path), last_error=None
                    )

                    cleanup_audio_file(audio_path, self._emit_log)
                    completed += 1
                    self._emit_log(
                        f"Completed {video_id} with {len(chunks_json)} chunks."
                    )
                except Exception as exc:
                    failed += 1
                    self.state_store.update(video_id, "failed", last_error=str(exc))
                    self._emit_log(f"Failed {video_id}: {exc}", "ERROR")
                    if audio_path is not None:
                        cleanup_audio_file(audio_path, self._emit_log)
                finally:
                    self._emit_summary(total, completed, failed, skipped)

            self._emit_log("Pipeline run finished.")
            self.event_queue.put({"type": "done"})
        except Exception as exc:
            self._emit_log(f"Fatal pipeline error: {exc}", "ERROR")
            self._emit_log(traceback.format_exc(), "ERROR")
            self.event_queue.put({"type": "done"})

    def _drain_queue(self) -> None:
        while True:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event.get("type")
            if event_type == "log":
                self._log(event["message"], event.get("level", "INFO"))
            elif event_type == "progress":
                self.progress["value"] = event["value"]
            elif event_type == "summary":
                self.total_var.set(str(event["total"]))
                self.completed_var.set(str(event["completed"]))
                self.failed_var.set(str(event["failed"]))
                self.skipped_var.set(str(event["skipped"]))
            elif event_type == "done":
                self._set_running(False)

        self.root.after(120, self._drain_queue)


def launch_app() -> None:
    root = Tk()
    root.minsize(820, 560)
    IngestionGUI(root)
    root.mainloop()
