"""Main script for exif-tagger – CLI entry point.

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
    """Format a summary dictionary into human-readable text.

    Args:
        summary: Dictionary with run statistics

    Returns:
        Formatted summary string for display
    """
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


def run(
    config_path: str,
    verbose: bool = False,
    force_resume: bool = False,
) -> int:
    """Execute the full tagging pipeline. Returns exit code (0=success, 1=error).

    PERFORMANCE: Uses stream processing - each image is processed immediately
    (AI → EXIF → checkpoint update) instead of accumulating all results in memory.
    Checkpoints are written every CHECKPOINT_BATCH_SIZE images to reduce I/O overhead.

    Args:
        config_path: Path to configuration file
        verbose: Enable per-image logging during processing
        force_resume: Ignore existing checkpoint and restart from beginning

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # SECURITY: Setup logging with secret redaction to prevent API key exposure
    from exif_tagger.ai_client import setup_secure_logging
    
    log_level = logging.DEBUG if verbose else logging.INFO
    setup_secure_logging(log_level)
    logger = logging.getLogger("exif_tagger")

    try:
        # ---- 1. Load configuration ----
        from exif_tagger.config import load_config, get_resume_info, save_checkpoint
        from exif_tagger.models.schema import Config, ImageCheckpoint

        config: Config = load_config(config_path)
        config.validate()
        config.validate_exclude_patterns()

        if not config.tags:
            logger.error("No tags configured in %s. Add 'tags:' section to continue.", config_path)
            return 1

        _log_tag_list(config.tags)

        # ---- 2. Scan images ----
        from exif_tagger.image_scanner import scan_images, filter_by_checkpoint

        all_images = scan_images(
            root_directory=config.root_directory,
            exclude_patterns=config.exclude_patterns or [],
        )

        total_found = len(all_images)
        if total_found == 0:
            logger.warning("No images found in %s. Nothing to do.", config.root_directory)
            return 0

        # ---- 3. Checkpoint / resume logic ----
        checkpoint: dict[str, ImageCheckpoint] = {}
        skipped_by_checkpoint = 0
        already_tagged = 0  # from previous runs (status == "done")

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

        # Separate images into to_process vs already-done
        images_to_process, done_from_cp = filter_by_checkpoint(all_images, checkpoint)
        skipped_by_checkpoint += done_from_cp

        logger.info(
            "%d total found, %d from previous run (skipped), %d to process now.",
            total_found, skipped_by_checkpoint, len(images_to_process),
        )

        if not images_to_process:
            logger.info("All images already processed – nothing to do.")
            return 0

        # ---- 4-5. Process images with streaming (AI → EXIF → checkpoint) ----
        # PERFORMANCE: Stream processing - no accumulation of AI results in memory
        successfully_tagged = 0
        failed_count = 0
        errors: list[str] = []
        checkpoint_images: dict[str, ImageCheckpoint] = dict(checkpoint)
        
        # Batch checkpoint tracking
        checkpoint_batch_counter = 0

        for i, img_path in enumerate(images_to_process, start=1):
            if verbose:
                logger.info("Processing image %d/%d: %s", i, len(images_to_process), img_path.name)

            try:
                # Call AI immediately (streaming - no accumulation)
                from exif_tagger.ai_client import tag_image_with_ai
                response = tag_image_with_ai(config.ai_model, img_path, config.tags)

                # Determine which tags actually match (score >= threshold)
                matched_tag_names = []
                for tr in response.results:
                    tag_def = config.tags.get(tr.tag_name)
                    if tag_def and tr.score >= tag_def.threshold:
                        matched_tag_names.append(tr.tag_name)

                # Write to EXIF immediately (append mode – only truly new tags)
                from exif_tagger.exif_writer import tag_image_exif
                modified, n_new = tag_image_exif(img_path, matched_tag_names)
                
                if modified:
                    successfully_tagged += 1
                    logger.info(
                        "  → Written %d new XPTags: %s",
                        n_new, ", ".join(matched_tag_names),
                    )
                elif verbose:
                    logger.debug("  → All tags already present – no change.")

                # Update checkpoint immediately
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

            # PERFORMANCE: Batch checkpoint writes every N images instead of after each one
            checkpoint_batch_counter += 1
            if checkpoint_batch_counter >= CHECKPOINT_BATCH_SIZE:
                save_checkpoint(config.root_directory, total_found, checkpoint_images)
                checkpoint_batch_counter = 0
                if verbose:
                    logger.debug("Checkpoint saved (batch of %d)", CHECKPOINT_BATCH_SIZE)

        # CRITICAL: Ensure final checkpoint write happens after loop completes
        save_checkpoint(config.root_directory, total_found, checkpoint_images)

        # ---- 6. Summary ----
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

        if verbose:
            logger.info(_format_summary_text(summary))
        else:
            # Quiet mode – only print summary at end
            for line in _format_summary_text(summary).split("\n"):
                print(line)

        return 0 if failed_count == 0 and not errors else 1

    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        print(f"exif-tagger fatal error: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.list_tags:
        # Quick tag-list mode – minimal config load (no logging needed)
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
