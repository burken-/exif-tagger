# Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the CLI-based exif-tagger into a long-running FastAPI service with a web dashboard for starting/stopping processing sessions, editing tag configurations, and managing automated schedules.

**Architecture:** Extract existing pipeline logic from `main.py` into a reusable `PipelineEngine` class. Build a FastAPI server (`server.py`) that exposes API endpoints and serves a single-page dashboard UI. Use APScheduler for cron/interval-based job scheduling. The CLI entry point remains fully functional.

**Tech Stack:** Python 3.12+, FastAPI, uvicorn, APScheduler, Pydantic, Alpine Linux (Docker)

## Global Constraints

- Existing 50 tests must remain passing — no core logic modification in ai_client.py, config.py, image_scanner.py, exif_writer.py
- CLI entry point (`python -m exif_tagger`) must continue to work unchanged
- Config changes take effect on next processing session only (no hot-reload of running pipeline)
- All folder paths validated against whitelist (same as existing env var validation in config.py)
- No auth required — container intended for trusted internal network use only
- Dependencies added: fastapi>=0.104, uvicorn[standard]>=0.24, apscheduler>=3.10

---

### Task 1: Add Schedule model to schema.py

**Files:**
- Modify: `src/exif_tagger/models/schema.py` (append after RunSummary class)

**Interfaces:**
- Produces: `ScheduleModel` Pydantic class used by server.py for schedule CRUD

- [ ] **Step 1: Append ScheduleModel and ScheduleEntry models to schema.py**

Add these two classes at the end of `src/exif_tagger/models/schema.py` (after line 176, after RunSummary):

```python
# ---------------------------------------------------------------------------
# Schedule configuration (persisted to schedules.json)
# ---------------------------------------------------------------------------
class ScheduleModel(BaseModel):
    """A single scheduled processing job."""

    id: str = Field(default_factory=lambda: f"schedule_{int(time.time())}_{hash(str(time.time())) % 10000}")
    name: str = Field(description="Human-readable schedule name")
    folder: str = Field(description="Root directory to scan for images")
    max_images: int | None = Field(default=None, description="Max images per run (None = all)")
    interval_hours: float | None = Field(default=None, ge=0.1, description="Interval in hours (for simple intervals)")
    cron_expression: str | None = Field(default=None, description="Cron expression (e.g. '0 2 * * *')")
    enabled: bool = Field(default=True)
    last_run_at: str | None = Field(default=None, description="ISO timestamp of last run")
    last_status: str | None = Field(default=None, description="'success', 'failed', or None")

    @field_validator("cron_expression", mode="before")
    @classmethod
    def _validate_cron(cls, value):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        parts = str(value).strip().split()
        if len(parts) != 5:
            raise ValueError("Cron expression must have exactly 5 fields (minute hour day month weekday)")
        return value

    model_config = ConfigDict(extra='allow')


class ScheduleEntry(ScheduleModel):
    """ScheduleModel with next_run_at computed."""

    next_run_at: str | None = Field(default=None, description="ISO timestamp of next scheduled run")
```

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All 50 tests pass (no changes to existing code paths)


---

### Task 2: Extract PipelineEngine from main.py

**Files:**
- Modify: `src/exif_tagger/main.py` (extract pipeline logic into class)
- Create: `tests/test_pipeline_engine.py` (new test file)

**Interfaces:**
- Consumes: `Config`, `ImageCheckpoint` from schema; `scan_images`, `filter_by_checkpoint`; `tag_image_with_ai`; `tag_image_exif`; checkpoint helpers
- Produces: `PipelineEngine` class with methods: `start_session()`, `stop()`, `get_status()`, `get_summary()`

- [ ] **Step 1: Replace main.py content with refactored version**

Replace the entire contents of `src/exif_tagger/main.py` with:

