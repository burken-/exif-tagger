"""Huvudscript för exif-tagger – CLI entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


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


def _format_summary_text(summary):
    """Format a RunSummary object into human-readable text."""
    lines = [
        "",
        "=" * 60,
        "RUN SUMMARY",
        "=" * 60,
        f"Root directory: {summary.root_directory}",
        f"Total images found:   {summary.total_images_found}",
        f"Processed this run:   {summary.total_processed}",
        f"Newly tagged:         {summary.successfully_tagged}",
        f"Already had tags:     {summary.already_tagged}",
        f"Skipped (checkpoint): {summary.skipped_by_checkpoint}",
        f"Failed:               {summary.failed}",
    ]

    if summary.errors:
        lines.append("")
        lines.append("Errors:")
        for err in summary.errors[:10]:  # Max 10 errors shown
            lines.append(f"  - {err}")
        if len(summary.errors) > 10:
            lines.append(f"  ... and {len(summary.errors) - 10} more")

    lines.extend(["", "=" * 60])
    return "\n".join(lines)


def run(
    config_path: str,
    verbose: bool = False,
    force_resume: bool = False,
) -> int:
    """Execute the full tagging pipeline. Returns exit code (0=success, 1=error)."""

    # Setup logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
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
        checkpoint = {}
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

        # ---- 4. Tag images with AI ----
        from exif_tagger.ai_client import tag_images_batch
        from exif_tagger.exif_writer import tag_image_exif, get_existing_xptags

        ai_results = tag_images_batch(
            model_config=config.ai_model,
            image_paths=images_to_process,
            tag_definitions=config.tags,
            verbose=verbose,
        )

        # ---- 5. Write EXIF tags and update checkpoint ----
        successfully_tagged = 0
        failed_count = 0
        errors: list[str] = []
        all_checkpoint_images = dict(checkpoint)

        for img_path in images_to_process:
            if verbose:
                logger.info("Writing EXIF for %s ...", img_path.name)

            try:
                response = ai_results.get(img_path)
                if response is None or not response.results:
                    # No tags matched – still mark as done but with 0 new
                    all_checkpoint_images[str(img_path.resolve())] = ImageCheckpoint(
                        path=str(img_path), status="done", matched_tags=[], error=None,
                    )
                    continue

                # Determine which tags actually match (score >= threshold)
                matched_tag_names = []
                for tr in response.results:
                    tag_def = config.tags.get(tr.tag_name)
                    if tag_def and tr.score >= tag_def.threshold:
                        matched_tag_names.append(tr.tag_name)

                # Write to EXIF (append mode – only truly new tags)
                modified, n_new = tag_image_exif(img_path, matched_tag_names)
                if modified:
                    successfully_tagged += 1
                    logger.info(
                        "  → Written %d new XPTags: %s",
                        n_new, ", ".join(matched_tag_names),
                    )
                elif verbose:
                    logger.debug("  → All tags already present – no change.")

                all_checkpoint_images[str(img_path.resolve())] = ImageCheckpoint(
                    path=str(img_path), status="done", matched_tags=matched_tag_names, error=None,
                )

            except Exception as exc:
                failed_count += 1
                errors.append(f"{img_path.name}: {exc}")
                logger.error("Failed to process %s: %s", img_path.name, exc)
                all_checkpoint_images[str(img_path.resolve())] = ImageCheckpoint(
                    path=str(img_path), status="failed", matched_tags=[], error=str(exc),
                )

            # Save checkpoint after each image so we can resume from here if interrupted
            save_checkpoint(config.root_directory, total_found, all_checkpoint_images)

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
    parser = _build_parser()
    args = parser.parse_args()

    if args.list_tags:
        # Quick tag-list mode – minimal config load
        from exif_tagger.config import load_config
        from exif_tagger.models.schema import Config
        config: Config = load_config(args.config)
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
