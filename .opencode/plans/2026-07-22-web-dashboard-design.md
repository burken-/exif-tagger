# Web Dashboard for EXIF Tagger — Design Spec

**Date:** 2026-07-22  
**Status:** Approved by user  

---

## Overview

Transform the existing CLI-based `exif-tagger` tool into a long-running FastAPI service with a web dashboard. The container runs continuously, exposing an HTTP interface for starting/stopping image processing sessions, editing tag configurations, and managing automated schedules. The core pipeline logic remains unchanged — it is extracted from the CLI entry point into reusable functions callable both programmatically and via API.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Browser (Dashboard UI)                         │
│  ┌──────────┬────────────┬──────────────────┐   │
│  │Processing│ Config     │ Schedule         │   │
│  │Tab       │ Tab        │ Tab              │   │
│  └──────────┴────────────┴──────────────────┘   │
└──────────────────────┬──────────────────────────┘
                       │ HTTP/JSON (fetch API)
┌──────────────────────▼──────────────────────────┐
│  FastAPI Server (uvicorn, port 8080)            │
│  ┌─────────────────────────────────────────┐    │
│  │  API Routes                             │    │
│  │  GET  /api/status       - current run   │    │
│  │  POST /api/start        - begin process │    │
│  │  POST /api/stop         - graceful stop │    │
│  │  GET  /api/config       - read config   │    │
│  │  PUT  /api/config       - update config │    │
│  │  GET  /api/schedule     - list schedules│    │
│  │  POST /api/schedule     - add schedule  │    │
│  │  DELETE /api/schedule/<id> - remove     │    │
│  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────┐    │
│  │  Pipeline Engine (existing logic)       │    │
│  │  scan_images() → process_batch()        │    │
│  │  Runs in background thread              │    │
│  └─────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────┐    │
│  │  Scheduler (APScheduler)                │    │
│  │  Simple intervals + cron expressions    │    │
│  └─────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

**Key decisions:**
- Existing `main.py` pipeline logic is extracted into a `PipelineEngine` class callable programmatically.
- A background thread runs the processing loop, reporting progress to an in-memory state object.
- FastAPI serves both the API and static UI files (single-page app).
- No database — config persisted as YAML on disk; schedules stored as JSON file (`/app/schedules.json`).
- The CLI entry point (`python -m exif_tagger`) remains fully functional for standalone use.

---

## API Endpoints

| Method | Path | Purpose | Request Body | Response |
|--------|------|---------|--------------|----------|
| `GET`  | `/api/status` | Current run state | — | `{running: bool, processed: int, total: int, currentImage: str \| null, progressPct: number}` |
| `POST` | `/api/start` | Begin processing session | `{rootDirectory: string, maxImages: number}` | `{sessionId: string, status: "started"}` |
| `POST` | `/api/stop`  | Gracefully stop current run | — | `{status: "stopped", processed: int}` |
| `GET`  | `/api/config` | Read current config | — | Full YAML config object |
| `PUT`  | `/api/config` | Update config in-place | Partial config changes | `{status: "updated"}` |
| `POST` | `/api/schedule` | Add a schedule | `{name, folder, interval/cron, enabled}` | `{id: string}` |
| `GET`  | `/api/schedule` | List all schedules | — | Array of schedule objects |
| `DELETE`| `/api/schedule/:id` | Remove schedule | — | `{status: "deleted"}` |

---

## UI Components (3 Tabs)

### Processing Tab
- Folder path input (pre-filled from config or last used value).
- Max images slider/input for current session limit.
- Start/Stop buttons with visual state indicator (green = running, gray = idle).
- Live progress bar showing processed / total count and percentage.
- Log panel showing recent processing output lines (scrollable, auto-scroll to bottom).

### Config Tab
- YAML editor area with basic syntax highlighting (via CodeMirror or similar lightweight library loaded from CDN).
- Tag definitions rendered as cards: name, description text field, threshold slider (0–1 step 0.05).
- Add/remove tag buttons per card.
- Exclude patterns list with add/remove inputs.
- Save button writes updated config to `/app/config.yaml` on disk; validates before writing.

### Schedule Tab
- List of active schedules showing: name, folder path, frequency type (interval/cron), next run time, enabled toggle, last run status.
- "Add schedule" form with fields: name, folder path, interval type selector (simple preset or custom cron expression).
- Simple presets: every 1 hour, every 6 hours, daily at X, weekly on day X at Y.
- Custom cron editor with a visual grid for minute/hour/day-of-month/month/day-of-week selection plus raw expression input.
- Enable/disable toggle per schedule; delete button.