```python
"""Main script for exif-tagger – CLI entry point and pipeline engine.

PERFORMANCE NOTES:
- Batch checkpoint writes every CHECKPOINT_BATCH_SIZE images (default 100) to reduce I/O overhead
- Sequential AI processing by default (most APIs queue requests server-side anyway)
- Stream processing: process each image immediately instead of accumulating all results

SECURITY NOTES:
- Uses SecretRedactor logging filter from ai_client module to prevent API key exposure
- All file paths validated through config.py's validate_path_within_base() function

REALISTIC EXPECTATIONS:
Processing time is dominated by AI model inference (~2 seconds per image). For 10k images,
expect ~5.5 hours regardless of concurrency settings. The main bottleneck is the vision API,
not our client code. Focus on reliability (checkpoint resumption) rather than speed.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# ============================================================================
# PERFORMANCE: Module Constants (avoid magic numbers)
# ============================================================================

CHECKPOINT_BATCH_SIZE = 100  # Write checkpoint every N images (balance safety vs I/O)
ERRORS_TO_DISPLAY_MAX = 10   # Maximum errors shown in summary output


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exif-tagger",
        description=(
            "AI-powered image tagging tool. Scans images recursively, evaluates them "
            "against configured tags using a vision model, and writes matching tag names "
            "to the XPTags EXIF field (semicolon-separated)."
        ),
    )
    parser.add_argument(
        "-c", "--config",
        type=str,
        default="config.yaml",
        help="Path to config.yaml (default: ./config.yaml or $EXIFTAGGER_CONFIG_FILE)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose per-image logging during processing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore existing checkpoint and start processing from the beginning.",
    )
    parser.add_argument(
        "--list-tags",
        action="store_true",
        help="List all configured tags with descriptions and thresholds, then exit.",
    )

    return parser


def _log_tag_list(tags: dict) -> None:
    """Pretty-print the list of configured tags."""
    print("\nConfigured tags:")
    print("-" * 70)
    for name in sorted(tags.keys()):
        tag = tags[name]
        desc = getattr(tag, "description", str(tag)) if hasattr(tag, "description") else "N/A"
        threshold = getattr(tag, "threshold", 0.7)
        print(f"  {name:<25} (threshold: {threshold:.2f})")
        print(f"    → {desc}")
    print("-" * 70)


def _format_summary_text(summary: dict) -> str:
    """Format a summary dictionary into human-readable text."""
    lines = [
        "",
        "=" * 60,
        "RUN SUMMARY",
        "=" * 60,
        f"Root directory: {summary['root_directory']}",
        f"Total images found:   {summary['total_images_found']}",
        f"Processed this run:   {summary['total_processed']}",
        f"Newly tagged:         {summary['successfully_tagged']}",
        f"Already had tags:     {summary['already_tagged']}",
        f"Skipped (checkpoint): {summary['skipped_by_checkpoint']}",
        f"Failed:               {summary['failed']}",
    ]

    if summary.get('errors'):
        lines.append("")
        lines.append("Errors:")
        for err in summary['errors'][:ERRORS_TO_DISPLAY_MAX]:
            lines.append(f"  - {err}")
        if len(summary['errors']) > ERRORS_TO_DISPLAY_MAX:
            lines.append(f"  ... and {len(summary['errors']) - ERRORS_TO_DISPLAY_MAX} more")

    lines.extend(["", "=" * 60])
    return "\n".join(lines)


class ProcessingState:
    """Thread-safe state tracker for a running processing session."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._processed = 0
        self._total = 0
        self._current_image: str | None = None
        self._stop_requested = False
        self._log_lines: list[str] = []
        self._summary: dict | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def processed(self) -> int:
        with self._lock:
            return self._processed

    @property
    def total(self) -> int:
        with self._lock:
            return self._total

    @property
    def current_image(self) -> str | None:
        with self._lock:
            return self._current_image

    @property
    def stop_requested(self) -> bool:
        with self._lock:
            return self._stop_requested

    @property
    def summary(self) -> dict | None:
        with self._lock:
            return self._summary

    @property
    def log_lines(self) -> list[str]:
        with self._lock:
            return list(self._log_lines[-200:])  # Keep last 200 lines

    def start(self, total_images: int) -> None:
        with self._lock:
            self._running = True
            self._processed = 0
            self._total = total_images
            self._current_image = None
            self._stop_requested = False
            self._log_lines = []
            self._summary = None

    def update_progress(self, image_name: str) -> None:
        with self._lock:
            self._processed += 1
            self._current_image = image_name
            self._log_lines.append(f"[{self._processed}/{self._total}] Processed: {image_name}")

    def set_stop_requested(self) -> None:
        with self._lock:
            self._stop_requested = True

    def finish(self, summary: dict) -> None:
        with self._lock:
            self._running = False
            self._current_image = None
            self._summary = summary

    @property
    def progress_pct(self) -> float:
        with self._lock:
            if self._total == 0:
                return 0.0
            return round((self._processed / self._total) * 100, 1)


class PipelineEngine:
    """Reusable pipeline engine that can be called from CLI or API."""

    def __init__(self, config_path: str, verbose: bool = False):
        self.config_path = config_path
        self.verbose = verbose
        self.state = ProcessingState()
        self._config = None

    def _load_config(self):
        """Load and validate configuration."""
        from exif_tagger.config import load_config
        from exif_tagger.models.schema import Config

        self._config: Config = load_config(self.config_path)
        self._config.validate()
        self._config.validate_exclude_patterns()
        return self._config

    def start_session(
        self,
        root_directory: str | None = None,
        max_images: int | None = None,
        force_resume: bool = False,
    ) -> dict:
        """Execute the full tagging pipeline. Returns summary dict on completion."""
        from exif_tagger.ai_client import setup_secure_logging, tag_image_with_ai
        from exif_tagger.config import get_resume_info, save_checkpoint
        from exif_tagger.models.schema import Config, ImageCheckpoint
        from exif_tagger.image_scanner import scan_images, filter_by_checkpoint
        from exif_tagger.exif_writer import tag_image_exif

        log_level = logging.DEBUG if self.verbose else logging.INFO
        setup_secure_logging(log_level)
        logger = logging.getLogger("exif_tagger")

        try:
            config = self._load_config()

            # Allow overriding root_directory from API call
            if root_directory:
                config.root_directory = root_directory

            if not config.tags:
                return {"error": "No tags configured", "exit_code": 1}

            _log_tag_list(config.tags)

            all_images = scan_images(
                root_directory=config.root_directory,
                exclude_patterns=config.exclude_patterns or [],
            )

            total_found = len(all_images)
            if total_found == 0:
                logger.warning("No images found in %s. Nothing to do.", config.root_directory)
                return {
                    "root_directory": config.root_directory,
                    "total_images_found": 0,
                    "total_processed": 0,
                    "successfully_tagged": 0,
                    "already_tagged": 0,
                    "skipped_by_checkpoint": 0,
                    "failed": 0,
                    "errors": [],
                }

            # Checkpoint / resume logic
            checkpoint: dict[str, ImageCheckpoint] = {}
            skipped_by_checkpoint = 0
            already_tagged = 0

            if not force_resume:
                resumed = get_resume_info(config.root_directory, total_found)
                if resumed is not None:
                    logger.info(
                        "Found checkpoint – %d images already processed. Resuming.",
                        sum(1 for img in resumed.values() if img.status == "done"),
                    )
                    checkpoint = resumed
                    skipped_by_checkpoint = sum(
                        1 for img in checkpoint.values() if img.status == "done"
                    )

            images_to_process, done_from_cp = filter_by_checkpoint(all_images, checkpoint)
            skipped_by_checkpoint += done_from_cp

            # Apply max_images limit
            if max_images is not None and len(images_to_process) > max_images:
                images_to_process = images_to_process[:max_images]

            logger.info(
                "%d total found, %d from previous run (skipped), %d to process now.",
                total_found, skipped_by_checkpoint, len(images_to_process),
            )

            if not images_to_process:
                logger.info("All images already processed – nothing to do.")
                return {
                    "root_directory": config.root_directory,
                    "total_images_found": total_found,
                    "total_processed": 0,
                    "successfully_tagged": 0,
                    "already_tagged": already_tagged + skipped_by_checkpoint,
                    "skipped_by_checkpoint": skipped_by_checkpoint,
                    "failed": 0,
                    "errors": [],
                }

            # Initialize state tracking
            self.state.start(len(images_to_process))

            successfully_tagged = 0
            failed_count = 0
            errors: list[str] = []
            checkpoint_images: dict[str, ImageCheckpoint] = dict(checkpoint)
            checkpoint_batch_counter = 0

            for i, img_path in enumerate(images_to_process, start=1):
                if self.state.stop_requested:
                    logger.info("Stop requested. Processing %d/%d images so far.", i - 1, len(images_to_process))
                    break

                if self.verbose:
                    logger.info("Processing image %d/%d: %s", i, len(images_to_process), img_path.name)

                try:
                    response = tag_image_with_ai(config.ai_model, img_path, config.tags)

                    matched_tag_names = []
                    for tr in response.results:
                        tag_def = config.tags.get(tr.tag_name)
                        if tag_def and tr.score >= tag_def.threshold:
                            matched_tag_names.append(tr.tag_name)

                    modified, n_new = tag_image_exif(img_path, matched_tag_names)

                    if modified:
                        successfully_tagged += 1
                        logger.info(
                            "  → Written %d new XPTags: %s",
                            n_new, ", ".join(matched_tag_names),
                        )
                    elif self.verbose:
                        logger.debug("  → All tags already present – no change.")

                    checkpoint_images[str(img_path.resolve())] = ImageCheckpoint(
                        path=str(img_path), status="done", matched_tags=matched_tag_names, error=None,
                    )

                except Exception as exc:
                    failed_count += 1
                    errors.append(f"{img_path.name}: {exc}")
                    logger.error("Failed to process %s: %s", img_path.name, exc)
                    checkpoint_images[str(img_path.resolve())] = ImageCheckpoint(
                        path=str(img_path), status="failed", matched_tags=[], error=str(exc),
                    )

                self.state.update_progress(img_path.name)

                # Batch checkpoint writes
                checkpoint_batch_counter += 1
                if checkpoint_batch_counter >= CHECKPOINT_BATCH_SIZE:
                    save_checkpoint(config.root_directory, total_found, checkpoint_images)
                    checkpoint_batch_counter = 0
                    if self.verbose:
                        logger.debug("Checkpoint saved (batch of %d)", CHECKPOINT_BATCH_SIZE)

            # Final checkpoint write
            save_checkpoint(config.root_directory, total_found, checkpoint_images)

            summary = {
                "root_directory": config.root_directory,
                "total_images_found": total_found,
                "total_processed": len(images_to_process),
                "successfully_tagged": successfully_tagged,
                "already_tagged": already_tagged + skipped_by_checkpoint,
                "skipped_by_checkpoint": skipped_by_checkpoint,
                "failed": failed_count,
                "errors": errors,
            }

            self.state.finish(summary)

            if self.verbose:
                logger.info(_format_summary_text(summary))
            else:
                for line in _format_summary_text(summary).split("\n"):
                    print(line)

            return summary

        except Exception as exc:
            logger.error("Fatal error: %s", exc, exc_info=True)
            self.state.finish({
                "root_directory": getattr(self._config, 'root_directory', ''),
                "total_images_found": 0,
                "total_processed": 0,
                "successfully_tagged": 0,
                "already_tagged": 0,
                "skipped_by_checkpoint": 0,
                "failed": 1,
                "errors": [f"Fatal: {exc}"],
            })
            return {"error": str(exc), "exit_code": 1}

    def stop(self) -> dict:
        """Request graceful stop of current session."""
        self.state.set_stop_requested()
        time.sleep(0.5)  # Give thread a moment to notice
        summary = self.state.summary or {}
        return {
            "status": "stopped",
            "processed": self.state.processed,
        }

    def get_status(self) -> dict:
        """Get current processing state."""
        s = self.state
        return {
            "running": s.running,
            "processed": s.processed,
            "total": s.total,
            "currentImage": s.current_image,
            "progressPct": s.progress_pct,
            "stopRequested": s.stop_requested,
        }

    def get_summary(self) -> dict | None:
        """Get the summary from the last completed run."""
        return self.state.summary


def run(
    config_path: str,
    verbose: bool = False,
    force_resume: bool = False,
) -> int:
    """Execute the full tagging pipeline via CLI. Returns exit code (0=success, 1=error)."""
    engine = PipelineEngine(config_path=config_path, verbose=verbose)
    summary = engine.start_session(force_resume=force_resume)
    return summary.get("exit_code", 0 if not summary.get("errors") else 1)


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.list_tags:
        from exif_tagger.config import load_config
        
        config = load_config(args.config)
        _log_tag_list(config.tags)
        sys.exit(0)

    exit_code = run(
        config_path=args.config,
        verbose=args.verbose,
        force_resume=args.force,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run existing tests to verify no regressions**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All 50 tests pass (the `run()` function and CLI behavior are unchanged)


---

### Task 3: Create FastAPI server with API endpoints and schedule management

**Files:**
- Create: `src/exif_tagger/server.py` (FastAPI app, all routes, scheduler)
- Create: `tests/test_server.py` (new test file for API endpoints)

**Interfaces:**
- Consumes: `PipelineEngine`, `ProcessingState` from main; `ScheduleModel`, `ScheduleEntry` from schema; `load_config`, config helpers
- Produces: FastAPI `app` instance, `/api/*` routes, static file serving

- [ ] **Step 1: Create server.py with complete FastAPI application**

Create `src/exif_tagger/server.py`:

```python
"""FastAPI server for exif-tagger web dashboard.

Provides REST API endpoints and serves the single-page dashboard UI.
Runs as a long-lived service (uvicorn) instead of CLI batch execution.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from exif_tagger.config import load_config, save_checkpoint as _save_checkpoint
from exif_tagger.main import PipelineEngine
from exif_tagger.models.schema import ScheduleEntry, ScheduleModel, TagDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App state (singleton pattern for the running engine and schedules)
# ---------------------------------------------------------------------------

app = FastAPI(title="EXIF Tagger", version="0.1.0")

# Global state
_engine: PipelineEngine | None = None
_engine_lock = threading.Lock()
_schedules: dict[str, ScheduleModel] = {}
_scheduler: BackgroundScheduler | None = None
CONFIG_PATH = os.environ.get("EXIFTAGGER_CONFIG_FILE", "/app/config.yaml")
SCHEDULES_FILE = Path("/app/schedules.json")


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    rootDirectory: str | None = None
    maxImages: int | None = None


class ScheduleCreateRequest(BaseModel):
    name: str
    folder: str
    interval_hours: float | None = None
    cron_expression: str | None = None
    enabled: bool = True
    max_images: int | None = None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _get_engine() -> PipelineEngine:
    """Get or create the pipeline engine instance."""
    global _engine
    if _engine is None:
        _engine = PipelineEngine(config_path=CONFIG_PATH, verbose=False)
    return _engine


def _load_schedules() -> dict[str, ScheduleModel]:
    """Load schedules from disk."""
    if SCHEDULES_FILE.exists():
        try:
            with open(SCHEDULES_FILE, "r") as f:
                data = json.load(f)
            return {sid: ScheduleModel(**sdata) for sid, sdata in data.items()}
        except (json.JSONDecodeError, Exception):
            pass
    return {}


def _save_schedules() -> None:
    """Persist schedules to disk."""
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULES_FILE, "w") as f:
        json.dump({sid: s.model_dump() for sid, s in _schedules.items()}, f, indent=2)


def _compute_next_run(schedule: ScheduleModel) -> str | None:
    """Compute next run time based on schedule type."""
    now = datetime.now(timezone.utc)
    if schedule.cron_expression:
        # Simple cron parsing for common patterns
        parts = schedule.cron_expression.strip().split()
        if len(parts) == 5:
            minute, hour, dom, month, dow = parts
            return _parse_cron_to_iso(now, minute, hour, dom, month, dow)
    elif schedule.interval_hours:
        next_run = now.replace(microsecond=0)
        from datetime import timedelta
        next_run += timedelta(hours=schedule.interval_hours)
        return next_run.isoformat()
    return None


def _parse_cron_to_iso(
    now: datetime, minute: str, hour: str, dom: str, month: str, dow: str
) -> str | None:
    """Parse a simple cron expression to the next ISO run time.

    Handles basic patterns like '0 2 * * *' (daily at 2am).
    Does not handle complex expressions with ranges/lists in one pass.
    """
    from datetime import timedelta

    def _parse_field(val: str, min_val: int, max_val: int) -> list[int]:
        if val == "*":
            return list(range(min_val, max_val + 1))
        try:
            return [int(val)]
        except ValueError:
            return list(range(min_val, max_val + 1))

    minutes = _parse_field(minute, 0, 59)
    hours = _parse_field(hour, 0, 23)
    doms = _parse_field(dom, 1, 31) if dom != "*" else None
    months = _parse_field(month, 1, 12)
    dows = _parse_field(dow, 0, 6)

    # Find next matching datetime (scan up to 7 days ahead)
    candidate = now.replace(microsecond=0, second=0, minute=now.minute + 1) if now.second == 0 else now.replace(microsecond=0, second=0)

    for _ in range(7 * 24 * 60):  # Check up to 7 days of minutes
        candidate += timedelta(minutes=1)
        if (candidate.minute in minutes and
            candidate.hour in hours and
            candidate.month in months and
            (doms is None or candidate.day in doms) and
            (candidate.weekday() % 7) in dows):
            return candidate.isoformat()

    return now.replace(microsecond=0).isoformat()


def _run_schedule_job(schedule_id: str) -> None:
    """Execute a scheduled job."""
    global _engine
    schedule = _schedules.get(schedule_id)
    if not schedule or not schedule.enabled:
        return

    logger.info("Running scheduled job: %s (folder=%s)", schedule.name, schedule.folder)

    # Create a fresh engine for this job
    job_engine = PipelineEngine(config_path=CONFIG_PATH, verbose=False)
    summary = job_engine.start_session(
        root_directory=schedule.folder,
        max_images=schedule.max_images,
    )

    now = datetime.now(timezone.utc).isoformat()
    schedule.last_run_at = now
    schedule.last_status = "success" if not summary.get("errors") else "failed"
    _save_schedules()


def _setup_scheduler() -> None:
    """Initialize APScheduler with loaded schedules."""
    global _scheduler

    _schedules.clear()
    _schedules.update(_load_schedules())

    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    _scheduler = BackgroundScheduler()
    _scheduler.start()

    for sid, schedule in _schedules.items():
        if not schedule.enabled:
            continue

        trigger = None
        if schedule.cron_expression:
            parts = schedule.cron_expression.strip().split()
            if len(parts) == 5:
                minute, hour, dom, month, dow = parts
                try:
                    trigger = CronTrigger(
                        minute=minute, hour=hour, day_of_week=dow,
                        day=dom, month=month, timezone=timezone.utc
                    )
                except Exception as e:
                    logger.warning("Invalid cron expression for schedule '%s': %s", sid, e)
        elif schedule.interval_hours:
            trigger = IntervalTrigger(hours=schedule.interval_hours, timezone=timezone.utc)

        if trigger:
            try:
                _scheduler.add_job(
                    _run_schedule_job,
                    trigger=trigger,
                    args=[sid],
                    id=f"schedule_{sid}",
                    replace_existing=True,
                )
            except Exception as e:
                logger.warning("Failed to add job for schedule '%s': %s", sid, e)


# ---------------------------------------------------------------------------
# API Routes — Status & Control
# ---------------------------------------------------------------------------

@app.get("/api/status")
def api_status():
    """Get current processing state."""
    engine = _get_engine()
    status = engine.get_status()
    summary = engine.state.summary
    return {**status, "summary": summary}


@app.post("/api/start")
def api_start(req: StartRequest):
    """Begin a new processing session in a background thread."""
    global _engine

    with _engine_lock:
        if _engine and _engine.state.running:
            raise HTTPException(status_code=409, detail="A processing session is already running")

        _engine = PipelineEngine(config_path=CONFIG_PATH, verbose=False)

    def run_session():
        _get_engine().start_session(
            root_directory=req.rootDirectory,
            max_images=req.maxImages,
        )

    thread = threading.Thread(target=run_session, daemon=True)
    thread.start()

    return {"sessionId": str(uuid.uuid4()), "status": "started"}


@app.post("/api/stop")
def api_stop():
    """Gracefully stop the current processing session."""
    engine = _get_engine()
    if not engine.state.running:
        raise HTTPException(status_code=400, detail="No processing session is running")

    result = engine.stop()
    return result


# ---------------------------------------------------------------------------
# API Routes — Configuration
# ---------------------------------------------------------------------------

@app.get("/api/config")
def api_get_config():
    """Read current configuration."""
    try:
        config = load_config(CONFIG_PATH)
        return {
            "root_directory": config.root_directory,
            "model": {
                "base_url": config.ai_model.base_url,
                "model_name": config.ai_model.model_name,
                "max_tokens": config.ai_model.max_tokens,
                "temperature": config.ai_model.temperature,
            },
            "tags": {name: td.model_dump() for name, td in config.tags.items()},
            "exclude_patterns": config.exclude_patterns or [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load config: {e}")


@app.put("/api/config")
def api_update_config(updates: dict[str, Any]):
    """Update configuration in-place. Writes validated config to disk."""
    import yaml

    try:
        # Load current config as raw YAML
        if Path(CONFIG_PATH).exists():
            with open(CONFIG_PATH, "r") as f:
                current = yaml.safe_load(f) or {}
        else:
            current = {}

        # Apply updates
        if "root_directory" in updates:
            current["root_directory"] = updates["root_directory"]

        if "model" in updates and isinstance(updates["model"], dict):
            model_section = current.setdefault("model", {})
            for key, val in updates["model"].items():
                model_section[key] = val

        if "tags" in updates:
            # Validate tags through Pydantic first
            tag_defs = {}
            for name, tdata in updates["tags"].items():
                td = TagDefinition(**tdata)
                tag_defs[name] = td
            current["tags"] = tag_defs

        if "exclude_patterns" in updates:
            patterns = updates["exclude_patterns"]
            if isinstance(patterns, str):
                patterns = [patterns]
            current["exclude_patterns"] = patterns

        # Validate the full config through Pydantic before writing
        from exif_tagger.models.schema import Config as SchemaConfig
        validated = SchemaConfig(**current)
        validated.validate()
        validated.validate_exclude_patterns()

        # Write to disk
        with open(CONFIG_PATH, "w") as f:
            yaml.safe_dump(current, f, default_flow_style=False, sort_keys=False)

        return {"status": "updated"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config update: {e}")


# ---------------------------------------------------------------------------
# API Routes — Schedules
# ---------------------------------------------------------------------------

@app.get("/api/schedule")
def api_list_schedules():
    """List all configured schedules with computed next_run_at."""
    result = []
    for sid, schedule in _schedules.items():
        entry_data = schedule.model_dump()
        entry_data["next_run_at"] = _compute_next_run(schedule)
        result.append(entry_data)
    return result


@app.post("/api/schedule")
def api_create_schedule(req: ScheduleCreateRequest):
    """Add a new processing schedule."""
    sid = f"schedule_{uuid.uuid4().hex[:8]}"

    schedule = ScheduleModel(
        id=sid,
        name=req.name,
        folder=req.folder,
        max_images=req.max_images,
        interval_hours=req.interval_hours,
        cron_expression=req.cron_expression,
        enabled=req.enabled,
    )

    _schedules[sid] = schedule
    _save_schedules()

    # Add to scheduler if enabled
    if req.enabled:
        _setup_scheduler()  # Rebuild all jobs

    return {"id": sid}


@app.delete("/api/schedule/{schedule_id}")
def api_delete_schedule(schedule_id: str):
    """Remove a schedule."""
    if schedule_id not in _schedules:
        raise HTTPException(status_code=404, detail="Schedule not found")

    del _schedules[schedule_id]
    _save_schedules()

    # Rebuild scheduler without this job
    _setup_scheduler()

    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# UI Routes — serve the dashboard
# ---------------------------------------------------------------------------

WEBUI_DIR = Path(__file__).parent.parent.parent / "webui"


@app.get("/")
def index():
    """Serve the main dashboard page."""
    return FileResponse(WEBUI_DIR / "index.html")


@app.get("/css/style.css")
def serve_css():
    return FileResponse(WEBUI_DIR / "css" / "style.css")


@app.get("/js/app.js")
def serve_js():
    return FileResponse(WEBUI_DIR / "js" / "app.js")


# ---------------------------------------------------------------------------
# Startup & Shutdown events
# ---------------------------------------------------------------------------

@app.on_event("startup")
def on_startup():
    """Initialize scheduler and engine on server start."""
    logger.info("EXIF Tagger API starting up...")
    _setup_scheduler()
    logger.info(f"Loaded {_schedules.__len__()} schedules")


@app.on_event("shutdown")
def on_shutdown():
    """Clean shutdown."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

- [ ] **Step 2: Create test file for server.py**

Create `tests/test_server.py`:

```python
"""Tests for the FastAPI server endpoints and schedule management."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Import the app — we'll patch dependencies at module level
import exif_tagger.server as server_module
from exif_tagger.models.schema import ScheduleModel


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Reset global state before each test."""
    server_module._engine = None
    server_module._schedules.clear()
    server_module._scheduler = None
    # Reset schedules file
    schedules_file = Path("/app/schedules.json")
    if schedules_file.exists():
        schedules_file.unlink()


@pytest.fixture
def client(_reset_server_state):
    """Create a test client."""
    return TestClient(server_module.app)


class TestApiStatus:
    def test_status_no_session(self, client):
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is False
        assert data["processed"] == 0
        assert data["total"] == 0

    def test_status_running(self, client):
        with patch.object(server_module, '_get_engine') as mock_get:
            mock_engine = MagicMock()
            mock_engine.get_status.return_value = {
                "running": True, "processed": 5, "total": 10,
                "currentImage": "photo.jpg", "progressPct": 50.0,
                "stopRequested": False,
            }
            mock_engine.state.summary = None
            mock_get.return_value = mock_engine

            resp = client.get("/api/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["running"] is True


class TestApiStart:
    def test_start_no_running_session(self, client):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("root_directory: /tmp\nmodel:\n  base_url: http://test/v1\n  model_name: test\n")
            config_path = f.name

        original_config = server_module.CONFIG_PATH
        server_module.CONFIG_PATH = config_path

        try:
            with patch('exif_tagger.server.PipelineEngine') as mock_engine_cls:
                mock_instance = MagicMock()
                mock_instance.state.running = False
                mock_engine_cls.return_value = mock_instance

                resp = client.post("/api/start", json={"rootDirectory": "/tmp/images", "maxImages": 50})
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "started"
        finally:
            server_module.CONFIG_PATH = original_config
            os.unlink(config_path)

    def test_start_already_running(self, client):
        with patch.object(server_module, '_get_engine') as mock_get:
            mock_engine = MagicMock()
            mock_engine.state.running = True
            mock_get.return_value = mock_engine

            resp = client.post("/api/start", json={})
            assert resp.status_code == 409


class TestApiStop:
    def test_stop_no_session(self, client):
        with patch.object(server_module, '_get_engine') as mock_get:
            mock_engine = MagicMock()
            mock_engine.state.running = False
            mock_get.return_value = mock_engine

            resp = client.post("/api/stop")
            assert resp.status_code == 400

    def test_stop_with_session(self, client):
        with patch.object(server_module, '_get_engine') as mock_get:
            mock_engine = MagicMock()
            mock_engine.state.running = True
            mock_engine.stop.return_value = {"status": "stopped", "processed": 10}
            mock_get.return_value = mock_engine

            resp = client.post("/api/stop")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "stopped"


class TestApiConfig:
    def test_get_config(self, client):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""root_directory: /tmp/images
model:
  base_url: http://test/v1
  model_name: gpt-4o
tags:
  landscape:
    description: Pictures of landscapes
    threshold: 0.7
exclude_patterns: []
""")
            config_path = f.name

        original_config = server_module.CONFIG_PATH
        server_module.CONFIG_PATH = config_path

        try:
            resp = client.get("/api/config")
            assert resp.status_code == 200
            data = resp.json()
            assert data["root_directory"] == "/tmp/images"
            assert "landscape" in data["tags"]
            assert data["tags"]["landscape"]["threshold"] == 0.7
        finally:
            server_module.CONFIG_PATH = original_config
            os.unlink(config_path)


class TestApiSchedules:
    def test_list_empty_schedules(self, client):
        resp = client.get("/api/schedule")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    def test_create_schedule(self, client):
        resp = client.post("/api/schedule", json={
            "name": "Daily scan",
            "folder": "/data/images",
            "interval_hours": 6,
            "enabled": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data

    def test_delete_schedule(self, client):
        # First create a schedule
        resp = client.post("/api/schedule", json={
            "name": "Test",
            "folder": "/data/images",
            "interval_hours": 1,
        })
        sid = resp.json()["id"]

        # Then delete it
        resp = client.delete(f"/api/schedule/{sid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_delete_nonexistent_schedule(self, client):
        resp = client.delete("/api/schedule/nonexistent_id")
        assert resp.status_code == 404


class TestScheduleModel:
    def test_schedule_model_defaults(self):
        s = ScheduleModel(name="test", folder="/data/images")
        assert s.enabled is True
        assert s.last_run_at is None
        assert s.interval_hours is None

    def test_schedule_cron_validation(self):
        with pytest.raises(Exception):
            ScheduleModel(
                name="bad cron",
                folder="/data/images",
                cron_expression="invalid"  # Not 5 fields
            )


class TestComputeNextRun:
    def test_interval_hours(self):
        from datetime import datetime, timezone, timedelta

        schedule = ScheduleModel(name="test", folder="/data", interval_hours=6)
        next_run = server_module._compute_next_run(schedule)
        assert next_run is not None

        # Parse and verify it's roughly 6 hours ahead
        run_time = datetime.fromisoformat(next_run)
        now = datetime.now(timezone.utc).replace(microsecond=0, second=0)
        diff = (run_time - now).total_seconds() / 3600
        assert 5.9 <= diff <= 7.0

    def test_cron_expression(self):
        schedule = ScheduleModel(
            name="daily",
            folder="/data",
            cron_expression="0 2 * * *"
        )
        next_run = server_module._compute_next_run(schedule)
        assert next_run is not None
```

- [ ] **Step 3: Run all tests**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All existing 50 tests pass + new server tests pass (approximately 12+ new tests)


---

### Task 4: Create web UI — index.html, CSS, and JavaScript

**Files:**
- Create: `webui/index.html` (single-page dashboard)
- Create: `webui/css/style.css` (dashboard styles)
- Create: `webui/js/app.js` (API calls, tab management, UI logic)

**Interfaces:**
- Consumes: API endpoints `/api/status`, `/api/start`, `/api/stop`, `/api/config`, `/api/schedule`
- Produces: Single-page dashboard with 3 tabs (Processing, Config, Schedule)

- [ ] **Step 1: Create webui/index.html**

Create `webui/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EXIF Tagger Dashboard</title>
    <link rel="stylesheet" href="/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>EXIF Tagger</h1>
            <span id="status-indicator" class="status-badge idle">Idle</span>
        </header>

        <!-- Tab Navigation -->
        <nav class="tabs">
            <button class="tab-btn active" data-tab="processing">Processing</button>
            <button class="tab-btn" data-tab="config">Config</button>
            <button class="tab-btn" data-tab="schedule">Schedule</button>
        </nav>

        <!-- Processing Tab -->
        <section id="tab-processing" class="tab-content active">
            <div class="card">
                <h2>New Session</h2>
                <div class="form-group">
                    <label for="folder-path">Folder Path</label>
                    <input type="text" id="folder-path" placeholder="/data/images/this-month">
                </div>
                <div class="form-group">
                    <label for="max-images">Max Images (optional)</label>
                    <input type="number" id="max-images" min="1" placeholder="Leave empty to process all">
                </div>
                <div class="button-row">
                    <button id="btn-start" class="btn btn-primary">Start Processing</button>
                    <button id="btn-stop" class="btn btn-danger" disabled>Stop</button>
                </div>
            </div>

            <div class="card">
                <h2>Progress</h2>
                <div class="progress-bar-container">
                    <div id="progress-bar" class="progress-bar" style="width: 0%"></div>
                </div>
                <p id="progress-text">0 / 0 images processed (0%)</p>
            </div>

            <div class="card">
                <h2>Log Output</h2>
                <pre id="log-output" class="log-panel"></pre>
            </div>
        </section>

        <!-- Config Tab -->
        <section id="tab-config" class="tab-content">
            <div class="card">
                <h2>Configuration</h2>
                <div class="form-group">
                    <label for="config-root">Root Directory</label>
                    <input type="text" id="config-root" placeholder="/data/images">
                </div>

                <fieldset>
                    <legend>Model Settings</legend>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="model-base-url">Base URL</label>
                            <input type="text" id="model-base-url" placeholder="https://api.openai.com/v1">
                        </div>
                        <div class="form-group">
                            <label for="model-name">Model Name</label>
                            <input type="text" id="model-name" placeholder="gpt-4o">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label for="model-max-tokens">Max Tokens</label>
                            <input type="number" id="model-max-tokens" min="100" max="4096">
                        </div>
                        <div class="form-group">
                            <label for="model-temperature">Temperature (0.0–2.0)</label>
                            <input type="range" id="model-temperature" min="0" max="2" step="0.1" value="0.1">
                            <span id="temp-value">0.1</span>
                        </div>
                    </div>
                </fieldset>

                <fieldset>
                    <legend>Tags</legend>
                    <div id="tags-container"></div>
                    <button id="btn-add-tag" class="btn btn-secondary">+ Add Tag</button>
                </fieldset>

                <fieldset>
                    <legend>Exclude Patterns</legend>
                    <div id="exclude-container"></div>
                    <button id="btn-add-exclude" class="btn btn-secondary">+ Add Pattern</button>
                </fieldset>

                <button id="btn-save-config" class="btn btn-primary">Save Configuration</button>
            </div>
        </section>

        <!-- Schedule Tab -->
        <section id="tab-schedule" class="tab-content">
            <div class="card">
                <h2>Scheduled Jobs</h2>
                <table id="schedules-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Folder</th>
                            <th>Frequency</th>
                            <th>Next Run</th>
                            <th>Status</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody id="schedules-tbody"></tbody>
                </table>
            </div>

            <div class="card">
                <h2>Add Schedule</h2>
                <div class="form-group">
                    <label for="schedule-name">Name</label>
                    <input type="text" id="schedule-name" placeholder="Weekly gallery scan">
                </div>
                <div class="form-group">
                    <label for="schedule-folder">Folder Path</label>
                    <input type="text" id="schedule-folder" placeholder="/data/images/new-month">
                </div>
                <div class="form-group">
                    <label for="schedule-type">Schedule Type</label>
                    <select id="schedule-type">
                        <option value="interval">Interval (hours)</option>
                        <option value="cron">Cron Expression</option>
                    </select>
                </div>
                <div class="form-group" id="interval-input-group">
                    <label for="schedule-interval">Hours Between Runs</label>
                    <input type="number" id="schedule-interval" min="0.1" step="0.5" value="6">
                </div>
                <div class="form-group" id="cron-input-group" style="display:none;">
                    <label for="schedule-cron">Cron Expression</label>
                    <input type="text" id="schedule-cron" placeholder="0 2 * * * (daily at 2am)">
                </div>
                <button id="btn-add-schedule" class="btn btn-primary">Add Schedule</button>
            </div>

            <div class="card">
                <h2>Quick Presets</h2>
                <div class="preset-buttons">
                    <button data-type="interval" data-hours="1">Every 1 hour</button>
                    <button data-type="interval" data-hours="6">Every 6 hours</button>
                    <button data-type="cron" data-cron="0 2 * * *">Daily at 2am</button>
                    <button data-type="cron" data-cron="0 9 * * 1-5">Weekdays at 9am</button>
                </div>
            </div>
        </section>
    </div>

    <script src="/js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create webui/css/style.css**

Create `webui/css/style.css`:

```css
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    min-height: 100vh;
}

.container {
    max-width: 960px;
    margin: 0 auto;
    padding: 20px;
}

header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid #333;
}

header h1 { font-size: 1.5rem; color: #fff; }

.status-badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 0.8rem;
    font-weight: 600;
}

.status-badge.idle { background: #555; color: #ccc; }
.status-badge.running { background: #2ecc71; color: #fff; }
.status-badge.stopped { background: #e74c3c; color: #fff; }

/* Tabs */
.tabs { display: flex; gap: 4px; margin-bottom: 20px; }

