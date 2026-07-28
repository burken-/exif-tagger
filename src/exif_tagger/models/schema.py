"""Pydantic-modeller för exif-tagger-konfiguration och AI-respons."""

from __future__ import annotations

import re
import time
from pathlib import Path

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Image support – vilka filändelser vi accepterar
# ---------------------------------------------------------------------------
IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif"}
)

# ---------------------------------------------------------------------------
# Model configuration (OpenAI-compatible endpoint)
# ---------------------------------------------------------------------------
class ModelConfig(BaseModel):
    """Konfiguration för vision-modellen som anropas via OpenAI-compatible API."""

    base_url: str = Field(
        description="Base URL to the OpenAI-compatible API endpoint "
        "(e.g. https://api.openai.com/v1)"
    )
    model_name: str = Field(
        description="Name of the vision model (e.g. gpt-4o, claude-3-opus via bridge)"
    )
    api_key: str | None = Field(
        default=None,
        description="API key for authentication. Can be set via env var OPENAI_API_KEY.",
    )
    max_tokens: int = Field(default=500, ge=100, le=4096)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional parameters passed directly to the vision API call. "
        "Explicit fields like temperature and max_tokens take priority over duplicate keys.",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def _resolve_from_env(cls, value: str | None) -> str | None:
        """If no api_key is set in config, fall back to OPENAI_API_KEY env var."""
        if not value:
            return None
        return value

    model_config = ConfigDict(extra='allow')
# Tag definition
# ---------------------------------------------------------------------------
class TagDefinition(BaseModel):
    """En enskild tagg med beskrivning och tröskelvärde för matchning."""

    description: str = Field(
        description="Beskrivning av vad en bild ska uppfylla för att matcha denna tagg"
    )
    threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Tröskel (0-1). Bilder med score >= threshold får taggen.",
    )


# ---------------------------------------------------------------------------
# Top-level configuration
# ---------------------------------------------------------------------------
class Config(BaseModel):
    """Hela konfigurationen av exif-tagger."""

    root_directory: str = Field(
        default="/data/images",
        description="Sökväg till rot-mappen som ska skannas rekursivt",
    )
    ai_model: ModelConfig = Field(alias="model", default_factory=ModelConfig)
    tags: dict[str, TagDefinition] = Field(default_factory=dict)
    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="Reguljära uttryck för sökväg som ska exkluderas från körningen.",
    )
    max_image_dimension: int = Field(
        default=720,
        ge=100,
        le=4096,
        description="Maximal bilddimension (bred eller hög) innan skalning till AI-modellen.",
    )

    # Validation & convenience methods
    def validate(self) -> None:
        """Run extra validation beyond Pydantic's built-in checks."""
        root = Path(self.root_directory)
        if not root.exists():
            raise ValueError(f"root_directory does not exist: {self.root_directory}")
        if not root.is_dir():
            raise ValueError(f"root_directory is not a directory: {self.root_directory}")

    def validate_exclude_patterns(self) -> None:
        """Verify that all exclude patterns compile as valid regex."""
        for pattern in self.exclude_patterns:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"Invalid regex pattern '{pattern}': {exc}"
                ) from exc

    @field_validator("tags", mode="before")
    @classmethod
    def _parse_tags(cls, value):  # type: ignore[no-untyped-def]
        """Handle case where tags come in as plain strings (no threshold)."""
        if isinstance(value, list):
            # Support format like [{"name": "landskap", "description": "..."}]
            result = {}
            for item in value:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("tag_name", "")
                    tag_def = TagDefinition(**item)  # type: ignore[arg-type]
                    result[str(name)] = tag_def
            return result
        if isinstance(value, str):
            raise ValueError(
                "tags must be a dict of {tag_name: {description, threshold}} objects"
            )
        return value

    model_config = ConfigDict(extra='allow')


# ---------------------------------------------------------------------------
# AI response model (structured output from vision model)
# ---------------------------------------------------------------------------
class TagResult(BaseModel):
    """One tag evaluation result from the AI."""

    tag_name: str
    score: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    reason: str | None = None


class TaggingResponse(BaseModel):
    """Full response from vision model for a single image."""

    results: list[TagResult]
    summary: str | None = None


# ---------------------------------------------------------------------------
# Checkpoint data (persisted to JSON)
# ---------------------------------------------------------------------------
class ImageCheckpoint(BaseModel):
    """Status for a single processed image."""

    path: str
    status: str  # "pending", "done", "failed"
    matched_tags: list[str] = Field(default_factory=list)
    error: str | None = None


class CheckpointData(BaseModel):
    """Full checkpoint – tracks progress for resumable runs."""

    version: int = Field(default=1)
    created_at: str  # ISO timestamp
    root_directory: str
    total_images: int
    processed: int
    images: dict[str, ImageCheckpoint]  # path -> status


# ---------------------------------------------------------------------------
# Summary statistics (reported after run completes)
# ---------------------------------------------------------------------------
class RunSummary(BaseModel):
    """Statistics for a completed or interrupted run."""

    root_directory: str
    total_images_found: int
    total_processed: int
    successfully_tagged: int
    already_tagged: int  # had tags from before, unchanged
    skipped_by_checkpoint: int
    failed: int
    failed_apis: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Schedule configuration (persisted to schedules.json)
# ---------------------------------------------------------------------------
class ScheduleModel(BaseModel):
    """A single scheduled processing job."""

    id: str = Field(
        default_factory=lambda: f"schedule_{int(time.time())}_{hash(str(time.time())) % 10000}"
    )
    name: str = Field(description="Human-readable schedule name")
    folder: str = Field(description="Root directory to scan for images")
    max_images: int | None = Field(default=None, description="Max images per run (None = all)")
    interval_hours: float | None = Field(
        default=None, ge=0.1, description="Interval in hours (for simple intervals)"
    )
    cron_expression: str | None = Field(
        default=None, description="Cron expression (e.g. '0 2 * * *')"
    )
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