---

## Data Flow

### Starting a Processing Session
1. User enters folder path and max images, clicks Start.
2. FastAPI validates inputs, creates a `PipelineEngine` instance with the config.
3. A background thread starts the pipeline loop:
   - Scans directory for supported image files (existing logic).
   - Checks checkpoint file to skip already-tagged images.
   - Processes up to `maxImages` new images (or all if not specified).
   - Reports progress after each image via a thread-safe queue into `ProcessingState`.
4. UI polls `/api/status` every 2 seconds, updates progress bar and log panel.
5. On completion or stop, status reflects final state; checkpoint persists on disk.

### Graceful Stop
1. User clicks Stop → `POST /api/stop`.
2. Pipeline engine sets a `_stop_requested` flag.
3. Current image finishes processing (no partial writes), then loop exits cleanly.
4. Checkpoint is saved with all completed images.
5. Status reflects stopped state with total processed count.

### Config Updates
1. User edits tags, thresholds, or exclude patterns in the UI.
2. On Save, config is validated through existing Pydantic models (`Config`, `TagDefinition`).
3. Validated config is written to `/app/config.yaml` via PyYAML safe_dump.
4. Changes take effect on next processing session (no hot-reload of running pipeline).

### Schedule Execution
1. APScheduler runs scheduled jobs in a separate thread pool.
2. Each schedule triggers the same pipeline logic as manual start, using its configured folder and default max images (or unlimited).
3. Schedule metadata (last run time, last status) is updated after each execution.
4. Schedules persisted to `/app/schedules.json` — loaded on startup, saved on every change.

---

## File Structure Changes

```
/app/exif-tagger/
├── src/exif_tagger/
│   ├── __init__.py
│   ├── __main__.py              # CLI entry point (unchanged)
│   ├── ai_client.py             # Unchanged
│   ├── config.py                # Unchanged
│   ├── exif_writer.py           # Unchanged
│   ├── image_scanner.py         # Unchanged
│   ├── main.py                  # Refactored: extract PipelineEngine class
│   ├── server.py                # NEW: FastAPI app, routes, background tasks
│   └── models/
│       └── schema.py            # Unchanged (add Schedule model)
├── webui/                       # NEW: static frontend assets
│   ├── index.html               # Single-page dashboard
│   ├── css/style.css            # Dashboard styles
│   └── js/app.js                # API calls, UI logic, tab management
├── Dockerfile                   # Updated: install uvicorn + APScheduler, serve FastAPI
├── docker-compose.yml           # Updated: port 8080 mapping, volume mounts
├── requirements.txt             # Added: fastapi, uvicorn, apscheduler
└── schedules.json               # NEW: runtime schedule storage (created on first add)
```

---

## Docker Changes

### Dockerfile Updates
- Add `fastapi`, `uvicorn[standard]`, and `apscheduler` to requirements.
- Change ENTRYPOINT from `python -m exif_tagger` to `uvicorn src.exif_tagger.server:app --host 0.0.0.0 --port 8080`.
- Add volume mount for `/app/config.yaml` (config) and `/app/data` (gallery + checkpoints).

### docker-compose.yml Updates
- Map port `8080:8080` for dashboard access.
- Mount gallery directory at `/app/data/images`.
- Mount config at `/app/config.yaml`.
- Add persistent volume for schedules (`schedules:/app/schedules.json`).

---

## Security Considerations

- **Path validation:** All folder paths validated against whitelist (same as existing env var validation in `config.py`).
- **Config write protection:** Config updates validated through Pydantic models before writing to disk.
- **No auth required** — container is intended for trusted internal network use only.
- **Schedules stored locally** — no external persistence; schedules survive container restarts via volume mount.

---

## Dependencies Added

| Package | Purpose |
|---------|---------|
| fastapi ≥0.104 | Web framework |
| uvicorn[standard] ≥0.24 | ASGI server |
| apscheduler ≥3.10 | Job scheduling (cron + intervals) |

---

## Testing Strategy

- Existing 50 tests remain unchanged and passing — no core logic is modified.
- New tests for `server.py`: API endpoint handlers, config validation, schedule CRUD operations.
- Integration test: start FastAPI server in test mode, send requests to `/api/start`, verify status updates and checkpoint creation.