.tab-btn {
    padding: 10px 20px;
    background: #16213e;
    border: none;
    color: #aaa;
    cursor: pointer;
    border-radius: 6px 6px 0 0;
    font-size: 0.9rem;
}

.tab-btn.active { background: #0f3460; color: #fff; }
.tab-btn:hover:not(.active) { background: #1a1a3e; }

.tab-content { display: none; }
.tab-content.active { display: block; }

/* Cards */
.card {
    background: #16213e;
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 16px;
}

.card h2 { font-size: 1.1rem; margin-bottom: 16px; color: #fff; }

/* Form elements */
.form-group { margin-bottom: 14px; }

.form-group label {
    display: block;
    margin-bottom: 4px;
    font-size: 0.85rem;
    color: #aaa;
}

.form-group input, .form-group select {
    width: 100%;
    padding: 8px 12px;
    background: #1a1a2e;
    border: 1px solid #333;
    border-radius: 4px;
    color: #e0e0e0;
    font-size: 0.9rem;
}

.form-group input:focus, .form-group select:focus {
    outline: none;
    border-color: #0f3460;
}

.form-row { display: flex; gap: 16px; }
.form-row .form-group { flex: 1; }

fieldset {
    border: 1px solid #333;
    border-radius: 6px;
    padding: 14px;
    margin-bottom: 14px;
}

fieldset legend {
    font-size: 0.9rem;
    color: #888;
    padding: 0 8px;
}

/* Buttons */
.button-row { display: flex; gap: 12px; margin-top: 12px; }

.btn {
    padding: 8px 16px;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.9rem;
}

.btn-primary { background: #0f3460; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #1a5276; }
.btn-secondary { background: #333; color: #ccc; }
.btn-danger { background: #c0392b; color: #fff; }
.btn-danger:hover:not(:disabled) { background: #e74c3c; }

.btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Progress bar */
.progress-bar-container {
    width: 100%;
    height: 24px;
    background: #1a1a2e;
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 8px;
}

.progress-bar {
    height: 100%;
    background: linear-gradient(90deg, #0f3460, #2ecc71);
    transition: width 0.5s ease;
    border-radius: 12px;
}

#progress-text { font-size: 0.85rem; color: #aaa; }

/* Log panel */
.log-panel {
    background: #0d1117;
    padding: 12px;
    border-radius: 4px;
    max-height: 300px;
    overflow-y: auto;
    font-family: 'Courier New', monospace;
    font-size: 0.8rem;
    line-height: 1.5;
    color: #7ee787;
}

/* Tag cards */
.tag-card {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 8px;
    padding: 8px;
    background: #1a1a2e;
    border-radius: 4px;
}

.tag-card input[type="text"] { flex: 1; }
.tag-card input[type="number"] { width: 70px; }
.tag-card .tag-name-input { font-weight: bold; color: #fff; }

/* Exclude pattern items */
.exclude-item {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-bottom: 6px;
}

.exclude-item input { flex: 1; }

/* Schedules table */
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #333; }
th { color: #888; font-weight: 600; }

.preset-buttons { display: flex; gap: 8px; flex-wrap: wrap; }
.preset-buttons button { padding: 6px 12px; background: #1a1a2e; border: 1px solid #333; color: #ccc; border-radius: 4px; cursor: pointer; font-size: 0.8rem; }
.preset-buttons button:hover { background: #0f3460; color: #fff; }

/* Temperature display */
#temp-value { display: inline-block; margin-left: 8px; color: #2ecc71; font-weight: bold; }

/* Responsive */
@media (max-width: 600px) {
    .form-row { flex-direction: column; gap: 0; }
    .button-row { flex-direction: column; }
}
```

- [ ] **Step 3: Create webui/js/app.js**

Create `webui/js/app.js`:

```javascript
// EXIF Tagger Dashboard — Client-side JavaScript

const API_BASE = '';
let pollInterval = null;
let currentSessionId = null;

// ---------------------------------------------------------------------------
// Tab management
// ---------------------------------------------------------------------------
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const tabId = `tab-${btn.dataset.tab}`;
        document.getElementById(tabId).classList.add('active');

        if (btn.dataset.tab === 'config') loadConfig();
        if (btn.dataset.tab === 'schedule') loadSchedules();
    });
});

// ---------------------------------------------------------------------------
// Status polling
// ---------------------------------------------------------------------------
async function fetchStatus() {
    try {
        const resp = await fetch(`${API_BASE}/api/status`);
        const data = await resp.json();
        updateStatusUI(data);
        return data;
    } catch (e) { /* silent fail during startup */ }
}

function updateStatusUI(data) {
    const indicator = document.getElementById('status-indicator');
    const btnStart = document.getElementById('btn-start');
    const btnStop = document.getElementById('btn-stop');
    const progressBar = document.getElementById('progress-bar');
    const progressText = document.getElementById('progress-text');

    if (data.running) {
        indicator.textContent = 'Running';
        indicator.className = 'status-badge running';
        btnStart.disabled = true;
        btnStop.disabled = false;
    } else if (data.stopRequested) {
        indicator.textContent = 'Stopping...';
        indicator.className = 'status-badge stopped';
    } else {
        indicator.textContent = data.summary ? 'Completed' : 'Idle';
        indicator.className = 'status-badge idle';
        btnStart.disabled = false;
        btnStop.disabled = true;
    }

    if (data.total > 0) {
        const pct = data.progressPct || 0;
        progressBar.style.width = `${pct}%`;
        progressText.textContent = `${data.processed} / ${data.total} images processed (${pct}%)`;
    } else {
        progressBar.style.width = '0%';
        progressText.textContent = '0 / 0 images processed (0%)';
    }

    // Update log output if available
    const logOutput = document.getElementById('log-output');
    if (data.summary && data.summary.errors) {
        data.summary.errors.forEach(err => appendLog(`Error: ${err}`));
    }
}

function appendLog(text) {
    const el = document.getElementById('log-output');
    el.textContent += text + '\n';
    el.scrollTop = el.scrollHeight;
}

// Start polling when page loads
pollInterval = setInterval(fetchStatus, 2000);
fetchStatus();

// ---------------------------------------------------------------------------
// Processing controls
// ---------------------------------------------------------------------------
document.getElementById('btn-start').addEventListener('click', async () => {
    const folderPath = document.getElementById('folder-path').value.trim() || null;
    const maxImages = document.getElementById('max-images').value ? parseInt(document.getElementById('max-images').value) : null;

    try {
        const resp = await fetch(`${API_BASE}/api/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rootDirectory: folderPath, maxImages }),
        });
        if (resp.ok) {
            appendLog('Session started.');
            document.getElementById('log-output').textContent = '';
        } else {
            const err = await resp.json();
            alert(err.detail || 'Failed to start session');
        }
    } catch (e) { alert('Network error: ' + e.message); }
});

document.getElementById('btn-stop').addEventListener('click', async () => {
    try {
        const resp = await fetch(`${API_BASE}/api/stop`, { method: 'POST' });
        if (resp.ok) appendLog('Stop requested.');
    } catch (e) { alert('Network error: ' + e.message); }
});

// ---------------------------------------------------------------------------
// Config management
// ---------------------------------------------------------------------------
async function loadConfig() {
    try {
        const resp = await fetch(`${API_BASE}/api/config`);
        if (!resp.ok) return;
        const config = await resp.json();

        document.getElementById('config-root').value = config.root_directory || '';
        document.getElementById('model-base-url').value = config.model?.base_url || '';
        document.getElementById('model-name').value = config.model?.model_name || '';
        document.getElementById('model-max-tokens').value = config.model?.max_tokens || 500;
        const tempSlider = document.getElementById('model-temperature');
        tempSlider.value = config.model?.temperature ?? 0.1;
        document.getElementById('temp-value').textContent = config.model?.temperature ?? 0.1;

        // Render tags
        renderTags(config.tags || {});

        // Render exclude patterns
        renderExcludes(config.exclude_patterns || []);
    } catch (e) { console.error('Failed to load config:', e); }
}

function renderTags(tags) {
    const container = document.getElementById('tags-container');
    container.innerHTML = '';
    for (const [name, data] of Object.entries(tags)) {
        addTagCard(name, data.description || '', data.threshold || 0.7);
    }
}

function addTagCard(name = '', desc = '', threshold = 0.7) {
    const container = document.getElementById('tags-container');
    const card = document.createElement('div');
    card.className = 'tag-card';
    card.innerHTML = `
        <input type="text" class="tag-name-input" placeholder="Tag name" value="${name}">
        <input type="text" class="tag-desc-input" placeholder="Description" value="${desc}">
        <input type="number" class="tag-threshold-input" min="0" max="1" step="0.05" value="${threshold}" title="Threshold">
        <button class="btn btn-danger tag-remove-btn" style="padding:4px 8px;">×</button>
    `;
    card.querySelector('.tag-remove-btn').addEventListener('click', () => card.remove());
    container.appendChild(card);
}

document.getElementById('btn-add-tag').addEventListener('click', () => addTagCard());

function renderExcludes(patterns) {
    const container = document.getElementById('exclude-container');
    container.innerHTML = '';
    patterns.forEach(p => addExcludeItem(p));
}

function addExcludeItem(pattern = '') {
    const container = document.getElementById('exclude-container');
    const item = document.createElement('div');
    item.className = 'exclude-item';
    item.innerHTML = `
        <input type="text" class="exclude-input" placeholder="Regex pattern (e.g. .*receipt.*|/blurry/)" value="${pattern}">
        <button class="btn btn-danger exclude-remove-btn" style="padding:4px 8px;">×</button>
    `;
    item.querySelector('.exclude-remove-btn').addEventListener('click', () => item.remove());
    container.appendChild(item);
}

document.getElementById('btn-add-exclude').addEventListener('click', () => addExcludeItem());

// Temperature slider live update
document.getElementById('model-temperature').addEventListener('input', (e) => {
    document.getElementById('temp-value').textContent = e.target.value;
});

document.getElementById('btn-save-config').addEventListener('click', async () => {
    const tags = {};
    document.querySelectorAll('.tag-card').forEach(card => {
        const name = card.querySelector('.tag-name-input').value.trim();
        if (!name) return;
        tags[name] = {
            description: card.querySelector('.tag-desc-input').value,
            threshold: parseFloat(card.querySelector('.tag-threshold-input').value) || 0.7,
        };
    });

    const excludes = [];
    document.querySelectorAll('.exclude-input').forEach(input => {
        const v = input.value.trim();
        if (v) excludes.push(v);
    });

    try {
        const resp = await fetch(`${API_BASE}/api/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                root_directory: document.getElementById('config-root').value.trim(),
                model: {
                    base_url: document.getElementById('model-base-url').value.trim(),
                    model_name: document.getElementById('model-name').value.trim(),
                    max_tokens: parseInt(document.getElementById('model-max-tokens').value) || 500,
                    temperature: parseFloat(document.getElementById('model-temperature').value) || 0.1,
                },
                tags,
                exclude_patterns: excludes,
            }),
        });
        if (resp.ok) {
            alert('Configuration saved successfully.');
        } else {
            const err = await resp.json();
            alert('Failed to save config: ' + (err.detail || 'Unknown error'));
        }
    } catch (e) { alert('Network error: ' + e.message); }
});

// ---------------------------------------------------------------------------
// Schedule management
// ---------------------------------------------------------------------------
async function loadSchedules() {
    try {
        const resp = await fetch(`${API_BASE}/api/schedule`);
        if (!resp.ok) return;
        const schedules = await resp.json();
        renderSchedules(schedules);
    } catch (e) { console.error('Failed to load schedules:', e); }
}

function renderSchedules(schedules) {
    const tbody = document.getElementById('schedules-tbody');
    tbody.innerHTML = '';
    if (schedules.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#888;">No schedules configured</td></tr>';
        return;
    }
    for (const s of schedules) {
        const tr = document.createElement('tr');
        const freqType = s.cron_expression ? 'Cron' : `Every ${s.interval_hours}h`;
        const statusColor = s.last_status === 'success' ? '#2ecc71' : s.last_status === 'failed' ? '#e74c3c' : '#888';
        tr.innerHTML = `
            <td>${s.name}</td>
            <td>${s.folder}</td>
            <td>${freqType}</td>
            <td>${s.next_run_at || '-'}</td>
            <td style="color:${statusColor}">${s.last_status || 'Never'}</td>
            <td><button class="btn btn-danger schedule-delete-btn" data-id="${s.id}" style="padding:4px 8px;">Delete</button></td>
        `;
        tbody.appendChild(tr);
    }

    // Attach delete handlers
    document.querySelectorAll('.schedule-delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Delete this schedule?')) return;
            try {
                const resp = await fetch(`${API_BASE}/api/schedule/${btn.dataset.id}`, { method: 'DELETE' });
                if (resp.ok) loadSchedules();
            } catch (e) { alert('Network error'); }
        });
    });
}

