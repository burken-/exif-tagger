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

    _scheduler = BackgroundScheduler(timezone=timezone.utc)
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
