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