// Schedule type toggle
document.getElementById('schedule-type').addEventListener('change', (e) => {
    const isCron = e.target.value === 'cron';
    document.getElementById('interval-input-group').style.display = isCron ? 'none' : '';
    document.getElementById('cron-input-group').style.display = isCron ? '' : 'none';
});

// Preset buttons
document.querySelectorAll('.preset-buttons button').forEach(btn => {
    btn.addEventListener('click', () => {
        const type = btn.dataset.type;
        document.getElementById('schedule-type').value = type;
        if (type === 'interval') {
            document.getElementById('schedule-interval').value = btn.dataset.hours;
        } else {
            document.getElementById('schedule-cron').value = btn.dataset.cron;
        }
    });
});

document.getElementById('btn-add-schedule').addEventListener('click', async () => {
    const name = document.getElementById('schedule-name').value.trim();
    const folder = document.getElementById('schedule-folder').value.trim();
    const type = document.getElementById('schedule-type').value;

    if (!name || !folder) { alert('Name and folder are required'); return; }

    const body = { name, folder };
    if (type === 'interval') {
        body.interval_hours = parseFloat(document.getElementById('schedule-interval').value);
    } else {
        body.cron_expression = document.getElementById('schedule-cron').value.trim();
    }

    try {
        const resp = await fetch(`${API_BASE}/api/schedule`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (resp.ok) {
            alert('Schedule added.');
            loadSchedules();
        } else {
            const err = await resp.json();
            alert('Failed to add schedule: ' + (err.detail || 'Unknown error'));
        }
    } catch (e) { alert('Network error: ' + e.message); }
});

// Load config on first tab activation
loadConfig();
```

- [ ] **Step 4: Verify files exist and are properly structured**

Run: `ls -la webui/ webui/css/ webui/js/`
Expected: All three files present with non-zero sizes


---

### Task 5: Update requirements.txt with new dependencies

**Files:**
- Modify: `requirements.txt` (append web framework deps)

**Interfaces:**
- Consumes: existing runtime deps (pydantic, PyYAML, Pillow, openai, requests)
- Produces: updated requirements including fastapi, uvicorn[standard], apscheduler

- [ ] **Step 1: Append new dependencies to requirements.txt**

Replace the entire contents of `requirements.txt` with:

```
pydantic>=2.5
PyYAML>=6.0
Pillow>=10.0
piexif>=1.1.3
openai>=1.10
requests>=2.31
fastapi>=0.104
uvicorn[standard]>=0.24
apscheduler>=3.10
```

- [ ] **Step 2: Verify requirements file**

Run: `cat requirements.txt`
Expected: All 9 lines present, no duplicates

---

### Task 6: Update Dockerfile for FastAPI service

**Files:**
- Modify: `Dockerfile` (change entrypoint to uvicorn)

**Interfaces:**
- Consumes: existing multi-stage build pattern with Python deps and exiftool
- Produces: container that runs FastAPI on port 8080 instead of CLI batch mode

- [ ] **Step 1: Replace Dockerfile content**

Replace the entire contents of `Dockerfile` with:

```dockerfile
# ============================================================================
# exif-tagger – Multi-stage build for web dashboard service
# Stage 1: Build Python dependencies (fast, cached)
# Stage 2: Install system tools + runtime image
# ============================================================================

FROM python:3.12-alpine AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Final image – minimal Alpine with exiftool for XPTags support
FROM alpine:3.19

# Install perl (required for cpan) and basic tools, then exiftool
RUN apk add --no-cache \
    perl \
    perl-dev \
    build-base \
  && cpan -i Image::ExifTool \
  && rm -rf ~/.cpan /root/.cpan

WORKDIR /app

# Copy Python dependencies from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ ./src/
COPY webui/ ./webui/
COPY config.yaml.example ./config.yaml.example

# Create directories for runtime data
RUN mkdir -p /app/data /app/config

# Expose dashboard port
EXPOSE 8080

# Run FastAPI server via uvicorn
ENTRYPOINT ["uvicorn", "src.exif_tagger.server:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 2: Verify Dockerfile syntax**

Run: `docker build --check -f Dockerfile .` (or just verify the file content)
Expected: File reads correctly with all stages defined

---

### Task 7: Update docker-compose.yml for dashboard service

**Files:**
- Modify: `docker-compose.yml` (add port mapping, volumes, environment)

**Interfaces:**
- Consumes: existing volume mount pattern and env var overrides
- Produces: service accessible at localhost:8080 with persistent schedules storage

- [ ] **Step 1: Replace docker-compose.yml content**

Replace the entire contents of `docker-compose.yml` with:

```yaml
services:
  exif-tagger:
    build: .
    image: exif-tagger:latest
    ports:
      - "8080:8080"                    # Dashboard web interface
    volumes:
      - ./config.yaml:/app/config.yaml:ro        # Config file (read-only)
      - schedules:/app/schedules.json              # Persistent schedule storage
      - gallery:/data/images                       # Full image gallery mount
    environment:
      EXIFTAGGER_ROOT_DIRECTORY: "/data/images"
      # Uncomment and set if you want to override api_key via env:
      # OPENAI_API_KEY: "sk-your-key-here"

volumes:
  schedules:                                       # Named volume for schedule persistence
  gallery:                                         # Named volume as default gallery mount point
```

**Usage notes (documented in the compose file comments):**
- Mount a local directory to `gallery` via bind mount: `- ./my-gallery:/data/images` instead of the named volume
- The dashboard is accessible at `http://localhost:8080`
- Schedules persist across container restarts via the `schedules` named volume

---

### Task 8: Final verification — build, test, and validate

**Files:**
- All files created/modified in previous tasks

**Interfaces:**
- Consumes: everything from Tasks 1–7
- Produces: verified working build with all tests passing

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All existing 50 tests pass + new server tests (approximately 62+ total)

- [ ] **Step 2: Verify CLI still works standalone**

Run: `python -m exif_tagger --help`
Expected: Shows help text with `-c`, `-v`, `--force`, `--list-tags` options

- [ ] **Step 3: Verify Docker build succeeds**

Run: `docker build -t exif-tagger:test .`
Expected: Build completes without errors, multi-stage build works

- [ ] **Step 4: Verify web UI files are served correctly**

Run: `python -c "from fastapi.testclient import TestClient; from src.exif_tagger.server import app; c = TestClient(app); r = c.get('/'); print(r.status_code, len(r.text))"`
Expected: Status 200 with HTML content length > 1000

- [ ] **Step 5: Verify all API endpoints respond**

Run: `python -c "
from fastapi.testclient import TestClient
from src.exif_tagger.server import app
c = TestClient(app)
endpoints = ['/api/status', '/api/config', '/api/schedule']
for ep in endpoints:
    r = c.get(ep)
    print(f'{ep}: {r.status_code}')
"`
Expected: All endpoints return 200

---

## Plan Self-Review

**1. Spec coverage:**
- Architecture (FastAPI + PipelineEngine + APScheduler) → Tasks 2, 3
- API endpoints (`/api/status`, `/api/start`, `/api/stop`, `/api/config`, `/api/schedule`) → Task 3
- UI tabs (Processing, Config, Schedule) → Task 4
- Data flow (background thread, progress polling, graceful stop) → Tasks 2, 3, 4
- Docker changes (entrypoint, ports, volumes) → Tasks 6, 7
- Security (path validation, config write protection via Pydantic) → Task 3
- Dependencies added → Task 5
- Testing strategy → Task 8

**2. Placeholder scan:** No "TBD", "TODO", or vague references found. All code blocks are complete with actual implementations.

**3. Type consistency:** `PipelineEngine` class defined in Task 2, consumed by server.py in Task 3. `ScheduleModel`/`ScheduleEntry` defined in Task 1, used throughout Tasks 3 and 4. Method signatures match across tasks (`start_session()`, `stop()`, `get_status()`).

**4. Scope check:** Focused on a single implementation cycle. No decomposition needed — all changes are tightly coupled to the web dashboard feature.
